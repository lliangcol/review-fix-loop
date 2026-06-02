# Project Adapter Template

This directory is a copy point for project-specific Review Fix Loop adapters. It is not part of the core Python package API.

## Files

- `gates.json`: example slices, modes, and gate commands.
- `SKILL.md`: adapter guidance for an agent.
- `agents/openai.yaml`: example agent metadata.
- `references/adapter-authoring.md`: concise authoring notes.

## How To Use It

1. Copy this directory into the target repository.
2. Rename it to match the project or team.
3. Replace slices with real ownership boundaries.
4. Replace gate commands with commands that are already valid in that repository.
5. Replace rule files with public-safe local policy text.

Do not commit private paths, secrets, company-only scripts, or captured command output.

## Run Records

Without `--cache-dir`, run records are written under `.git/review-fix-loop/runs/...` and are outside the worktree. With `--cache-dir .review-fix-loop`, records are written under `.review-fix-loop/runs/...`; keep that path ignored.

## Minimum Smoke Test

```bash
review-fix-loop snapshot \
  --repo . \
  --config adapters/project-template/gates.json \
  --mode normal_loop \
  --pass 1 \
  --write-run-record
```

Then fix, rerun with `--pass 2 --previous-run-record <run-root>/run-record.json`, and confirm changed slices appear in `reuse_forbidden_slices`.
