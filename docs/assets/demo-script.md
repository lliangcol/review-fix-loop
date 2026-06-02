# Demo Script

Goal: show stale diff risk turning into a fresh snapshot re-review in 30 to 60 seconds.

## Setup

```bash
python -m pip install -e ".[dev]"
```

Create or modify a small file so the repository has a visible working-tree change.

## Pass 1 Snapshot

```bash
review-fix-loop snapshot \
  --repo . \
  --config adapters/generic/gates.json \
  --mode normal_loop \
  --pass 1 \
  --write-run-record \
  --cache-dir .review-fix-loop
```

Narration: the agent receives `must_reload`, `planned_gates`, and paths from the live worktree.

## Fix

Edit the changed file again, as if the agent fixed a finding.

Narration: pass 1 diff text is now stale.

## Pass 2 Fresh Snapshot

```bash
review-fix-loop snapshot \
  --repo . \
  --config adapters/generic/gates.json \
  --mode normal_loop \
  --pass 2 \
  --previous-run-record .review-fix-loop/runs/<run-id>/run-record.json \
  --write-run-record \
  --cache-dir .review-fix-loop
```

Narration: the pass 2 snapshot reports changed slices in `reuse_forbidden_slices` and paths in `must_reload`.

## Gate Current State

```bash
review-fix-loop gate \
  --repo . \
  --config adapters/generic/gates.json \
  --snapshot .review-fix-loop/runs/<new-run-id>/snapshot.json
```

Narration: gates run against the snapshot-selected current state, not stale pass 1 context.
