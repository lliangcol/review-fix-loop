from __future__ import annotations

import json
from pathlib import Path

import yaml


def test_contract_fixtures_exist() -> None:
    root = Path(__file__).resolve().parents[1] / "examples" / "contracts"
    expected = {
        "case-01-normal-loop-stale-diff.md",
        "case-02-large-merge-residual-risk.md",
        "case-03-subagent-slice-review.md",
        "case-04-project-adapter-gates.md",
        "case-05-auto-fix-boundary.md",
    }
    assert expected == {path.name for path in root.glob("case-*.md")}


def test_core_skill_contains_fresh_snapshot_rule() -> None:
    skill = Path(__file__).resolve().parents[1] / "skills" / "review-fix-loop-core" / "SKILL.md"
    text = skill.read_text(encoding="utf-8")
    assert "Reusing pass 1 diff or pass 1 findings without a fresh snapshot is invalid" in text


def test_snapshot_schema_includes_reloaded_slices() -> None:
    schema_path = Path(__file__).resolve().parents[1] / "skills" / "review-fix-loop-core" / "references" / "snapshot.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert "reloaded_slices" in schema["required"]
    assert "reloaded_slices" in schema["properties"]
    assert "config_sources" in schema["properties"]
    assert "local_override_applied" in schema["properties"]


def test_workflow_yaml_files_parse() -> None:
    root = Path(__file__).resolve().parents[1] / ".github" / "workflows"
    for path in root.glob("*.yml"):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(data, dict), path
        assert "jobs" in data, path


def test_skill_reference_schemas_match_packaged_schemas() -> None:
    root = Path(__file__).resolve().parents[1]
    src_schema_root = root / "src" / "review_fix_loop" / "schemas"
    skill_schema_root = root / "skills" / "review-fix-loop-core" / "references"
    for src_path in src_schema_root.glob("*.schema.json"):
        skill_path = skill_schema_root / src_path.name
        assert skill_path.exists()
        assert json.loads(src_path.read_text(encoding="utf-8")) == json.loads(skill_path.read_text(encoding="utf-8"))


def test_docs_have_zh_cn_counterparts() -> None:
    docs_root = Path(__file__).resolve().parents[1] / "docs"
    exemptions = {"assets"}
    for english_doc in docs_root.glob("*.md"):
        if english_doc.stem in exemptions:
            continue
        zh_doc = docs_root / "zh-CN" / english_doc.name
        assert zh_doc.exists(), f"missing zh-CN counterpart for {english_doc.name}"


def test_generated_artifact_paths_are_ignored_and_untracked() -> None:
    root = Path(__file__).resolve().parents[1]
    ignore_text = (root / ".gitignore").read_text(encoding="utf-8")
    for pattern in ("dist/", "build/", "*.egg-info/", ".review-fix-loop/", ".pytest_cache/"):
        assert pattern in ignore_text


def test_runtime_never_uses_shell_true() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "review_fix_loop"
    for path in root.glob("*.py"):
        assert "shell=True" not in path.read_text(encoding="utf-8"), path
