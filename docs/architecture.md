# Architecture

Review Fix Loop is a local workflow contract. It does not review code by itself; it gives an AI agent a reliable way to know when old review context is no longer valid.

## Snapshot

The `snapshot` command reads the live Git repository and produces structured metadata for the current pass. It separates:

- staged changes;
- unstaged changes;
- untracked files;
- large-merge branch diff from `merge_base..HEAD`.

Entries include paths, status metadata, bounded content hashes, binary markers,
slice assignment, and changed-line ranges for diagnostic filtering. They do not
include full source text or full diffs. Worktree file hashes are bounded and
sample both the beginning and end of very large files; symlinks are hashed by
link target instead of following the target file.

## Slice Invalidation

Adapters define slices such as `source`, `tests`, `docs`, or project-specific risk areas. For pass 2 and later, Review Fix Loop compares the current snapshot with the previous run record.

A slice cannot reuse old review context when:

- the slice hash changed;
- the effective gate config changed;
- project rule file hashes changed;
- the previous pass recorded fixes in that slice;
- the previous pass still had diagnostics in that slice.

The snapshot reports `must_reload`, `reloaded_slices`, `reused_slices`, and `reuse_forbidden_slices`.

## Planned Gates

Gate planning happens at snapshot time. Gates can target staged, unstaged, untracked, branch-diff, or all scopes. A gate runs only when the snapshot selected it, except for gates marked as final-pass checks.

Gate execution verifies that the current gate config and rule files still match
the snapshot. If they do not match, the gate command fails and requires a fresh
snapshot. `filter_mode` is applied after parsing diagnostics, so adapters can
use reviewdog-style file, added-line, and diff-context filtering without
discarding tool-level failures.

## Advisory Mode Fields

Modes may carry contract hints such as `require_fresh_snapshot`,
`require_risk_slices`, `require_invariant_checks`,
`require_residual_risk_report`, `max_deep_review_files`, and
`max_diff_bytes_per_slice`. These are validated and folded into the config hash,
but they are **advisory**: the reviewing agent and skill honor them, while the
CLI itself does not mechanically enforce them. The CLI only enforces the
fresh-snapshot, slice-invalidation, and gate contracts described above.

## Run Records And Redaction

When `--write-run-record` is set, the run root receives:

- `snapshot.json`
- `run-record.json`
- `gates.json`
- `summary.md`

Run records keep metadata needed for the next pass: hashes, planned gates,
diagnostics, fixes, stop decision, and residual risks. They avoid full source
text, full diffs, secrets, and unredacted command output. Gate argv, summaries,
diagnostics, and the persisted config copy are redacted before writing.

## Runtime Boundary

The core package has no install-time dependencies and runs locally through the
Python CLI. Adapters provide project-specific rule files, slices, and gate
commands. Bundled templates and schemas are packaged with the wheel so `init`
and `validate-schema` work from an installed CLI.
