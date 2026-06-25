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

- Worktree started this round with many already staged source, test, and doc
  changes. They are treated as pre-existing user work.
- `pyproject.toml` currently declares `dependencies = []`, matching the
  zero runtime dependency requirement.
- CI, security, and release workflows exist and align with the implementation
  plan at a high level: split lint/type/test/build/artifact hygiene jobs,
  Bandit/pip-audit/CodeQL/Dependency Review, and tag or TestPyPI release flow.
- English and Chinese remaining-work plans are structurally paired and both
  separate local completion criteria from external GitHub/PyPI verification.
- Packaged schemas and skill reference schemas have matching filenames and
  current file contents.
- The bundled generic adapter and packaged generic template had a duplicate
  `require_residual_risk_report` key in `large_merge`; this round removes the
  duplicate while preserving behavior.

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

- Existing staged changes are broad and should be reviewed as their own batch
  before release claims are made.
- Local generated directories (`.review-fix-loop/`, `dist/`, caches, coverage
  output) are present in the checkout and must remain untracked.
- GitHub branch protection, workflow green status, and PyPI/TestPyPI trusted
  publisher setup cannot be proven from the local checkout.

## Backlog

1. Add an explicit duplicate-key guard for adapter JSON loading so future config
   duplicates fail fast instead of relying on review.
2. Add or strengthen docs parity checks for README and primary docs structure.
3. Run full security and release validation after the current staged source
   changes are understood and stabilized.

## Recent Validation

- `python -m pip install -e ".[dev]"`: failed because the active uv-managed
  Python reports `externally-managed-environment` (PEP 668). No
  `--break-system-packages` override was used.
- `git diff --check`: passed.
- `git diff --cached --check`: passed.
- `PYTHONPATH=src python -m review_fix_loop.cli validate-config --repo . --config adapters/generic/gates.json --no-local-override`: passed.
- `python -m pytest tests/test_review_loop_contract.py -q`: initially failed
  because this new English status file needed a `docs/zh-CN/` counterpart;
  passed after adding the counterpart (`9 passed`).
- `python -m pytest tests/test_gate_config.py::test_all_bundled_gate_configs_validate_against_schema -q`: not run because that test id does not exist.
- `python -m pytest tests/test_gate_config.py::test_generic_adapter_matches_packaged_template tests/test_gate_config.py::test_packaged_adapter_configs_validate -q`: passed (`2 passed`).
- `python -m pytest tests/test_gate_config.py -q`: failed with one pre-existing
  live-worktree failure in `test_diagnostic_schema_rejects_invalid_severity`.
  The current validator reports `field severity must be one of [...]`, while
  the test still expects jsonschema-style `"'fatal' is not one of"` text.
- `python -m ruff check ...`: not run because `ruff` is not installed in the
  active Python environment.
- `python -m mypy src/review_fix_loop`: not run because `mypy` is not installed
  in the active Python environment.

## Next Candidate

Add a focused duplicate-key regression test for bundled adapter JSON files and
the `init` template source, using only the standard library.
