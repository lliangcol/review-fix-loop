# Review Loop Runbook

This runbook describes a complete local review/fix/re-review loop for an AI
agent. It is repository-neutral: project-specific rules, slices, and gates come
from the selected adapter.

## Goal

The loop is complete only when the agent has reviewed the current live
snapshot, fixed in-scope findings, generated a fresh snapshot after those
fixes, re-reviewed invalidated slices, run blocking gates, and reported
residual risks.

## Prompt Pattern

Use a prompt like:

```text
Review the current repository changes, fix in-scope findings with the smallest
useful change, create a fresh snapshot after fixes, and re-review invalidated
slices until no new in-scope findings remain and blocking gates pass.
```

For a branch or large merge, include the baseline:

```text
Use large_merge mode with baseline origin/main. Separate committed branch diff,
staged changes, unstaged changes, and untracked files. Do not report local dirty
fixes as committed branch changes.
```

## Required Inputs

Before reviewing, load:

- the selected core skill guidance, usually `skills/review-fix-loop-core/SKILL.md`;
- the selected adapter guidance, such as `adapters/project-template/SKILL.md`;
- the adapter gate config, such as `adapters/project-template/gates.json`;
- repository-local rule files declared by the adapter;
- nearest subdirectory rule files that apply to touched paths.

If a declared rule file is missing, report the limitation instead of inventing
project policy.

## Normal Loop

Create pass 1:

```bash
review-fix-loop snapshot \
  --repo . \
  --config adapters/project-template/gates.json \
  --mode normal_loop \
  --pass 1 \
  --write-run-record
```

Review only the paths and slices that the snapshot says must be loaded. Fix only
in-scope findings.

Run gates selected by the snapshot:

```bash
review-fix-loop gate \
  --repo . \
  --config adapters/project-template/gates.json \
  --snapshot <snapshot-json>
```

Create pass 2 from the previous run record:

```bash
review-fix-loop snapshot \
  --repo . \
  --config adapters/project-template/gates.json \
  --mode normal_loop \
  --pass 2 \
  --previous-run-record <run-record-json> \
  --write-run-record
```

When a pass is intended to be the final verification pass, add `--final-pass`
to the snapshot command before running gates. This ensures gates marked
`final_always` are included in `planned_gates` even when no matching path
changed.

Re-review invalidated slices from the fresh snapshot. Repeat until the stop
conditions are met.

## Large Merge Loop

Use `large_merge` when the branch diff is large enough that branch changes,
staged changes, unstaged changes, and untracked files must be reported
separately:

```bash
review-fix-loop snapshot \
  --repo . \
  --config adapters/project-template/gates.json \
  --mode large_merge \
  --baseline origin/main \
  --pass 1 \
  --write-run-record
```

For the final large-merge verification snapshot, include `--final-pass` before
running gates so final-pass checks are planned.

The final report should distinguish:

- fully reviewed files or slices;
- mechanically verified files or slices;
- invariant-checked behavior;
- sampled areas;
- not-reviewed areas;
- residual risks.

## Gate Selection

Run only gates listed in the snapshot's `planned_gates`. If the adapter config
or any declared rule file changes after the snapshot, create a fresh snapshot
before running gates.

Use adapter `when_paths` selectors for expensive or domain-specific gates. This
keeps ordinary documentation or formatting changes from triggering unrelated
project checks.

## Auto-Fix Boundary

Safe auto-fix categories usually include:

- whitespace and formatting diagnostics reported by configured gates;
- generated indexes or metadata when the generator command is declared;
- documentation metadata drift when the adapter marks it safe.

Stop for confirmation before changes that affect public APIs, data, payments,
entitlements, queues, transactions, data sources, CI/CD, deployment, permissions,
cloud configuration, dependencies, broad migrations, or history.

## Final Report

Report:

```text
Pass:
Snapshot:
Must reload:
Reloaded slices:
Reused slices:
Reuse forbidden:
Findings:
Fixes:
Gates:
Stop decision:
Residual risks:
```

Do not claim success until a fresh re-review has no new in-scope findings and
blocking gates have passed or have been explicitly waived.
