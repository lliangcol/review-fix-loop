from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from review_fix_loop.cli import main
from review_fix_loop.config import load_effective_config
from review_fix_loop.slices import assign_slice


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test User")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("print('hello')\n", encoding="utf-8")
    git(repo, "add", "src/app.py")
    git(repo, "commit", "-m", "initial")
    return repo


def write_config(repo: Path, gates: list[dict], rule_files: list[str] | None = None) -> Path:
    config = {
        "version": 1,
        "rule_files": rule_files or [],
        "modes": {
            "normal_loop": {"scope": ["staged", "unstaged", "untracked"]},
            "large_merge": {"baseline": "main", "scope": ["merge_base_to_head", "staged", "unstaged", "untracked"]},
        },
        "slices": [{"id": "source", "paths": ["src/**"], "risk": "medium"}],
        "gates": gates,
    }
    path = repo / "gates.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def snapshot(capsys, repo: Path, config: Path, cache: Path) -> dict:
    code = main([
        "snapshot",
        "--repo",
        str(repo),
        "--config",
        str(config),
        "--mode",
        "normal_loop",
        "--pass",
        "1",
        "--final-pass",
        "--write-run-record",
        "--cache-dir",
        str(cache),
    ])
    captured = capsys.readouterr()
    assert code == 0, captured.err
    return json.loads(captured.out)


def test_final_always_gate_runs_and_warning_below_fail_level_does_not_fail(capsys, tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    config = write_config(repo, [
        {
            "id": "warn-gate",
            "argv": [sys.executable, "-c", "print('src/app.py:1:warning only')"],
            "scope": "all",
            "filter_mode": "nofilter",
            "fail_level": "error",
            "blocking": True,
            "timeout_seconds": 30,
            "final_always": True,
            "parser": {
                "type": "regex-lines",
                "pattern": "^(?P<file>[^:]+):(?P<line>\\d+):(?P<message>.*)$",
                "severity": "warning",
            },
        }
    ])
    snap = snapshot(capsys, repo, config, tmp_path / "cache")
    assert snap["planned_gates"] == ["warn-gate"]

    code = main(["gate", "--repo", str(repo), "--config", str(config), "--snapshot", snap["snapshot_path"]])
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert code == 0
    assert result["gates"][0]["status"] == "passed"
    assert result["diagnostics"][0]["severity"] == "warning"


def test_warning_below_fail_level_with_nonzero_tool_exit_does_not_fail(capsys, tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    config = write_config(repo, [
        {
            "id": "warn-gate",
            "argv": [sys.executable, "-c", "import sys; print('src/app.py:1:warning only'); sys.exit(1)"],
            "scope": "all",
            "filter_mode": "nofilter",
            "fail_level": "error",
            "blocking": True,
            "timeout_seconds": 30,
            "final_always": True,
            "parser": {
                "type": "regex-lines",
                "pattern": "^(?P<file>[^:]+):(?P<line>\\d+):(?P<message>.*)$",
                "severity": "warning",
            },
        }
    ])
    snap = snapshot(capsys, repo, config, tmp_path / "cache")

    code = main(["gate", "--repo", str(repo), "--config", str(config), "--snapshot", snap["snapshot_path"]])
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert code == 0
    assert result["gates"][0]["exit_code"] == 1
    assert result["gates"][0]["status"] == "passed"
    assert result["diagnostics"][0]["severity"] == "warning"


def test_config_hash_mismatch_requires_fresh_snapshot(capsys, tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    config = write_config(repo, [
        {
            "id": "final",
            "argv": [sys.executable, "-c", "print('ok')"],
            "scope": "all",
            "final_always": True,
            "parser": {"type": "exit-code"},
        }
    ])
    snap = snapshot(capsys, repo, config, tmp_path / "cache")
    changed = json.loads(config.read_text(encoding="utf-8"))
    changed["slices"].append({"id": "docs", "paths": ["docs/**"], "risk": "low"})
    config.write_text(json.dumps(changed), encoding="utf-8")

    code = main(["gate", "--repo", str(repo), "--config", str(config), "--snapshot", snap["snapshot_path"]])
    captured = capsys.readouterr()

    assert code == 1
    assert "fresh snapshot" in captured.err


def test_rule_hash_mismatch_requires_fresh_snapshot(capsys, tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    (repo / "RULES.md").write_text("first version\n", encoding="utf-8")
    config = write_config(repo, [
        {
            "id": "final",
            "argv": [sys.executable, "-c", "print('ok')"],
            "scope": "all",
            "final_always": True,
            "parser": {"type": "exit-code"},
        }
    ], rule_files=["RULES.md"])
    snap = snapshot(capsys, repo, config, tmp_path / "cache")
    (repo / "RULES.md").write_text("second version\n", encoding="utf-8")

    code = main(["gate", "--repo", str(repo), "--config", str(config), "--snapshot", snap["snapshot_path"]])
    captured = capsys.readouterr()

    assert code == 1
    assert "rule file hashes differ" in captured.err
    assert "fresh snapshot" in captured.err


def test_nonblocking_json_diagnostic_does_not_fail_blocking_gate(capsys, tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    script = (
        "import json; "
        "print(json.dumps({'diagnostics':[{'severity':'error','message':'advisory','blocking':False}]}))"
    )
    config = write_config(repo, [
        {
            "id": "advisory",
            "argv": [sys.executable, "-c", script],
            "scope": "all",
            "final_always": True,
            "blocking": True,
            "parser": {"type": "json-diagnostics"},
        }
    ])
    snap = snapshot(capsys, repo, config, tmp_path / "cache")

    code = main(["gate", "--repo", str(repo), "--config", str(config), "--snapshot", snap["snapshot_path"]])
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert code == 0
    assert result["gates"][0]["status"] == "passed"
    assert result["diagnostics"][0]["blocking"] is False


def test_malformed_json_diagnostics_output_is_gate_failure(capsys, tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    config = write_config(repo, [
        {
            "id": "bad-json",
            "argv": [sys.executable, "-c", "print('not json')"],
            "scope": "all",
            "final_always": True,
            "blocking": True,
            "parser": {"type": "json-diagnostics"},
        }
    ])
    snap = snapshot(capsys, repo, config, tmp_path / "cache")

    code = main(["gate", "--repo", str(repo), "--config", str(config), "--snapshot", snap["snapshot_path"]])
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert code == 1
    assert result["gates"][0]["status"] == "failed"
    assert result["diagnostics"][0]["rule"] == "json-diagnostics"
    assert "Could not parse JSON diagnostics" in result["diagnostics"][0]["message"]


def test_invalid_json_diagnostics_shape_is_gate_failure(capsys, tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    config = write_config(repo, [
        {
            "id": "bad-shape",
            "argv": [sys.executable, "-c", "print('{\"diagnostics\":\"not-a-list\"}')"],
            "scope": "all",
            "final_always": True,
            "blocking": True,
            "parser": {"type": "json-diagnostics"},
        }
    ])
    snap = snapshot(capsys, repo, config, tmp_path / "cache")

    code = main(["gate", "--repo", str(repo), "--config", str(config), "--snapshot", snap["snapshot_path"]])
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert code == 1
    assert result["gates"][0]["status"] == "failed"
    assert "must be a list" in result["diagnostics"][0]["message"]


def test_missing_gate_command_is_reported_as_gate_failure(capsys, tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    config = write_config(repo, [
        {
            "id": "missing-command",
            "argv": ["review-fix-loop-command-that-does-not-exist"],
            "scope": "all",
            "final_always": True,
            "blocking": True,
            "parser": {"type": "exit-code"},
        }
    ])
    snap = snapshot(capsys, repo, config, tmp_path / "cache")

    code = main(["gate", "--repo", str(repo), "--config", str(config), "--snapshot", snap["snapshot_path"]])
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert code == 1
    assert result["gates"][0]["status"] == "failed"
    assert result["gates"][0]["exit_code"] == -2
    assert "Could not execute gate command" in result["gates"][0]["stderr_summary"]


def test_generic_adapter_checks_untracked_whitespace_without_index_mutation(capsys, tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    config = Path(__file__).resolve().parents[1] / "adapters" / "generic" / "gates.json"
    (repo / "src" / "new.py").write_text("print('new')  \n", encoding="utf-8")

    snap = snapshot(capsys, repo, config, tmp_path / "cache")
    assert "untracked-whitespace" in snap["planned_gates"]

    code = main(["gate", "--repo", str(repo), "--config", str(config), "--snapshot", snap["snapshot_path"]])
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    status = subprocess.run(
        ["git", "-C", str(repo), "status", "--short", "--", "src/new.py"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    assert code == 1
    assert result["gates"][0]["id"] == "untracked-whitespace"
    assert result["gates"][0]["status"] == "failed"
    assert result["diagnostics"][0]["file"] == "src/new.py"
    assert result["diagnostics"][0]["line"] == 1
    assert result["diagnostics"][0]["message"] == "trailing whitespace."
    assert status.stdout.strip() == "?? src/new.py"


def test_regex_parser_requires_pattern(capsys, tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    config = write_config(repo, [
        {
            "id": "bad-regex",
            "argv": [sys.executable, "-c", "print('x')"],
            "scope": "all",
            "final_always": True,
            "parser": {"type": "regex-lines"},
        }
    ])

    code = main([
        "snapshot",
        "--repo",
        str(repo),
        "--config",
        str(config),
        "--mode",
        "normal_loop",
        "--pass",
        "1",
        "--final-pass",
    ])
    captured = capsys.readouterr()

    assert code == 1
    assert "requires a pattern" in captured.err


def test_generic_adapter_classifies_public_project_files() -> None:
    repo = Path(__file__).resolve().parents[1]
    config, _, _ = load_effective_config(repo, repo / "adapters" / "generic" / "gates.json")
    slices = config["slices"]

    expected = {
        ".github/workflows/ci.yml": "project-config",
        ".gitignore": "project-config",
        "pyproject.toml": "project-config",
        "MANIFEST.in": "project-config",
        "adapters/project-template/README.md": "project-config",
        "README.zh-CN.md": "docs",
        "CHANGELOG.md": "docs",
        "LICENSE": "docs",
        "docs/quickstart.md": "docs",
        "examples/adapters/python-basic/gates.json": "docs",
    }

    for path, slice_id in expected.items():
        assert assign_slice(path, slices) == slice_id
