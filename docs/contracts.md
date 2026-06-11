# Behavior Contracts

This page summarizes the behavior covered by the current test suite and contract examples.

## Freshness

- Pass 2 and later require `--previous-run-record`.
- Changed slice hashes mark slices as forbidden for reuse.
- Previous fixes and unresolved diagnostics can force a slice to be reloaded.
  Gate diagnostics are attributed to slices by file path, so a failing gate on
  an unchanged slice still forbids reuse on the next pass.
- Config hash and rule file hash changes require a fresh snapshot before gates run.
- `gate --require-fresh-tree` optionally fails when the working tree no longer
  matches the snapshot scope hashes. Leave it off when gates intentionally run
  after fixes were applied (the standard loop order).

## Git Snapshot Semantics

- Staged, unstaged, and untracked changes are separated.
- Large-merge mode separates `merge_base..HEAD` branch diff from dirty worktree changes.
- Renames preserve old and new paths.
- Binary files are marked and hashed without storing raw content.
- Large file tail changes still invalidate the owning slice through content hashing.

## Gates

- Gates are planned from the snapshot and run by ID.
- `when_paths` selectors limit expensive or domain-specific gates to relevant
  changed paths.
- `final_always` gates can be planned for a final-pass snapshot even when no
  matching path changed.
- Warning diagnostics below an `error` fail level do not fail the gate.
- Nonblocking JSON diagnostics do not fail a blocking gate.
- Malformed JSON diagnostics, invalid diagnostic shape, and missing commands are reported as gate failures.
- The generic adapter checks untracked whitespace without adding files to the Git index.

## Run Records

- `snapshot.json` and `run-record.json` avoid full source text, full diffs, secrets, and unredacted command output.
- Run records still store paths, hashes, gate results, diagnostics, and other metadata needed for the next pass.

## Contract Fixtures

The `examples/contracts` directory contains concise scenario fixtures for stale-diff prevention, large-merge residual risk, subagent slice review, project adapter gates, and auto-fix boundaries.
