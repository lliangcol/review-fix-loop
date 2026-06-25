# Contributing

Thanks for helping improve Review Fix Loop. Keep contributions focused on the local fresh-snapshot contract for AI review/fix/re-review workflows.

## Development Setup

```bash
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q
```

Use an isolated virtual environment for local development. Some Python
installations, including uv-managed interpreters, reject direct editable
installs with PEP 668 `externally-managed-environment`.

Before opening a pull request, run the same local checks that back the CI,
security, and release workflows when your environment supports them:

```bash
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pytest -q --cov=review_fix_loop --cov-branch --cov-report=term-missing
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m mypy src/review_fix_loop
.\.venv\Scripts\python.exe -m bandit -r src/review_fix_loop
.\.venv\Scripts\python.exe -m pip_audit
.\.venv\Scripts\python.exe -m build
.\.venv\Scripts\python.exe -m twine check dist/*
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
