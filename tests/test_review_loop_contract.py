from __future__ import annotations

import json
from pathlib import Path


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
