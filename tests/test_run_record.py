from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from review_fix_loop.cli import main
from review_fix_loop.errors import WorkflowError
from review_fix_loop.run_record import build_run_record, update_run_record_after_gates, write_run_outputs


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def test_snapshot_writes_run_record_without_source_or_diff_text(capsys, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test User")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("secret_token = 'do-not-store'\n", encoding="utf-8")
    config = {
        "version": 1,
        "rule_files": [],
        "modes": {"normal_loop": {"scope": ["untracked"]}, "large_merge": {"baseline": "main", "scope": ["merge_base_to_head"]}},
        "slices": [{"id": "source", "paths": ["src/**"], "risk": "medium"}],
        "gates": [],
    }
    config_path = repo / "gates.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

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
        "--write-run-record",
        "--cache-dir",
        str(tmp_path / "cache"),
    ])
    captured = capsys.readouterr()
    assert code == 0, captured.err
    snapshot = json.loads(captured.out)
    record_text = Path(snapshot["run_record_path"]).read_text(encoding="utf-8")
    run_root = Path(snapshot["run_record_path"]).parent
    summary_path = run_root / "summary.md"

    assert "do-not-store" not in record_text
    assert "secret_token" not in record_text
    assert snapshot["run_record_path"].endswith("run-record.json")
    assert Path(snapshot["snapshot_path"]).exists()
    assert summary_path.exists()
    assert "Local override applied: False" in summary_path.read_text(encoding="utf-8")
    assert not summary_path.with_name(summary_path.name + ".tmp").exists()


def test_skill_snapshot_wrapper_runs_from_source_tree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    config = {
        "version": 1,
        "rule_files": [],
        "modes": {"normal_loop": {"scope": ["untracked"]}, "large_merge": {"baseline": "main", "scope": ["merge_base_to_head"]}},
        "slices": [{"id": "source", "paths": ["src/**"], "risk": "medium"}],
        "gates": [],
    }
    config_path = repo / "gates.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("print('wrapper')\n", encoding="utf-8")
    wrapper = Path(__file__).resolve().parents[1] / "skills" / "review-fix-loop-core" / "scripts" / "snapshot.py"

    result = subprocess.run(
        [
            sys.executable,
            str(wrapper),
            "--repo",
            str(repo),
            "--config",
            str(config_path),
            "--mode",
            "normal_loop",
            "--pass",
            "1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    snapshot = json.loads(result.stdout)
    assert snapshot["must_reload"] == ["gates.json", "src/app.py"]


def test_gate_run_record_update_rejects_path_outside_snapshot_dir(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    run_root.mkdir()
    snapshot_path = run_root / "snapshot.json"
    snapshot_path.write_text("{}", encoding="utf-8")
    outside_record = tmp_path / "other" / "run-record.json"
    snapshot = {
        "run_record_path": str(outside_record),
    }

    with pytest.raises(WorkflowError, match="run_record_path must stay under the snapshot directory"):
        update_run_record_after_gates(snapshot, snapshot_path, [], [], 0)


def test_gate_run_record_update_rejects_non_string_record_path(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    run_root.mkdir()
    snapshot_path = run_root / "snapshot.json"
    snapshot_path.write_text("{}", encoding="utf-8")
    snapshot = {
        "run_record_path": ["run-record.json"],
    }

    with pytest.raises(WorkflowError, match="run_record_path must be a string"):
        update_run_record_after_gates(snapshot, snapshot_path, [], [], 0)


def test_gate_run_record_update_returns_false_when_record_missing(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    run_root.mkdir()
    snapshot_path = run_root / "snapshot.json"
    snapshot_path.write_text("{}", encoding="utf-8")

    updated = update_run_record_after_gates({}, snapshot_path, [], [], 0)

    assert updated is False
    assert not (run_root / "run-record.json").exists()


def test_write_run_outputs_rejects_non_string_summary_list(tmp_path: Path) -> None:
    snapshot = {
        "mode": "normal_loop",
        "pass": 1,
        "snapshot_id": "sha256:test",
        "config_sources": ["gates.json"],
        "must_reload": ["src/app.py", 1],
        "planned_gates": [],
    }

    with pytest.raises(WorkflowError, match="must_reload must be a list of strings"):
        write_run_outputs(tmp_path / "run", snapshot, {"schema": 1}, {})

    assert not (tmp_path / "run" / "snapshot.json").exists()


def test_build_run_record_rejects_non_string_slice_list() -> None:
    snapshot = {
        "mode": "normal_loop",
        "pass": 2,
        "snapshot_id": "sha256:test",
        "config_hash": "sha256:config",
        "rule_hashes": {},
        "scope_hashes": {},
        "slice_hashes": {},
        "reloaded_slices": ["source"],
        "reused_slices": ["tests", 1],
    }

    with pytest.raises(WorkflowError, match="reused_slices must be a list of strings"):
        build_run_record(snapshot, "run-id")
