from __future__ import annotations

import json
import re
from pathlib import Path

import yaml


README_DOC_LINK_RE = re.compile(r"^- \[[^\]]+\]\(([^)]+)\)$")
GENERATED_ARTIFACT_HYGIENE_PATTERNS = {
    "__pycache__/": "__pycache__",
    ".pytest_cache/": r"\.pytest_cache",
    ".mypy_cache/": r"\.mypy_cache",
    ".ruff_cache/": r"\.ruff_cache",
    "*.egg-info/": r"\.egg-info",
    "dist/": "^dist/",
    "build/": "^build/",
    ".review-fix-loop/": r"^\.review-fix-loop/",
}


def zh_counterpart_link(link: str) -> str:
    if link.startswith("docs/"):
        return link.replace("docs/", "docs/zh-CN/", 1)
    if link == "README.zh-CN.md":
        return "README.md"
    return link


def read_markdown_section_links(path: Path, heading: str) -> list[str]:
    links: list[str] = []
    in_section = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line == heading:
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if in_section:
            match = README_DOC_LINK_RE.match(line)
            if match:
                links.append(match.group(1))
    return links


def read_markdown_heading_levels(path: Path) -> list[int]:
    levels: list[int] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^(#{1,6})\s+\S", line)
        if match:
            levels.append(len(match.group(1)))
    return levels


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
    src_names = sorted(path.name for path in src_schema_root.glob("*.schema.json"))
    skill_names = sorted(path.name for path in skill_schema_root.glob("*.schema.json"))
    assert src_names == skill_names

    for src_path in sorted(src_schema_root.glob("*.schema.json")):
        skill_path = skill_schema_root / src_path.name
        assert src_path.read_bytes() == skill_path.read_bytes()


def test_docs_have_zh_cn_counterparts() -> None:
    docs_root = Path(__file__).resolve().parents[1] / "docs"
    exemptions = {"assets"}
    for english_doc in docs_root.glob("*.md"):
        if english_doc.stem in exemptions:
            continue
        zh_doc = docs_root / "zh-CN" / english_doc.name
        assert zh_doc.exists(), f"missing zh-CN counterpart for {english_doc.name}"
    for zh_doc in (docs_root / "zh-CN").glob("*.md"):
        english_doc = docs_root / zh_doc.name
        assert english_doc.exists(), f"missing English counterpart for zh-CN/{zh_doc.name}"


def test_docs_zh_cn_counterparts_keep_heading_structure() -> None:
    docs_root = Path(__file__).resolve().parents[1] / "docs"
    exemptions = {"assets"}
    for english_doc in docs_root.glob("*.md"):
        if english_doc.stem in exemptions:
            continue
        zh_doc = docs_root / "zh-CN" / english_doc.name
        assert read_markdown_heading_levels(zh_doc) == read_markdown_heading_levels(english_doc), (
            f"heading structure differs for {english_doc.name}"
        )


def test_root_readme_documentation_links_are_paired() -> None:
    root = Path(__file__).resolve().parents[1]
    english_links = read_markdown_section_links(root / "README.md", "## Documentation")
    zh_links = read_markdown_section_links(root / "README.zh-CN.md", "## \u6587\u6863")

    expected_zh_links = [zh_counterpart_link(link) for link in english_links]

    assert zh_links == expected_zh_links
    for link in english_links + zh_links:
        assert (root / link).exists(), link


def test_generated_artifact_paths_are_ignored_and_guarded_by_ci() -> None:
    root = Path(__file__).resolve().parents[1]
    ignored_patterns = set((root / ".gitignore").read_text(encoding="utf-8").splitlines())
    workflow = yaml.safe_load((root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    hygiene_steps = workflow["jobs"]["artifact-hygiene"]["steps"]
    hygiene_script = next(
        step["run"] for step in hygiene_steps if step.get("name") == "Check generated artifacts are not tracked"
    )

    assert "git ls-files" in hygiene_script
    for ignore_pattern, hygiene_pattern in GENERATED_ARTIFACT_HYGIENE_PATTERNS.items():
        assert ignore_pattern in ignored_patterns
        assert hygiene_pattern in hygiene_script


def test_runtime_never_uses_shell_true() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "review_fix_loop"
    for path in root.glob("*.py"):
        assert "shell=True" not in path.read_text(encoding="utf-8"), path
