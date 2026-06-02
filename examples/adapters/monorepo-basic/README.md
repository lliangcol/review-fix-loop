# Monorepo Basic Adapter

Scenario: a repository with backend, frontend, shared packages, and docs wants gates selected by changed ownership areas.

## Snapshot

```bash
review-fix-loop snapshot \
  --repo . \
  --config examples/adapters/monorepo-basic/gates.json \
  --mode large_merge \
  --baseline origin/main \
  --pass 1 \
  --write-run-record
```

## Expected Gate Selection

- Backend changes select `backend-tests`.
- Frontend changes select `frontend-tests`.
- Shared package changes select both backend and frontend tests.
- Docs-only changes select whitespace gates but avoid expensive app tests.

Replace paths and commands with the target monorepo layout.
