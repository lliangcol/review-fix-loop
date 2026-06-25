from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from review_fix_loop.cli import main
from review_fix_loop.domain.types import SnapshotRequest
from review_fix_loop.errors import WorkflowError
from review_fix_loop.services.snapshot_service import (
    create_snapshot_from_request,
    create_snapshot_request,
    previous_slice_has_fixes,
    previous_slice_has_unresolved_diagnostics,
)
from review_fix_loop.utils import DEFAULT_FILE_HASH_LIMIT_BYTES


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


def write_config(repo: Path, extra_gates: list[dict] | None = None) -> Path:
    config = {
        "version": 1,
        "rule_files": [],
        "modes": {
            "normal_loop": {
                "scope": ["staged", "unstaged", "untracked"],
                "require_fresh_snapshot": True,
            },
            "large_merge": {
                "baseline": "main",
                "scope": ["merge_base_to_head", "staged", "unstaged", "untracked"],
            },
        },
        "slices": [
            {"id": "source", "paths": ["src/**"], "risk": "medium"},
            {"id": "tests", "paths": ["tests/**"], "risk": "low"},
            {"id": "assets", "paths": ["assets/**"], "risk": "low"},
        ],
        "gates": extra_gates or [],
    }
    path = repo / "gates.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def run_snapshot(capsys, repo: Path, config: Path, *extra: str) -> tuple[int, dict]:
    code = main(["snapshot", "--repo", str(repo), "--config", str(config), *extra])
    captured = capsys.readouterr()
    data = json.loads(captured.out) if captured.out.strip() else {}
    return code, data


def test_pass_2_after_fix_invalidates_changed_slice(capsys, tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    config = write_config(repo)
    (repo / "src" / "app.py").write_text("print('pass1')\n", encoding="utf-8")
    code, first = run_snapshot(
        capsys,
        repo,
        config,
        "--mode",
        "normal_loop",
        "--pass",
        "1",
        "--write-run-record",
        "--cache-dir",
        str(tmp_path / "cache"),
    )
    assert code == 0

    (repo / "src" / "app.py").write_text("print('pass2')\n", encoding="utf-8")
    code, second = run_snapshot(
        capsys,
        repo,
        config,
        "--mode",
        "normal_loop",
        "--pass",
        "2",
        "--previous-run-record",
        first["run_record_path"],
        "--write-run-record",
        "--cache-dir",
        str(tmp_path / "cache"),
    )

    assert code == 0
    assert second["previous_snapshot_id"] == first["snapshot_id"]
    assert second["must_reload"] == ["src/app.py"]
    assert "source" in second["reuse_forbidden_slices"]
    assert "slice hash changed" in second["reuse_forbidden_slices"]["source"]


def test_pass_2_reuses_unchanged_slice_when_another_slice_changed(capsys, tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    config = write_config(repo)
    git(repo, "add", "gates.json")
    git(repo, "commit", "-m", "config")
    (repo / "src" / "app.py").write_text("print('pass1')\n", encoding="utf-8")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_app.py").write_text("def test_app():\n    pass\n", encoding="utf-8")
    code, first = run_snapshot(
        capsys,
        repo,
        config,
        "--mode",
        "normal_loop",
        "--pass",
        "1",
        "--write-run-record",
        "--cache-dir",
        str(tmp_path / "cache"),
    )
    assert code == 0
    assert first["reloaded_slices"] == ["source", "tests"]

    (repo / "src" / "app.py").write_text("print('pass2')\n", encoding="utf-8")
    code, second = run_snapshot(
        capsys,
        repo,
        config,
        "--mode",
        "normal_loop",
        "--pass",
        "2",
        "--previous-run-record",
        first["run_record_path"],
        "--write-run-record",
        "--cache-dir",
        str(tmp_path / "cache"),
    )

    assert code == 0
    assert second["previous_snapshot_id"] == first["snapshot_id"]
    assert second["must_reload"] == ["src/app.py"]
    assert second["reloaded_slices"] == ["source"]
    assert second["reused_slices"] == ["tests"]
    assert "source" in second["reuse_forbidden_slices"]
    assert "tests" not in second["reuse_forbidden_slices"]


def test_pass_2_previous_fix_metadata_invalidates_unchanged_slice(capsys, tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    config = write_config(repo)
    git(repo, "add", "gates.json")
    git(repo, "commit", "-m", "config")
    (repo / "src" / "app.py").write_text("print('needs review')\n", encoding="utf-8")
    code, first = run_snapshot(
        capsys,
        repo,
        config,
        "--mode",
        "normal_loop",
        "--pass",
        "1",
        "--write-run-record",
        "--cache-dir",
        str(tmp_path / "cache"),
    )
    assert code == 0

    previous_record_path = Path(first["run_record_path"])
    previous_record = json.loads(previous_record_path.read_text(encoding="utf-8"))
    previous_record["fixes"] = [{"path": "src/app.py", "slice": "source"}]
    previous_record_path.write_text(json.dumps(previous_record), encoding="utf-8")

    code, second = run_snapshot(
        capsys,
        repo,
        config,
        "--mode",
        "normal_loop",
        "--pass",
        "2",
        "--previous-run-record",
        str(previous_record_path),
        "--write-run-record",
        "--cache-dir",
        str(tmp_path / "cache"),
    )

    assert code == 0
    assert second["previous_snapshot_id"] == first["snapshot_id"]
    assert second["slice_hashes"] == first["slice_hashes"]
    assert second["must_reload"] == ["src/app.py"]
    assert second["reloaded_slices"] == ["source"]
    assert second["reused_slices"] == []
    reasons = second["reuse_forbidden_slices"]["source"]
    assert reasons == ["previous pass fixed files in slice"]


def test_pass_2_without_previous_run_record_exits_nonzero(capsys, tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    config = write_config(repo)
    (repo / "src" / "app.py").write_text("print('dirty')\n", encoding="utf-8")

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
    assert "--previous-run-record" in captured.err


def test_snapshot_service_requires_previous_run_record_for_pass_after_first(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    config = write_config(repo)
    (repo / "src" / "app.py").write_text("print('dirty')\n", encoding="utf-8")

    with pytest.raises(WorkflowError, match="--previous-run-record"):
        create_snapshot_request(repo, config, "normal_loop", 2, [])


def test_snapshot_service_accepts_typed_request_boundary(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    config = write_config(repo)
    (repo / "src" / "app.py").write_text("print('typed request')\n", encoding="utf-8")

    result = create_snapshot_from_request(SnapshotRequest(
        repo=repo,
        config=config,
        mode="normal_loop",
        pass_number=1,
        write_run_record=True,
        cache_dir=str(tmp_path / "cache"),
        include_repo_map=True,
        repo_map_limit=5,
    ))
    snapshot = result.to_json_output()

    assert snapshot["mode"] == "normal_loop"
    assert snapshot["pass"] == 1
    assert snapshot["must_reload"] == ["gates.json", "src/app.py"]
    assert "repo_map" in snapshot
    assert Path(snapshot["run_record_path"]).exists()


def test_snapshot_service_previous_record_helpers_use_json_boundaries() -> None:
    previous = {
        "fixes": [{"slice": "source"}, {"path": "tests/test_app.py"}],
        "diagnostics": [
            {"slice": "source"},
            {"slice": "tests"},
        ],
        "stop_decision": "needs_fixes",
    }

    assert previous_slice_has_fixes(previous, "source") is True
    assert previous_slice_has_fixes(previous, "tests") is False
    assert previous_slice_has_unresolved_diagnostics(previous, "tests") is True
    assert previous_slice_has_unresolved_diagnostics(previous, "docs") is False

    stopped_previous = {**previous, "stop_decision": "stop"}
    assert previous_slice_has_unresolved_diagnostics(stopped_previous, "source") is False


def test_pass_2_missing_previous_run_record_exits_nonzero_without_traceback(capsys, tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    config = write_config(repo)
    (repo / "src" / "app.py").write_text("print('dirty')\n", encoding="utf-8")

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
        "--previous-run-record",
        str(tmp_path / "missing-run-record.json"),
    ])
    captured = capsys.readouterr()

    assert code == 1
    assert "JSON file not found" in captured.err
    assert "Traceback" not in captured.err


def test_large_file_tail_change_invalidates_slice(capsys, tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    config = write_config(repo)
    (repo / "assets").mkdir()
    large_file = repo / "assets" / "large.txt"
    large_file.write_bytes((b"a" * DEFAULT_FILE_HASH_LIMIT_BYTES) + b"1\n")
    code, first = run_snapshot(
        capsys,
        repo,
        config,
        "--mode",
        "normal_loop",
        "--pass",
        "1",
        "--write-run-record",
        "--cache-dir",
        str(tmp_path / "cache"),
    )
    assert code == 0

    large_file.write_bytes((b"a" * DEFAULT_FILE_HASH_LIMIT_BYTES) + b"2\n")
    code, second = run_snapshot(
        capsys,
        repo,
        config,
        "--mode",
        "normal_loop",
        "--pass",
        "2",
        "--previous-run-record",
        first["run_record_path"],
        "--write-run-record",
        "--cache-dir",
        str(tmp_path / "cache"),
    )

    assert code == 0
    assert second["must_reload"] == ["assets/large.txt"]
    assert "slice hash changed" in second["reuse_forbidden_slices"]["assets"]


def test_untracked_and_same_path_staged_unstaged_are_separate(capsys, tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    config = write_config(repo)
    (repo / "src" / "app.py").write_text("print('staged')\n", encoding="utf-8")
    git(repo, "add", "src/app.py")
    (repo / "src" / "app.py").write_text("print('unstaged')\n", encoding="utf-8")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_app.py").write_text("def test_app():\n    pass\n", encoding="utf-8")

    code, snapshot = run_snapshot(capsys, repo, config, "--mode", "normal_loop", "--pass", "1")

    assert code == 0
    assert snapshot["entries"]["staged"][0]["path"] == "src/app.py"
    assert snapshot["entries"]["unstaged"][0]["path"] == "src/app.py"
    untracked_paths = {entry["path"] for entry in snapshot["entries"]["untracked"]}
    assert "tests/test_app.py" in untracked_paths
    assert "tests/test_app.py" in snapshot["must_reload"]


def test_rename_preserves_old_and_new_paths(capsys, tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    config = write_config(repo)
    git(repo, "mv", "src/app.py", "src/main.py")

    code, snapshot = run_snapshot(capsys, repo, config, "--mode", "normal_loop", "--pass", "1")

    assert code == 0
    entry = snapshot["entries"]["staged"][0]
    assert entry["status_kind"] == "R"
    assert entry["old_path"] == "src/app.py"
    assert entry["path"] == "src/main.py"


def test_binary_file_is_marked_without_content(capsys, tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    config = write_config(repo)
    (repo / "assets").mkdir()
    (repo / "assets" / "example.bin").write_bytes(b"abc\0def")

    code, snapshot = run_snapshot(capsys, repo, config, "--mode", "normal_loop", "--pass", "1")

    assert code == 0
    entry = snapshot["entries"]["untracked"][0]
    assert entry["binary"] is True
    assert entry["content_hash"].startswith("sha256:")
    assert "abc" not in json.dumps(snapshot)


def test_staged_binary_marker_uses_staged_blob_not_worktree(capsys, tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    config = write_config(repo)
    (repo / "src" / "app.py").write_text("print('staged text')\n", encoding="utf-8")
    git(repo, "add", "src/app.py")
    (repo / "src" / "app.py").write_bytes(b"binary\0worktree")

    code, snapshot = run_snapshot(capsys, repo, config, "--mode", "normal_loop", "--pass", "1")

    assert code == 0
    staged = snapshot["entries"]["staged"][0]
    unstaged = snapshot["entries"]["unstaged"][0]
    assert staged["binary"] is False
    assert unstaged["binary"] is True


def test_large_merge_separates_branch_diff_and_dirty_worktree(capsys, tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    config = write_config(repo)
    git(repo, "checkout", "-b", "feature")
    (repo / "src" / "feature.py").write_text("print('feature')\n", encoding="utf-8")
    git(repo, "add", "src/feature.py")
    git(repo, "commit", "-m", "feature")
    (repo / "src" / "app.py").write_text("print('dirty')\n", encoding="utf-8")

    code, snapshot = run_snapshot(capsys, repo, config, "--mode", "large_merge", "--baseline", "main", "--pass", "1")

    assert code == 0
    assert [entry["path"] for entry in snapshot["entries"]["merge_base_to_head"]] == ["src/feature.py"]
    assert [entry["path"] for entry in snapshot["entries"]["unstaged"]] == ["src/app.py"]
    assert snapshot["baseline"] == "main"
    assert snapshot["merge_base"]


def test_large_merge_marks_binary_branch_blob(capsys, tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    config = write_config(repo)
    git(repo, "checkout", "-b", "feature")
    (repo / "assets").mkdir()
    (repo / "assets" / "example.bin").write_bytes(b"branch\0binary")
    git(repo, "add", "assets/example.bin")
    git(repo, "commit", "-m", "binary")

    code, snapshot = run_snapshot(capsys, repo, config, "--mode", "large_merge", "--baseline", "main", "--pass", "1")

    assert code == 0
    entry = snapshot["entries"]["merge_base_to_head"][0]
    assert entry["path"] == "assets/example.bin"
    assert entry["binary"] is True


def test_custom_mode_declared_by_config_is_accepted(capsys, tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    config = {
        "version": 1,
        "rule_files": [],
        "modes": {
            "docs_review": {
                "scope": ["unstaged"],
                "max_changed_files": 10,
                "requires_repo_map": False,
            }
        },
        "slices": [{"id": "source", "paths": ["src/**"], "risk": "medium"}],
        "gates": [],
    }
    config_path = repo / "gates.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    (repo / "src" / "app.py").write_text("print('custom')\n", encoding="utf-8")

    code, snapshot = run_snapshot(
        capsys,
        repo,
        config_path,
        "--mode",
        "docs_review",
        "--pass",
        "1",
        "--write-run-record",
        "--cache-dir",
        str(tmp_path / "cache"),
    )

    assert code == 0
    assert snapshot["mode"] == "docs_review"
    assert snapshot["must_reload"] == ["src/app.py"]

    code = main(["validate-schema", "--schema", "snapshot", "--file", snapshot["snapshot_path"], "--repo", str(repo)])
    captured = capsys.readouterr()
    assert code == 0, captured.err

    code = main(["validate-schema", "--schema", "run-record", "--file", snapshot["run_record_path"], "--repo", str(repo)])
    captured = capsys.readouterr()
    assert code == 0, captured.err


def test_runtime_import_uses_no_external_dependency() -> None:
    assert "pytest" not in sys.modules.get("review_fix_loop", object()).__dict__
