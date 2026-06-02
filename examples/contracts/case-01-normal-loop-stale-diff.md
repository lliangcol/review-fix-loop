# Case 01: Normal Loop Stale Diff

Pass 2 must run `review-fix-loop snapshot --previous-run-record ...` before any
re-review. If a slice hash changed, the agent must reload that slice and must
not reuse pass 1 diff text.

