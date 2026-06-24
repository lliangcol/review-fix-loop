from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from review_fix_loop.cli import main


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test User")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("print('hello')\nprint('stable')\n", encoding="utf-8")
    git(repo, "add", "src/app.py")
    git(repo, "commit", "-m", "initial")
    return repo


def write_config(repo: Path, gates: list[dict]) -> Path:
    config = {
        "version": 1,
        "rule_files": [],
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


def snapshot(capsys, repo: Path, config: Path, cache: Path, *extra: str) -> dict:
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
        "--write-run-record",
        "--cache-dir",
        str(cache),
        *extra,
    ])
    captured = capsys.readouterr()
    assert code == 0, captured.err
    return json.loads(captured.out)


def test_final_pass_changes_snapshot_identity(capsys, tmp_path: Path) -> None:
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
    git(repo, "add", "gates.json")
    git(repo, "commit", "-m", "add config")

    normal = snapshot(capsys, repo, config, tmp_path / "cache-a")
    final = snapshot(capsys, repo, config, tmp_path / "cache-b", "--final-pass")

    assert normal["planned_gates"] == []
    assert final["planned_gates"] == ["final"]
    assert normal["snapshot_id"] != final["snapshot_id"]


def test_relative_cache_dir_is_repo_relative(capsys, tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    config = write_config(repo, [])
    (repo / "src" / "app.py").write_text("print('dirty')\n", encoding="utf-8")

    snap = snapshot(capsys, repo, config, Path(".review-fix-loop"))

    assert Path(snap["snapshot_path"]).is_relative_to(repo / ".review-fix-loop")


def test_added_filter_ignores_out_of_diff_diagnostics_and_nonzero_exit(capsys, tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    (repo / "src" / "app.py").write_text("print('changed')\nprint('stable')\n", encoding="utf-8")
    script = "import sys; print('src/app.py:2:error outside changed line'); sys.exit(1)"
    config = write_config(repo, [
        {
            "id": "line-filter",
            "argv": [sys.executable, "-c", script],
            "scope": "unstaged",
            "filter_mode": "added",
            "fail_level": "error",
            "blocking": True,
            "parser": {
                "type": "regex-lines",
                "pattern": "^(?P<file>[^:]+):(?P<line>\\d+):(?P<message>.*)$",
                "severity": "error",
            },
        }
    ])
    snap = snapshot(capsys, repo, config, tmp_path / "cache")

    code = main(["gate", "--repo", str(repo), "--config", str(config), "--snapshot", snap["snapshot_path"]])
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert code == 0
    assert result["gates"][0]["status"] == "passed"
    assert result["gates"][0]["filtered_diagnostics_count"] == 1
    assert result["diagnostics"] == []


def test_invalid_json_diagnostic_severity_fails(capsys, tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    script = "import json; print(json.dumps({'diagnostics':[{'severity':'fatal','message':'bad severity'}]}))"
    config = write_config(repo, [
        {
            "id": "bad-severity",
            "argv": [sys.executable, "-c", script],
            "scope": "all",
            "final_always": True,
            "parser": {"type": "json-diagnostics"},
        }
    ])
    snap = snapshot(capsys, repo, config, tmp_path / "cache", "--final-pass")

    code = main(["gate", "--repo", str(repo), "--config", str(config), "--snapshot", snap["snapshot_path"]])
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert code == 1
    assert result["diagnostics"][0]["rule"] == "invalid-severity"


def test_gate_output_and_record_are_redacted(capsys, tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    script = "print('api_key=super-secret')"
    config = write_config(repo, [
        {
            "id": "secret",
            "argv": [sys.executable, "-c", script],
            "scope": "all",
            "final_always": True,
            "parser": {"type": "exit-code"},
        }
    ])
    snap = snapshot(capsys, repo, config, tmp_path / "cache", "--final-pass")

    code = main(["gate", "--repo", str(repo), "--config", str(config), "--snapshot", snap["snapshot_path"]])
    captured = capsys.readouterr()
    result_text = captured.out
    record_text = Path(snap["run_record_path"]).read_text(encoding="utf-8")
    gates_text = (Path(snap["run_record_path"]).parent / "gates.json").read_text(encoding="utf-8")

    assert code == 0
    assert "super-secret" not in result_text
    assert "super-secret" not in record_text
    assert "super-secret" not in gates_text


@pytest.mark.parametrize(
    ("parser_type", "script", "expected_file"),
    [
        (
            "rdjson",
            "import json; print(json.dumps({'diagnostics':[{'message':'rd','severity':'ERROR','location':{'path':'src/app.py','range':{'start':{'line':1,'column':2}}},'code':{'value':'R1'}}]}))",
            "src/app.py",
        ),
        (
            "sarif",
            "import json; print(json.dumps({'runs':[{'results':[{'ruleId':'S1','level':'warning','message':{'text':'sarif'},'locations':[{'physicalLocation':{'artifactLocation':{'uri':'src/app.py'},'region':{'startLine':1}}}]}]}]}))",
            "src/app.py",
        ),
        (
            "checkstyle",
            "print('<checkstyle><file name=\"src/app.py\"><error line=\"1\" severity=\"error\" message=\"cs\" source=\"C1\" /></file></checkstyle>')",
            "src/app.py",
        ),
    ],
)
def test_external_diagnostic_formats(capsys, tmp_path: Path, parser_type: str, script: str, expected_file: str) -> None:
    repo = init_repo(tmp_path)
    config = write_config(repo, [
        {
            "id": parser_type,
            "argv": [sys.executable, "-c", script],
            "scope": "all",
            "final_always": True,
            "parser": {"type": parser_type},
        }
    ])
    snap = snapshot(capsys, repo, config, tmp_path / "cache", "--final-pass")

    code = main(["gate", "--repo", str(repo), "--config", str(config), "--snapshot", snap["snapshot_path"]])
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert code in {0, 1}
    assert result["diagnostics"][0]["file"] == expected_file


def test_new_cli_commands_and_repo_map(capsys, tmp_path: Path) -> None:
    repo = init_repo(tmp_path)

    code = main(["init", "--repo", str(repo), "--output", "rfl.gates.json"])
    captured = capsys.readouterr()
    assert code == 0, captured.err
    config_path = repo / "rfl.gates.json"
    assert config_path.exists()

    code = main(["list-adapters", "--repo", str(repo)])
    captured = capsys.readouterr()
    assert code == 0
    assert "generic" in captured.out

    code = main(["validate-config", "--repo", str(repo), "--config", str(config_path)])
    captured = capsys.readouterr()
    assert code == 0, captured.err
    assert json.loads(captured.out)["valid"] is True

    code = main(["validate-schema", "--schema", "gate-config", "--file", str(config_path), "--repo", str(repo)])
    captured = capsys.readouterr()
    assert code == 0, captured.err

    code = main(["doctor", "--repo", str(repo), "--config", str(config_path)])
    captured = capsys.readouterr()
    assert code == 0, captured.out

    (repo / "src" / "new.py").write_text("def new_feature():\n    return 1\n", encoding="utf-8")
    snap = snapshot(capsys, repo, config_path, tmp_path / "cache", "--include-repo-map")
    assert snap["repo_map"]["files"][0]["symbols"][0]["name"] == "new_feature"

    code = main(["inspect", "--snapshot", snap["snapshot_path"], "--format", "json"])
    captured = capsys.readouterr()
    assert code == 0
    assert json.loads(captured.out)["repo_map_files"] == 1


def test_local_override_provenance_and_disable_switch(capsys, tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    config_path = write_config(repo, [
        {
            "id": "base",
            "argv": [sys.executable, "-c", "print('base')"],
            "scope": "all",
            "final_always": True,
            "parser": {"type": "exit-code"},
        }
    ])
    local_override = repo / ".review-fix-loop.local.json"
    local_override.write_text(json.dumps({
        "gates": [
            {
                "id": "local",
                "argv": [sys.executable, "-c", "print('local')"],
                "scope": "all",
                "final_always": True,
                "parser": {"type": "exit-code"},
            }
        ]
    }), encoding="utf-8")

    code = main(["validate-config", "--repo", str(repo), "--config", str(config_path)])
    captured = capsys.readouterr()
    default_summary = json.loads(captured.out)

    assert code == 0
    assert default_summary["gates"] == ["local"]
    assert default_summary["local_override_applied"] is True
    assert default_summary["local_override_available"] is True
    assert default_summary["local_override_disabled"] is False
    assert default_summary["local_override_path"] == str(local_override.resolve())
    assert default_summary["config_sources"] == [str(config_path.resolve()), str(local_override.resolve())]

    code = main([
        "validate-config",
        "--repo",
        str(repo),
        "--config",
        str(config_path),
        "--no-local-override",
    ])
    captured = capsys.readouterr()
    disabled_summary = json.loads(captured.out)

    assert code == 0
    assert disabled_summary["gates"] == ["base"]
    assert disabled_summary["local_override_applied"] is False
    assert disabled_summary["local_override_available"] is True
    assert disabled_summary["local_override_disabled"] is True
    assert disabled_summary["config_sources"] == [str(config_path.resolve())]

    snap = snapshot(capsys, repo, config_path, tmp_path / "cache", "--final-pass")
    assert snap["planned_gates"] == ["local"]
    assert snap["local_override_applied"] is True

    code = main([
        "snapshot",
        "--repo",
        str(repo),
        "--config",
        str(config_path),
        "--mode",
        "normal_loop",
        "--pass",
        "1",
        "--final-pass",
        "--no-local-override",
    ])
    captured = capsys.readouterr()
    disabled_snap = json.loads(captured.out)

    assert code == 0
    assert disabled_snap["planned_gates"] == ["base"]
    assert disabled_snap["local_override_applied"] is False
    assert disabled_snap["local_override_disabled"] is True


def test_locale_env_localizes_common_workflow_error(capsys, monkeypatch, tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    config = write_config(repo, [])
    monkeypatch.setenv("REVIEW_FIX_LOOP_LOCALE", "zh-CN")

    code = main([
        "snapshot",
        "--repo",
        str(repo),
        "--config",
        str(config),
        "--mode",
        "normal_loop",
        "--pass",
        "2",
    ])
    captured = capsys.readouterr()

    assert code == 1
    assert "--pass 大于 1 时必须提供 --previous-run-record" in captured.err
