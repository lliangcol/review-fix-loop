# Python Basic Adapter

Scenario: a small Python package wants stale-diff protection plus local whitespace, unit test, and package build gates.

## Snapshot

```bash
review-fix-loop snapshot \
  --repo . \
  --config examples/adapters/python-basic/gates.json \
  --mode normal_loop \
  --pass 1 \
  --write-run-record
```

## Expected Gate Selection

- Source or test changes select `pytest`.
- Packaging file changes select `build-check`.
- Staged, unstaged, and untracked changes select the matching whitespace gate.

Replace commands with the exact test and build commands for the target package.
