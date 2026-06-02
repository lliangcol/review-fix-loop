# Frontend Basic Adapter

Scenario: a Vite, Vue, React, or similar frontend project wants local review-loop gates without a hosted PR bot.

## Snapshot

```bash
review-fix-loop snapshot \
  --repo . \
  --config examples/adapters/frontend-basic/gates.json \
  --mode normal_loop \
  --pass 1 \
  --write-run-record
```

## Expected Gate Selection

- Source changes select `lint` and `test`.
- Package metadata changes select `install-metadata-review`.
- Staged, unstaged, and untracked changes select the matching whitespace gate.

Replace `corepack pnpm ...` commands with the package manager used by the target project.
