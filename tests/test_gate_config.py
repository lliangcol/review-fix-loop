from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from review_fix_loop.cli import main
from review_fix_loop.config import deep_merge, load_effective_config
from review_fix_loop.diagnostics import parse_json_diagnostics
from review_fix_loop.domain.types import GateRequest, SchemaValidationRequest
from review_fix_loop.errors import WorkflowError
from review_fix_loop.gates import gate_trust_metadata, run_external_gate
from review_fix_loop.schema_validation import minimal_validate
from review_fix_loop.services.gate_service import execute_gate_from_request, execute_gate_request, execute_planned_gates
from review_fix_loop.services.schema_service import validate_schema_from_request
from review_fix_loop.slices import UNCATEGORIZED, assign_slice, attach_slices, paths_by_slice


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


def packaged_adapter_config_paths(root: Path) -> list[Path]:
    paths = [
        *root.glob("src/review_fix_loop/templates/*.gates.json"),
        *root.glob("adapters/*/gates.json"),
        *root.glob("examples/adapters/*/gates.json"),
    ]
    return sorted(paths, key=lambda path: path.as_posix())


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


def test_gate_service_rejects_config_hash_mismatch_before_execution(capsys, tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    marker = repo / "gate-ran.txt"
    script = (
        "from pathlib import Path; "
        f"Path({json.dumps(str(marker))}).write_text('ran', encoding='utf-8')"
    )
    config = write_config(repo, [
        {
            "id": "final",
            "argv": [sys.executable, "-c", script],
            "scope": "all",
            "final_always": True,
            "parser": {"type": "exit-code"},
        }
    ])
    snap = snapshot(capsys, repo, config, tmp_path / "cache")
    changed = json.loads(config.read_text(encoding="utf-8"))
    changed["slices"].append({"id": "docs", "paths": ["docs/**"], "risk": "low"})
    config.write_text(json.dumps(changed), encoding="utf-8")

    with pytest.raises(WorkflowError, match="effective config hash differs"):
        execute_gate_request(repo, config, snap["snapshot_path"], [])

    assert not marker.exists()


def test_gate_service_accepts_typed_request_boundary(capsys, tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    config = write_config(repo, [
        {
            "id": "trusted",
            "argv": [sys.executable, "-c", "print('typed gate request')"],
            "scope": "all",
            "final_always": True,
            "trusted": True,
            "allow_in_ci": True,
            "parser": {"type": "exit-code"},
        }
    ])
    snap = snapshot(capsys, repo, config, tmp_path / "cache")

    result = execute_gate_from_request(GateRequest(
        repo=repo,
        config=config,
        snapshot=snap["snapshot_path"],
        ci_mode=True,
    ))
    record = json.loads(Path(snap["run_record_path"]).read_text(encoding="utf-8"))

    assert result.exit_status == 0
    assert result.gates[0]["id"] == "trusted"
    assert result.gates[0]["status"] == "passed"
    assert result.diagnostics == []
    assert record["gates"][0]["id"] == "trusted"
    assert record["stop_decision"] == "stop"


def test_gate_service_planned_wrapper_accepts_json_boundaries(tmp_path: Path) -> None:
    gates, diagnostics, exit_status = execute_planned_gates(
        tmp_path,
        {"gates": []},
        {"planned_gates": []},
        tmp_path / "snapshot.json",
        ci_mode=True,
    )

    assert gates == []
    assert diagnostics == []
    assert exit_status == 0


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

    diagnostic_path = tmp_path / "diagnostic.json"
    diagnostic_path.write_text(json.dumps(result["diagnostics"][0]), encoding="utf-8")
    code = main(["validate-schema", "--schema", "diagnostic", "--file", str(diagnostic_path), "--repo", str(repo)])
    captured = capsys.readouterr()
    assert code == 0, captured.err


def test_diagnostic_schema_rejects_invalid_severity(capsys, tmp_path: Path) -> None:
    diagnostic_path = tmp_path / "invalid-diagnostic.json"
    diagnostic_path.write_text(
        json.dumps({
            "tool": "example",
            "severity": "fatal",
            "message": "bad severity",
            "scope": "all",
            "blocking": True,
        }),
        encoding="utf-8",
    )

    code = main(["validate-schema", "--schema", "diagnostic", "--file", str(diagnostic_path)])
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert code == 1
    assert result["valid"] is False
    assert any("severity" in error and "fatal" in error for error in result["errors"]) or any(
        "field severity must be one of" in error for error in result["errors"]
    )


def test_schema_service_accepts_typed_request_boundary(tmp_path: Path) -> None:
    diagnostic_path = tmp_path / "diagnostic.json"
    diagnostic_path.write_text(
        json.dumps({
            "tool": "typed-schema",
            "severity": "warning",
            "message": "typed request",
            "scope": "all",
            "blocking": False,
        }),
        encoding="utf-8",
    )

    result = validate_schema_from_request(SchemaValidationRequest(
        schema_name="diagnostic",
        file=diagnostic_path,
    ))
    output = result.to_json_output()

    assert result.valid is True
    assert output["valid"] is True
    assert output["schema"] == "diagnostic"
    assert output["file"] == str(diagnostic_path.resolve())


def test_schema_service_rejects_non_object_artifact(tmp_path: Path) -> None:
    diagnostic_path = tmp_path / "diagnostic.json"
    diagnostic_path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    with pytest.raises(WorkflowError, match="expected JSON object"):
        validate_schema_from_request(SchemaValidationRequest(
            schema_name="diagnostic",
            file=diagnostic_path,
        ))


def test_minimal_schema_validator_uses_typed_schema_boundaries(tmp_path: Path) -> None:
    artifact_path = tmp_path / "artifact.json"
    errors = minimal_validate(
        {"schema": 2, "state": "bad"},
        {
            "required": ["schema", 7],
            "properties": {
                "schema": {"const": 1},
                "state": {"enum": ["ok"]},
                "ignored": "not-an-object",
            },
        },
        artifact_path,
    )

    assert errors == [
        f"{artifact_path}: field schema must be 1",
        f"{artifact_path}: field state must be one of ['ok']",
    ]


def test_config_deep_merge_accepts_json_boundary_without_mutating_inputs() -> None:
    base = {
        "modes": {"normal_loop": {"scope": ["staged"]}},
        "gates": [{"id": "base"}],
    }
    override = {
        "modes": {"normal_loop": {"scope": ["unstaged"], "requires_final_pass": True}},
        "extra": {"enabled": True},
    }

    merged = deep_merge(base, override)

    assert merged == {
        "modes": {"normal_loop": {"scope": ["unstaged"], "requires_final_pass": True}},
        "gates": [{"id": "base"}],
        "extra": {"enabled": True},
    }
    assert base == {
        "modes": {"normal_loop": {"scope": ["staged"]}},
        "gates": [{"id": "base"}],
    }


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


def test_json_diagnostics_parser_accepts_json_boundary_shapes() -> None:
    diagnostics = parse_json_diagnostics(
        json.dumps({
            "diagnostics": [
                {
                    "tool": "custom",
                    "severity": "note",
                    "line": "12",
                    "column": "3",
                    "message": "typed boundary",
                    "blocking": False,
                    "slice": "source",
                }
            ]
        }),
        "json-gate",
        "all",
        True,
    )

    assert diagnostics == [
        {
            "tool": "custom",
            "severity": "info",
            "rule": None,
            "file": None,
            "line": 12,
            "column": 3,
            "message": "typed boundary",
            "scope": "all",
            "slice": "source",
            "blocking": False,
        }
    ]


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


def test_external_gate_capture_uses_typed_result(tmp_path: Path) -> None:
    output = run_external_gate(tmp_path, [sys.executable, "-c", "print('typed')"], 30)

    assert output.exit_code == 0
    assert output.stdout.splitlines() == ["typed"]
    assert output.stderr == ""
    assert output.stdout_bytes == len(output.stdout.encode("utf-8"))
    assert output.stderr_bytes == 0
    assert output.stdout_truncated is False
    assert output.stderr_truncated is False


def test_gate_trust_metadata_accepts_json_boundary_shapes() -> None:
    builtin = gate_trust_metadata(
        {"id": "builtin", "writes_worktree": True},
        ["__builtin__:policy"],
        allow_untrusted_gates=False,
        ci_mode=True,
    )
    external = gate_trust_metadata(
        {"id": "external", "trusted": True, "allow_in_ci": False},
        [sys.executable, "-c", "print('external')"],
        allow_untrusted_gates=False,
        ci_mode=True,
    )

    assert builtin["trusted"] is True
    assert builtin["allow_in_ci"] is True
    assert builtin["trust_reason"] == "builtin gate"
    assert "ci_refused" not in builtin
    assert external["trusted"] is True
    assert external["allow_in_ci"] is False
    assert external["ci_refused"] is True


def test_ci_mode_refuses_untrusted_external_gate(capsys, tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    config = write_config(repo, [
        {
            "id": "untrusted",
            "argv": [sys.executable, "-c", "print('should not run')"],
            "scope": "all",
            "final_always": True,
            "parser": {"type": "exit-code"},
        }
    ])
    snap = snapshot(capsys, repo, config, tmp_path / "cache")

    code = main([
        "gate",
        "--repo",
        str(repo),
        "--config",
        str(config),
        "--snapshot",
        snap["snapshot_path"],
        "--ci-mode",
    ])
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert code == 1
    assert result["gates"][0]["status"] == "failed"
    assert result["gates"][0]["trusted"] is False
    assert result["diagnostics"][0]["rule"] == "untrusted-gate-refused"
    assert "should not run" not in result["gates"][0]["stdout_summary"]


def test_trusted_external_gate_runs_in_ci_and_persists_metadata(capsys, tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    config = write_config(repo, [
        {
            "id": "trusted",
            "argv": [sys.executable, "-c", "print('ok')"],
            "scope": "all",
            "final_always": True,
            "trusted": True,
            "allow_in_ci": True,
            "writes_worktree": False,
            "requires_network": False,
            "trust_reason": "test fixture command",
            "parser": {"type": "exit-code"},
        }
    ])
    snap = snapshot(capsys, repo, config, tmp_path / "cache")

    code = main([
        "gate",
        "--repo",
        str(repo),
        "--config",
        str(config),
        "--snapshot",
        snap["snapshot_path"],
        "--ci-mode",
    ])
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    record = json.loads(Path(snap["run_record_path"]).read_text(encoding="utf-8"))

    assert code == 0
    assert result["gates"][0]["trusted"] is True
    assert result["gates"][0]["allow_in_ci"] is True
    assert result["gates"][0]["trust_reason"] == "test fixture command"
    assert record["gates"][0]["trusted"] is True
    assert record["gates"][0]["allow_in_ci"] is True
    assert record["gates"][0]["trust_reason"] == "test fixture command"

    code = main([
        "validate-schema",
        "--schema",
        "run-record",
        "--file",
        snap["run_record_path"],
        "--repo",
        str(repo),
    ])
    captured = capsys.readouterr()
    assert code == 0, captured.err


def test_parallel_safe_gates_keep_planned_order(capsys, tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    config = write_config(repo, [
        {
            "id": "slow",
            "argv": [sys.executable, "-c", "import time; time.sleep(0.35); print('slow')"],
            "scope": "all",
            "final_always": True,
            "trusted": True,
            "allow_in_ci": True,
            "parallel_safe": True,
            "parser": {"type": "exit-code"},
        },
        {
            "id": "fast",
            "argv": [sys.executable, "-c", "print('fast')"],
            "scope": "all",
            "final_always": True,
            "trusted": True,
            "allow_in_ci": True,
            "parallel_safe": True,
            "parser": {"type": "exit-code"},
        },
    ])
    snap = snapshot(capsys, repo, config, tmp_path / "cache")

    start = time.monotonic()
    code = main(["gate", "--repo", str(repo), "--config", str(config), "--snapshot", snap["snapshot_path"]])
    elapsed = time.monotonic() - start
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert code == 0
    assert [gate["id"] for gate in result["gates"]] == ["slow", "fast"]
    assert elapsed < 0.65


def test_gate_depends_on_waits_for_dependency(capsys, tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    config = write_config(repo, [
        {
            "id": "first",
            "argv": [sys.executable, "-c", "print('first')"],
            "scope": "all",
            "final_always": True,
            "trusted": True,
            "allow_in_ci": True,
            "parallel_safe": True,
            "parser": {"type": "exit-code"},
        },
        {
            "id": "second",
            "argv": [sys.executable, "-c", "print('second')"],
            "scope": "all",
            "final_always": True,
            "trusted": True,
            "allow_in_ci": True,
            "parallel_safe": True,
            "depends_on": ["first"],
            "parser": {"type": "exit-code"},
        },
    ])
    snap = snapshot(capsys, repo, config, tmp_path / "cache")

    code = main(["gate", "--repo", str(repo), "--config", str(config), "--snapshot", snap["snapshot_path"]])
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert code == 0
    assert [gate["id"] for gate in result["gates"]] == ["first", "second"]


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
    config, _, _, _ = load_effective_config(repo, repo / "adapters" / "generic" / "gates.json")
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


def test_slice_helpers_assign_uncategorized_and_dedupe_paths() -> None:
    slices = [{"id": "source", "paths": ["src/**"], "risk": "medium"}]
    entries = {
        "unstaged": [{"path": "src/app.py"}, {"path": "docs/readme.md"}],
        "untracked": [{"path": "src/app.py"}],
    }

    attach_slices(entries, slices)

    assert assign_slice("./src/app.py", slices) == "source"
    assert entries["unstaged"][0]["slice"] == "source"
    assert entries["unstaged"][1]["slice"] == UNCATEGORIZED
    assert paths_by_slice(entries) == {
        "source": ["src/app.py"],
        UNCATEGORIZED: ["docs/readme.md"],
    }


def test_generic_adapter_matches_packaged_template() -> None:
    root = Path(__file__).resolve().parents[1]
    adapter_config = json.loads((root / "adapters" / "generic" / "gates.json").read_text(encoding="utf-8"))
    template_config = json.loads(
        (root / "src" / "review_fix_loop" / "templates" / "generic.gates.json").read_text(encoding="utf-8")
    )

    assert template_config == adapter_config


def test_packaged_adapter_configs_validate(capsys) -> None:
    root = Path(__file__).resolve().parents[1]
    config_paths = packaged_adapter_config_paths(root)

    assert [path.as_posix() for path in config_paths] == [
        (root / "adapters" / "generic" / "gates.json").as_posix(),
        (root / "adapters" / "project-template" / "gates.json").as_posix(),
        (root / "examples" / "adapters" / "frontend-basic" / "gates.json").as_posix(),
        (root / "examples" / "adapters" / "monorepo-basic" / "gates.json").as_posix(),
        (root / "examples" / "adapters" / "python-basic" / "gates.json").as_posix(),
        (root / "src" / "review_fix_loop" / "templates" / "generic.gates.json").as_posix(),
    ]

    for config_path in config_paths:
        code = main([
            "validate-schema",
            "--schema",
            "gate-config",
            "--file",
            str(config_path),
            "--repo",
            str(root),
        ])
        captured = capsys.readouterr()
        assert code == 0, f"{config_path.relative_to(root)} schema failed: {captured.err}"

        code = main([
            "validate-config",
            "--repo",
            str(root),
            "--config",
            str(config_path),
            "--no-local-override",
        ])
        captured = capsys.readouterr()
        assert code == 0, f"{config_path.relative_to(root)} config failed: {captured.err}"
        assert json.loads(captured.out)["valid"] is True


def test_validate_config_rejects_duplicate_json_keys(capsys, tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    config_path = repo / "duplicate.gates.json"
    config_path.write_text(
        """{
  "version": 1,
  "version": 1,
  "modes": {
    "normal_loop": { "scope": ["staged"] }
  },
  "slices": [
    { "id": "source", "paths": ["src/**"] }
  ],
  "gates": []
}
""",
        encoding="utf-8",
    )

    code = main([
        "validate-config",
        "--repo",
        str(repo),
        "--config",
        str(config_path),
        "--no-local-override",
    ])
    captured = capsys.readouterr()

    assert code == 1
    assert "duplicate JSON key: version" in captured.err


def test_validate_schema_rejects_duplicate_json_keys(capsys, tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    config_path = repo / "duplicate.gates.json"
    config_path.write_text(
        """{
  "version": 1,
  "modes": {
    "normal_loop": { "scope": ["staged"], "scope": ["unstaged"] }
  },
  "slices": [
    { "id": "source", "paths": ["src/**"] }
  ],
  "gates": []
}
""",
        encoding="utf-8",
    )

    code = main([
        "validate-schema",
        "--schema",
        "gate-config",
        "--file",
        str(config_path),
        "--repo",
        str(repo),
    ])
    captured = capsys.readouterr()

    assert code == 1
    assert "duplicate JSON key: scope" in captured.err
