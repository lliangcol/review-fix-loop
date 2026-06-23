"""Regression tests for issues found during deep review."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from review_fix_loop.cli import main
from review_fix_loop.errors import GitError
from review_fix_loop.git_snapshot import collect_merge_base_to_head, collect_scopes
from review_fix_loop.gates import run_untracked_whitespace_builtin
from review_fix_loop.repo_map import build_repo_map
from review_fix_loop.run_record import write_json
from review_fix_loop.utils import truncate_text


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


def write_config(repo: Path, gates: list[dict], modes: dict | None = None) -> Path:
    config = {
        "version": 1,
        "rule_files": [],
        "modes": modes or {
            "normal_loop": {"scope": ["staged", "unstaged", "untracked"]},
            "large_merge": {"baseline": "main", "scope": ["merge_base_to_head", "staged", "unstaged", "untracked"]},
        },
        "slices": [{"id": "source", "paths": ["src/**"], "risk": "medium"}],
        "gates": gates,
    }
    path = repo / "gates.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def run_snapshot(capsys, repo: Path, config: Path, cache: Path, *extra: str) -> dict:
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


def test_truncate_text_clipped_multibyte_stays_valid_utf8() -> None:
    text = "a" * 8191 + "中文测试"
    truncated = truncate_text(text)
    truncated.encode("utf-8")  # must not raise: no lone surrogates
    assert truncated.endswith("[truncated to 8192 bytes]")
    assert "\udce4" not in truncated


def test_gate_with_large_multibyte_output_keeps_run_record_valid(capsys, tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    emit = "import sys; sys.stdout.buffer.write(b'a'*8191 + '\\u4e2d\\u6587'.encode('utf-8') * 20)"
    config = write_config(repo, [
        {
            "id": "big-output",
            "argv": [sys.executable, "-c", emit],
            "scope": "all",
            "final_always": True,
            "parser": {"type": "exit-code"},
        }
    ])
    snap = run_snapshot(capsys, repo, config, tmp_path / "cache", "--final-pass")

    code = main(["gate", "--repo", str(repo), "--config", str(config), "--snapshot", snap["snapshot_path"]])
    captured = capsys.readouterr()

    assert code == 0, captured.err
    record = json.loads(Path(snap["run_record_path"]).read_text(encoding="utf-8"))
    assert record["gates"][0]["status"] == "passed"


def test_write_json_failure_keeps_previous_file_intact(tmp_path: Path) -> None:
    target = tmp_path / "record.json"
    write_json(target, {"ok": True})
    with pytest.raises(UnicodeEncodeError):
        write_json(target, {"bad": "\udce4"})

    assert json.loads(target.read_text(encoding="utf-8")) == {"ok": True}
    assert not target.with_name(target.name + ".tmp").exists()


def test_unresolved_diagnostics_forbid_slice_reuse(capsys, tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    (repo / "src" / "app.py").write_text("print('dirty')\n", encoding="utf-8")
    config = write_config(repo, [
        {
            "id": "always-fails-on-src",
            "argv": [sys.executable, "-c", "import sys; print('src/app.py:1:bad code'); sys.exit(1)"],
            "scope": "all",
            "final_always": True,
            "blocking": True,
            "parser": {
                "type": "regex-lines",
                "pattern": "^(?P<file>[^:]+):(?P<line>\\d+):(?P<message>.*)$",
                "severity": "error",
            },
        }
    ])
    snap = run_snapshot(capsys, repo, config, tmp_path / "cache")

    code = main(["gate", "--repo", str(repo), "--config", str(config), "--snapshot", snap["snapshot_path"]])
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert code == 1
    assert result["diagnostics"][0]["slice"] == "source"

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
        snap["run_record_path"],
    ])
    captured = capsys.readouterr()
    second = json.loads(captured.out)

    assert code == 0
    assert "source" not in second["reused_slices"]
    assert "previous pass had unresolved diagnostics in slice" in second["reuse_forbidden_slices"]["source"]


def test_snapshot_with_mode_missing_from_config_reports_config_error(capsys, tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    config = write_config(repo, [], modes={"normal_loop": {"scope": ["unstaged"]}})

    code = main([
        "snapshot",
        "--repo",
        str(repo),
        "--config",
        str(config),
        "--mode",
        "large_merge",
        "--baseline",
        "main",
        "--pass",
        "1",
    ])
    captured = capsys.readouterr()

    assert code == 1
    assert "mode is not defined in config: large_merge" in captured.err
    assert "Traceback" not in captured.err


def test_non_integer_timeout_seconds_is_config_error(capsys, tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    config = write_config(repo, [
        {
            "id": "bad-timeout",
            "argv": [sys.executable, "-c", "print(1)"],
            "scope": "all",
            "final_always": True,
            "timeout_seconds": "60",
            "parser": {"type": "exit-code"},
        }
    ])

    code = main(["validate-config", "--repo", str(repo), "--config", str(config)])
    captured = capsys.readouterr()

    assert code == 1
    assert "timeout_seconds must be an integer >= 1" in captured.err


def test_non_boolean_gate_flags_are_config_errors(capsys, tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    config = write_config(repo, [
        {
            "id": "bad-blocking",
            "argv": [sys.executable, "-c", "print(1)"],
            "scope": "all",
            "blocking": "yes",
            "parser": {"type": "exit-code"},
        }
    ])

    code = main(["validate-config", "--repo", str(repo), "--config", str(config)])
    captured = capsys.readouterr()

    assert code == 1
    assert "blocking must be a boolean" in captured.err


def test_untracked_symlink_outside_repo_is_skipped(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("trailing space  \n", encoding="utf-8")
    try:
        os.symlink(outside, repo / "link.txt")
    except OSError:
        pytest.skip("symlinks are not permitted on this host")

    snapshot = {
        "entries": {
            "untracked": [
                {"path": "link.txt", "deleted": False, "binary": False, "symlink": True},
            ]
        }
    }
    exit_code, stdout, stderr = run_untracked_whitespace_builtin(repo, snapshot)

    assert exit_code == 0
    assert stdout == ""
    assert stderr == ""


def test_repo_map_truncated_only_counts_python_files(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    entries = {"unstaged": [{"path": "a.py"}, {"path": "z1.md"}, {"path": "z2.md"}]}

    result = build_repo_map(repo, entries, max_files=1)

    assert [item["path"] for item in result["files"]] == ["a.py"]
    assert result["truncated"] is False


def test_repeated_run_records_use_distinct_run_directories(capsys, tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    config = write_config(repo, [])
    (repo / "src" / "app.py").write_text("print('dirty')\n", encoding="utf-8")

    first = run_snapshot(capsys, repo, config, tmp_path / "cache")
    second = run_snapshot(capsys, repo, config, tmp_path / "cache")

    assert first["snapshot_id"] == second["snapshot_id"]
    assert first["run_record_path"] != second["run_record_path"]


def test_large_merge_mode_without_branch_scope_skips_merge_base(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    # The mode name alone must not force merge_base_to_head collection nor
    # require a baseline when the mode scope does not request the branch diff.
    merge_base, entries = collect_scopes(repo, "large_merge", None, ["staged"])

    assert merge_base is None
    assert entries["merge_base_to_head"] == []

    # When the scope does request the branch diff, a missing baseline is still
    # rejected.
    with pytest.raises(GitError):
        collect_scopes(repo, "large_merge", None, ["merge_base_to_head", "staged"])


def test_merge_base_deleted_entry_includes_line_range_keys(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    git(repo, "branch", "base")
    git(repo, "rm", "src/app.py")
    git(repo, "commit", "-m", "delete app")

    _, entries = collect_merge_base_to_head(repo, "base")
    deleted = [entry for entry in entries if entry["path"] == "src/app.py"]

    assert deleted and deleted[0]["deleted"] is True
    # Deleted branch-diff entries must carry the same line-range keys as every
    # other scope so entry shapes stay consistent across scopes.
    assert deleted[0]["changed_lines"] == []
    assert deleted[0]["diff_context_lines"] == []


def test_baseline_recorded_for_any_mode_using_merge_base_scope(capsys, tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    # A non-large_merge mode is allowed to declare merge_base_to_head scope.
    # Branch off, then advance HEAD so the branch diff is non-empty.
    git(repo, "branch", "base")
    (repo / "src" / "app.py").write_text("print('changed')\n", encoding="utf-8")
    git(repo, "commit", "-am", "change app")

    config = write_config(repo, [
        {
            "id": "echo-baseline",
            "argv": ["__builtin__:policy"],
            "scope": "all",
            "policy": {},
            "parser": {"type": "json-diagnostics"},
        }
    ], modes={
        "normal_loop": {"baseline": "base", "scope": ["merge_base_to_head", "staged"]},
    })

    snapshot = run_snapshot(capsys, repo, config, tmp_path / "cache")

    # The baseline must be keyed off the scope, not the mode name: it feeds the
    # snapshot id and gate {baseline} expansion whenever the branch diff runs.
    assert snapshot["baseline"] == "base"
    assert snapshot["merge_base"]


def test_baseline_omitted_when_mode_does_not_use_merge_base_scope(capsys, tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    # A stray baseline in a mode that never collects the branch diff must not
    # leak into the snapshot record.
    config = write_config(repo, [
        {"id": "noop", "argv": ["__builtin__:policy"], "scope": "all", "policy": {}, "parser": {"type": "json-diagnostics"}}
    ], modes={
        "normal_loop": {"baseline": "main", "scope": ["staged", "unstaged", "untracked"]},
    })

    snapshot = run_snapshot(capsys, repo, config, tmp_path / "cache")

    assert snapshot["baseline"] is None
    assert snapshot["merge_base"] is None


def test_unknown_builtin_gate_is_rejected_at_config_time(capsys, tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    # A typo in a builtin name must surface as a config error, not as an opaque
    # "could not execute" failure at gate runtime.
    config = write_config(repo, [
        {
            "id": "typo-builtin",
            "argv": ["__builtin__:untracked-whitepace"],
            "scope": "untracked",
            "parser": {"type": "git-diff-check"},
        }
    ])

    code = main(["validate-config", "--repo", str(repo), "--config", str(config)])
    captured = capsys.readouterr()

    assert code == 1
    assert "unknown builtin command: __builtin__:untracked-whitepace" in captured.err
    assert "Traceback" not in captured.err


def test_known_builtin_gates_pass_config_validation(capsys, tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    config = write_config(repo, [
        {
            "id": "untracked-ws",
            "argv": ["__builtin__:untracked-whitespace"],
            "scope": "untracked",
            "parser": {"type": "git-diff-check"},
        },
        {
            "id": "policy-check",
            "argv": ["__builtin__:policy"],
            "scope": "all",
            "policy": {"forbid_changed_paths": ["secrets/**"]},
            "parser": {"type": "json-diagnostics"},
        },
    ])

    code = main(["validate-config", "--repo", str(repo), "--config", str(config)])
    captured = capsys.readouterr()

    assert code == 0, captured.err


def test_gate_require_fresh_tree_detects_worktree_change(capsys, tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    config = write_config(repo, [
        {
            "id": "noop",
            "argv": [sys.executable, "-c", "print('ok')"],
            "scope": "all",
            "final_always": True,
            "parser": {"type": "exit-code"},
        }
    ])
    (repo / "src" / "app.py").write_text("print('dirty')\n", encoding="utf-8")
    snap = run_snapshot(capsys, repo, config, tmp_path / "cache", "--final-pass")

    code = main([
        "gate", "--repo", str(repo), "--config", str(config),
        "--snapshot", snap["snapshot_path"], "--require-fresh-tree",
    ])
    captured = capsys.readouterr()
    assert code == 0, captured.err

    (repo / "src" / "app.py").write_text("print('changed again')\n", encoding="utf-8")
    code = main([
        "gate", "--repo", str(repo), "--config", str(config),
        "--snapshot", snap["snapshot_path"], "--require-fresh-tree",
    ])
    captured = capsys.readouterr()

    assert code == 1
    assert "working tree changed since snapshot" in captured.err
