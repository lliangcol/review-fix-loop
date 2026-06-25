# Review Fix Loop Maintenance Status

Last updated: 2026-06-25

## Project Positioning

Review Fix Loop is a local-first CLI contract for AI review/fix/re-review loops.
It governs when an agent must refresh evidence from the live Git worktree after
fixes. It does not review code itself, call model APIs, provide hosted services,
act as a GitHub App, or run as an automatic repair platform.

## Hard Constraints

- Runtime package dependencies stay empty in `pyproject.toml`; test, schema,
  lint, type, security, and release tools stay in `.[dev]` or GitHub Actions.
- Core code must not add model APIs, cloud services, network dependencies, or
  external reviewer behavior.
- Adapter configs remain JSON data rather than Python plugins.
- Snapshots, run records, and gate outputs persist bounded redacted metadata
  only; they must not persist full source, full diffs, secrets, unredacted
  stdout/stderr, private paths, or environment details.
- Schema changes must keep `src/review_fix_loop/schemas/` and
  `skills/review-fix-loop-core/references/` synchronized.
- User-facing behavior changes require paired English and Chinese docs updates;
  JSON, schema, and artifact fields remain English.
- Do not commit `.review-fix-loop/`, `dist/`, `build/`, `*.egg-info`, caches,
  `__pycache__/`, or local run artifacts.
- Validation results must be reported as actually run, failed, skipped, or not
  run; do not infer passing status.

## Fact Sources Checked

- `git status --short`
- `README.md`
- `README.zh-CN.md`
- `pyproject.toml`
- `.github/workflows/ci.yml`
- `.github/workflows/security.yml`
- `.github/workflows/release.yml`
- GitHub Actions API for `lliangcol/review-fix-loop` workflow runs and jobs
- `CONTRIBUTING.md`
- `docs/remaining-work-implementation-plan.md`
- `docs/zh-CN/remaining-work-implementation-plan.md`
- `adapters/generic/gates.json`
- `src/review_fix_loop/templates/generic.gates.json`
- `src/review_fix_loop/schemas/*.schema.json`
- `skills/review-fix-loop-core/references/*.schema.json`
- `tests/test_review_loop_contract.py`

## Key Directories

- `src/review_fix_loop/`: runtime package and CLI implementation.
- `src/review_fix_loop/schemas/`: packaged JSON schemas.
- `src/review_fix_loop/templates/`: bundled adapter templates used by `init`.
- `adapters/`: repository and project adapter examples.
- `skills/review-fix-loop-core/`: skill packaging and schema references.
- `.github/workflows/`: CI, security, and release automation.
- `docs/` and `docs/zh-CN/`: paired user-facing documentation.
- `tests/`: runtime, schema, workflow, and contract tests.

## Current Audit Notes

- Current branch is `main` tracking `origin/main`.
- `pyproject.toml` currently declares `dependencies = []`, matching the
  zero runtime dependency requirement.
- CI, security, and release workflows exist and align with the implementation
  plan at a high level: split lint/type/test/build/artifact hygiene jobs,
  Bandit/pip-audit/CodeQL/Dependency Review, and tag or TestPyPI release flow.
- The CI matrix uses stable runner labels for the local package compatibility
  contract: `ubuntu-latest`, `windows-latest`, and `macos-15` across Python
  3.10-3.14.
- English and Chinese remaining-work plans are structurally paired and both
  separate local completion criteria from external GitHub/PyPI verification.
- Packaged schemas and skill reference schemas have matching filenames and
  current file contents.
- The bundled generic adapter and packaged generic template had a duplicate
  `require_residual_risk_report` key in `large_merge`; this round removes the
  duplicate while preserving behavior.
- Adapter/config JSON loading now rejects duplicate object keys through both
  `validate-config` and `validate-schema --schema gate-config`.
- Documentation parity tests now check both English-to-Chinese and
  Chinese-to-English Markdown counterparts under `docs/`.
- Local development documentation now uses the repository `.venv` path, which
  avoids PEP 668 failures from externally managed global Python installs.
- Remote GitHub Actions for commit `1c47d51` now match the local `.venv`
  validation surface: CI run `28143859766` passed and Security run
  `28143859790` passed for push-triggered jobs. The Security
  `dependency-review` job was skipped because it only runs on pull requests.
- No Release workflow run was present for `1c47d51`; that is expected for a
  normal branch push because Release only runs for `v*` tags or manual
  `workflow_dispatch`.

## Validation Commands

Preferred full local validation when time and environment allow:

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
python -m pytest -q --cov=review_fix_loop --cov-branch --cov-report=term-missing
python -m ruff check src tests
python -m mypy src/review_fix_loop
python -m bandit -r src/review_fix_loop
python -m pip_audit
python -m build
python -m twine check dist/*
git diff --check
review-fix-loop validate-config --repo . --config adapters/generic/gates.json --no-local-override
review-fix-loop snapshot --repo . --config adapters/generic/gates.json --mode normal_loop --pass 1 --write-run-record --cache-dir .review-fix-loop
review-fix-loop gate --repo . --config adapters/generic/gates.json --snapshot .review-fix-loop/runs/<run-id>/snapshot.json --ci-mode --no-local-override
```

For schema and workflow drift checks, run:

```bash
python -m pytest tests/test_review_loop_contract.py -q
python -m pytest tests/test_gate_config.py -q
```

## Schema Sync Points

- `src/review_fix_loop/schemas/gate-config.schema.json`
- `src/review_fix_loop/schemas/snapshot.schema.json`
- `src/review_fix_loop/schemas/run-record.schema.json`
- `src/review_fix_loop/schemas/diagnostic.schema.json`
- `skills/review-fix-loop-core/references/gate-config.schema.json`
- `skills/review-fix-loop-core/references/snapshot.schema.json`
- `skills/review-fix-loop-core/references/run-record.schema.json`
- `skills/review-fix-loop-core/references/diagnostic.schema.json`

## Known Risks

- Local generated directories (`.review-fix-loop/`, `dist/`, caches, coverage
  output) are present in the checkout and must remain untracked.
- GitHub branch protection and PyPI/TestPyPI trusted publisher setup cannot be
  proven from the local checkout.
- Direct editable installs against the active uv-managed global Python still
  fail with PEP 668 `externally-managed-environment`; use
  `.\.venv\Scripts\python.exe` for local validation.

## Backlog

1. Configure or verify GitHub branch protection and PyPI/TestPyPI trusted
   publisher setup outside the local checkout.
2. Consider a stricter heading-structure parity check for paired English and
   Chinese docs if future docs drift appears.

## Recent Validation

- `python -m pytest -q`: passed (`107 passed`) after the duplicate-key guard
  and bidirectional docs parity test rounds.
- `python -m pytest tests/test_review_loop_contract.py -q`: passed (`9 passed`)
  after bidirectional docs counterpart coverage was added.
- `.\.venv\Scripts\python.exe -m pip install -e ".[dev]"`: passed.
- `.\.venv\Scripts\python.exe -m pytest -q`: passed (`107 passed`).
- `.\.venv\Scripts\python.exe -m pytest -q --cov=review_fix_loop --cov-branch --cov-report=term-missing`: passed (`107 passed`, total coverage `82%`).
- `.\.venv\Scripts\python.exe -m ruff check src tests`: passed.
- `.\.venv\Scripts\python.exe -m mypy src/review_fix_loop`: passed.
- `.\.venv\Scripts\python.exe -m bandit -r src/review_fix_loop`: passed with no issues identified.
- `.\.venv\Scripts\python.exe -m pip_audit`: passed with no known vulnerabilities; the local package itself was skipped because it is not published on PyPI.
- `.\.venv\Scripts\python.exe -m build && .\.venv\Scripts\python.exe -m twine check dist/*`: passed.
- `.\.venv\Scripts\python.exe -m review_fix_loop.cli validate-config --repo . --config adapters/generic/gates.json --no-local-override`: passed.
- Fresh `snapshot --pass 1 --write-run-record` and `gate --ci-mode --no-local-override`
  passed for the `.venv` bootstrap documentation round.
- `git diff --check` and `git diff --cached --check`: passed.
- GitHub Actions API check for commit `1c47d51`: CI run `28143859766` passed,
  including lint, typecheck, artifact hygiene, build, and the full
  ubuntu/windows/macos Python 3.10-3.14 test matrix.
- GitHub Actions API check for commit `1c47d51`: Security run `28143859790`
  passed for CodeQL and python-security; dependency-review was skipped on the
  push event as configured.
- GitHub Actions API check for Release workflow: no run was present for
  `1c47d51`, matching the tag/manual trigger policy.
- GitHub Actions API check for commit `d9264ae`: Security passed; CI failed
  only on `test / macos-latest / Python 3.13`. Public logs were not available
  without GitHub authentication, but the public job page reported the
  `macos-latest` migration warning, so the next round pinned the macOS CI
  runner label to `macos-15`.
- GitHub Actions API check for commit `b3a20c1`: CI run `28144188537` passed
  and Security run `28144188557` passed after pinning the macOS runner label.

## Next Candidate

Verify branch protection and PyPI/TestPyPI trusted publisher configuration
outside the local checkout, or continue with a small docs parity hardening pass
if external settings access is not available.
