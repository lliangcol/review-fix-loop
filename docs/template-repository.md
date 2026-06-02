# Template Repository Guide

Review Fix Loop can be reused in two ways: copy only the adapter template into another repository, or use this repository as a fuller starting point for a workflow-governance project.

## Copy Only The Adapter Template

Use this path when the target project already has its own package, tests, and CI.

1. Copy `adapters/project-template` into the target repository.
2. Rename the adapter directory to match the project.
3. Replace `gates.json` slices with the target project's ownership and risk areas.
4. Replace gate commands with commands that already run locally in that project.
5. Update rule files and remove public placeholder text.

Run records default to `.git/review-fix-loop/runs/...`. If the target project uses `--cache-dir .review-fix-loop`, keep `.review-fix-loop/` ignored.

## Use This Repository As A Template

Use this path when creating a new public workflow package around the same contract.

1. Rename package metadata and repository links.
2. Replace README positioning and docs with the new project purpose.
3. Keep CI, release checks, community files, and docs structure.
4. Replace adapter examples with examples that match the new audience.

## Manual GitHub Setting

If this repository should become a GitHub template repository, enable that setting in GitHub UI before release. This cannot be represented by a normal tracked file unless the repository uses a settings app.
