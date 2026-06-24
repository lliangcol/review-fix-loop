---
name: review-fix-loop-core
description: >
  Use for iterative review, fix, and fresh re-review of Git worktree or branch
  changes. Enforces live snapshot refresh, slice invalidation, diagnostics,
  gate planning, and large merge coverage.
license: Apache-2.0
version: 0.1.0
compatibility:
  agents:
    - claude-code
    - codex
    - copilot
    - gemini-cli
  install_modes:
    - mount
    - copy
allowed-tools: "python git"
metadata:
  review_fix_loop:
    user-invocable: true
    auto-load: false
    disable-model-invocation: false
    domain: tool
    kb-paths: []
    ownership-scope: core-runtime
---

# Review Fix Loop Core

## When to use

Use this skill when the user asks to review current Git changes, fix findings,
and re-review until no new issues remain.

## Required fresh snapshot rule

For pass N, review input must be derived from the live worktree or live branch
snapshot after pass N-1 fixes. Reusing pass 1 diff or pass 1 findings without a fresh snapshot is invalid.

## Normal loop workflow

1. Load relevant project rules and adapter guidance.
2. Run `review-fix-loop snapshot`.
3. Read only invalidated slices and required context.
4. Review findings by severity.
5. Fix only in-scope findings.
6. Run `review-fix-loop gate`.
7. Run `review-fix-loop snapshot` again with `--previous-run-record`.
8. Re-review invalidated slices.
9. Stop only when the fresh snapshot review has no new findings and blocking
   gates pass.

## Large merge workflow

Use `--mode large_merge` with a baseline. Separate `merge_base_to_head`,
`staged`, `unstaged`, and `untracked`; never claim local dirty fixes are part
of the committed branch diff.

Report coverage as fully reviewed, mechanically verified, invariant checked,
sampled, not reviewed, and residual risks.

## Cache reuse rules

Reuse is allowed only when the slice hash, config hash, relevant rule hashes,
and previous diagnostics allow it. If the current snapshot marks a slice in
`reuse_forbidden_slices`, reload that slice before reviewing.

## Gate planning rules

Run only gates selected by the current snapshot `planned_gates`. If gate config
changed, create a fresh snapshot before executing gates.

Use `gate --ci-mode` for CI-style validation so untrusted external gates are
refused unless the adapter marks both `trusted=true` and `allow_in_ci=true`.
Parallel-safe gates may complete out of order, but run records preserve
`planned_gates` order.

## Diagnostic reporting rules

Report mechanical findings with severity, rule, file, line, message, scope,
slice, and blocking status when available.

## Subagent coordination rules

Subagents are optional. Give each subagent one slice or disjoint file set, the
current `snapshot_id`, selected scope, and `must_reload`. The main agent owns
final synthesis, fixes, and validation status.

## Stop conditions

Stop only when a fresh re-review finds no new in-scope findings, blocking gates
pass, and residual risks are explicitly reported.

## Output template

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
