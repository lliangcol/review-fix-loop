from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from review_fix_loop.cli import main


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

    assert "do-not-store" not in record_text
    assert "secret_token" not in record_text
    assert snapshot["run_record_path"].endswith("run-record.json")
    assert Path(snapshot["snapshot_path"]).exists()


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
