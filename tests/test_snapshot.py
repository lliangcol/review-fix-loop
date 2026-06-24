from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from review_fix_loop.cli import main
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
