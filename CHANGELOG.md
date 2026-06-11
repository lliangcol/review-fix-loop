# Changelog

All notable changes to Review Fix Loop are documented here.

## 0.1.0 - Unreleased

Initial public release candidate.

### Added

- Local `review-fix-loop` CLI with `snapshot` and `gate` commands.
- Fresh snapshot contract for pass 2 and later using `--previous-run-record`.
- Snapshot separation for staged, unstaged, untracked, and large-merge branch-diff scopes.
- Slice invalidation for changed slice hashes, gate config changes, project rule changes, previous fixes, and unresolved diagnostics.
- Planned gate execution with normalized diagnostics and redacted command summaries.
- Gate diagnostics attributed to config slices so unresolved findings forbid slice reuse on the next pass.
- Optional `gate --require-fresh-tree` check that fails when the working tree no longer matches the snapshot scope hashes.
- Atomic run-record writes and UTF-8-safe truncation of gate output summaries.
- Durable run records that avoid storing full source text, full diffs, secrets, and unredacted command output.
- Generic adapter and project-template adapter examples.
- Public documentation, community templates, release checklist, and demo script.

### Boundaries

- No hosted PR bot.
- No GitHub App.
- No model API key.
- No external service dependency.
- Adapter ecosystem is still early.
