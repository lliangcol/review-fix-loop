# Contributing

Thanks for helping improve Review Fix Loop. Keep contributions focused on the local fresh-snapshot contract for AI review/fix/re-review workflows.

## Development Setup

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
```

Before opening a pull request, run the same local checks that back the CI,
security, and release workflows when your environment supports them:

```bash
python -m pytest -q
python -m pytest -q --cov=review_fix_loop --cov-branch --cov-report=term-missing
python -m ruff check src tests
python -m mypy src/review_fix_loop
python -m bandit -r src/review_fix_loop
python -m pip_audit
python -m build
python -m twine check dist/*
git diff --check
```

## Contribution Areas

- Core runtime: keep behavior small, local-first, and dependency-light.
- Adapters: prefer narrow, reusable rules and gates over project-private logic.
- Docs: explain real commands, observed outputs, and current boundaries.
- Examples: avoid private paths, company names, secrets, and domain-specific scripts.

## Adapter Contributions

Adapter changes should state:

- which slices are defined;
- which gates can run;
- which modes they support;
- whether they affect snapshot, gate, or run-record behavior.

## Pull Requests

Use the pull request template. Include tests for runtime behavior changes and docs updates for public-facing behavior changes.
