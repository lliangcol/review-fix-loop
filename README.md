# Review Fix Loop

Review Fix Loop is a local-first toolkit for AI agents that need to review Git
changes, fix findings, and re-review from a fresh live snapshot.

The project provides:

- a dependency-free Python runtime and CLI;
- a `review-fix-loop-core` Skill for agent workflow control;
- staged, unstaged, untracked, and branch-diff snapshot separation;
- slice invalidation to block stale diff reuse;
- diagnostic normalization and gate planning;
- durable run records that avoid storing full source, full diffs, secrets, or
  unredacted command output.

## Install

```bash
python -m pip install -e ".[dev]"
```

The runtime package has no install-time dependencies. Development extras are
only for tests and release checks.

## Snapshot

```bash
review-fix-loop snapshot \
  --repo . \
  --config adapters/generic/gates.json \
  --mode normal_loop \
  --pass 1 \
  --write-run-record
```

For pass 2 and later, pass the previous run record:

```bash
review-fix-loop snapshot \
  --repo . \
  --config adapters/generic/gates.json \
  --mode normal_loop \
  --pass 2 \
  --previous-run-record <run-root>/run-record.json \
  --write-run-record
```

Reusing pass 1 diff or pass 1 findings without a fresh snapshot is an invalid
workflow.

## Gates

```bash
review-fix-loop gate \
  --repo . \
  --config adapters/generic/gates.json \
  --snapshot <run-root>/snapshot.json
```

The gate runner executes only gate IDs selected by the snapshot. If the
effective config hash changed since the snapshot, it fails and requires a new
snapshot.

## Inspirations

The design borrows public patterns from PR-Agent, OpenReview, Gito, reviewdog,
Danger JS, and pre-commit: configurable PR review, large PR context handling,
durable workflows, limited mechanical fixes, provider-agnostic review,
diagnostic filtering, team conventions as code, and staged-file local gates.

## Release Boundary

Version 0.1.0 is not a hosted PR bot. It does not require GitHub App
credentials, cloud sandboxes, model API keys, or external services.

