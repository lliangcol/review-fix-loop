# FAQ

## Why require a fresh snapshot?

Because AI agents can carry old diff text and old findings across turns. A fresh snapshot tells the agent which files and slices must be reloaded after fixes.

## Does Review Fix Loop upload source code?

No. The CLI runs locally. It does not call model APIs or external services.

## Do run records contain project information?

Yes. Run records contain metadata such as paths, hashes, gate IDs, diagnostics, and gate summaries. They avoid full source text, full diffs, secrets, and unredacted command output.

## Does it replace CI?

No. CI still owns repository-wide validation. Review Fix Loop helps the local agent choose gates and avoid stale re-review input between fix passes.

## How should I handle a large merge?

Use `--mode large_merge` with a baseline such as `origin/main`. The snapshot separates branch diff from dirty worktree changes so the agent can review the merge and local leftovers separately.

## Can I use it with Claude, Codex, Cursor, or Aider?

Yes. The tool is model-agnostic. The important rule is that the agent must read the fresh snapshot before re-reviewing.

## What should not be committed?

Do not commit workspace-local run records such as `.review-fix-loop/`, build output, caches, or virtual environments.
