# Remaining Work Implementation Plan

This document replaces the earlier multi-PR roadmap with the executable scope
for the current branch. The review found that the previous version treated
remote repository administration as local acceptance work. That was not
actionable from a local checkout, so the corrected plan separates local
implementation from external verification.

## Invariants

All work in this branch must preserve these constraints:

- the runtime package keeps zero install-time dependencies;
- CI, security, release, and documentation tooling stay in `.[dev]` or GitHub
  Actions setup;
- adapter configs remain JSON data, not Python plugin code;
- snapshots and run records keep bounded metadata only, not full source text or
  full diffs;
- schema changes are mirrored between `src/review_fix_loop/schemas/` and
  `skills/review-fix-loop-core/references/`;
- English and Chinese user-facing docs stay structurally paired.

## Implemented Work Packages

### CI Baselines

Split CI into `lint`, `typecheck`, matrix `test`, `build`, and
`artifact-hygiene` jobs. Test jobs upload JUnit and coverage XML with
`if: always()`. The build job creates distributions, runs `twine check`, and
smoke-tests the installed wheel.

### Security Workflow

Add `.github/workflows/security.yml` with Bandit, pip-audit, CodeQL, and
Dependency Review. Security tools are dev-only dependencies.

### Snapshot Performance Batching

Batch changed-line extraction by scope with `parse_unified_diff_by_path` and
`diff_line_ranges_for_scope`. Batch HEAD blob lookup and blob binary sampling
for committed branch entries while keeping the existing per-file fallback.

### CLI, Service, And Domain Boundaries

Keep `cli.py` as parser and dispatch, and move freshness/fresh-tree business
rules into `services/snapshot_service.py`. Add typed internal domain helpers
under `domain/types.py` and a gate service wrapper for execution.

### External Gate Trust Boundary

Add gate config fields `trusted`, `allow_in_ci`, `writes_worktree`,
`requires_network`, and `trust_reason`. Builtins are trusted by definition.
Normal local mode preserves compatibility and records trust warnings for
untrusted external gates. `gate --ci-mode` refuses external gates unless both
`trusted=true` and `allow_in_ci=true`.

### Parallel-Safe Gate Execution

Add `parallel_safe`, `reads_worktree_only`, and `depends_on`. Gate execution is
serial by default; contiguous ready gates marked `parallel_safe` run with a
thread pool. Result order remains the snapshot's `planned_gates` order.

### Adapter Mode Capability Model

Allow custom mode ids declared by the adapter config. Keep `normal_loop` and
`large_merge` in bundled templates, and validate advisory capability fields
such as `requires_merge_base`, `requires_repo_map`, `max_changed_files`, and
`max_diff_bytes_per_slice`.

### Documentation Parity And Locale

Add `--locale` / `REVIEW_FIX_LOOP_LOCALE` for common human-readable errors
while keeping JSON keys in English. Add Chinese counterparts for primary docs
and a docs parity test.

### Release Automation

Add `.github/workflows/release.yml` for tag builds, wheel smoke tests, and PyPI
Trusted Publishing. The release checklist now states the required PyPI/TestPyPI
trusted publisher setup and dry-run path.

## Local Completion Criteria

The branch is locally complete when all of these pass:

1. `python -m pytest -q`;
2. `python -m ruff check src tests`;
3. `python -m mypy src/review_fix_loop`;
4. `python -m build && python -m twine check dist/*`;
5. workflow YAML parse tests;
6. schema sync tests;
7. a final fresh `review-fix-loop snapshot` and `gate --ci-mode` pass has no
   blocking diagnostics.

## External Verification

These items cannot be proven from a local checkout and must be completed in the
GitHub/PyPI environment:

- configure branch protection required checks after the split CI jobs exist;
- confirm the `Security` workflow is green on GitHub Actions;
- configure PyPI/TestPyPI Trusted Publishing for this repository and workflow;
- run the release workflow against TestPyPI or an equivalent dry run before the
  first production PyPI publish.
