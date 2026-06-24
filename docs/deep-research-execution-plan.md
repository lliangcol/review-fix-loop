# Deep Research Execution Plan

This plan turns `D:/Documents/GitHub/review-fix-loop/deep-research-report.md`
into an execution sequence that can be reviewed, fixed, and re-reviewed with
fresh live snapshots. The research report is broader than one safe initial
batch, so this document records the local work promoted into this branch after
the quality baseline was established, and separates it from external release
verification.

## Scope

The current batch must preserve the core product contract:

- no install-time runtime dependencies;
- no model API, hosted service, or network dependency in the core package;
- snapshot and gate artifacts must stay redacted and must not store full source
  text or full diffs;
- fixes must be validated from a fresh worktree snapshot after edits.

The current batch implements the high-value changes that are small enough to
ship and verify together:

1. align the development toolchain with commands required by README, CI, and
   security workflows;
2. split CI into lint, typecheck, matrix test, build, and artifact-hygiene jobs
   while publishing coverage and JUnit artifacts;
3. make text run-record outputs use the same atomic write strategy as JSON;
4. make local config override provenance visible in CLI outputs and persisted
   records, and add a CI-safe switch to disable local overrides;
5. cap captured external gate output before persisted summaries are built, so
   very large stdout/stderr cannot be retained as unbounded text;
6. batch snapshot diff/blob probing, add service/domain boundaries, add gate
   trust and parallel-execution metadata, support custom adapter mode ids, add
   initial locale support, and add release automation;
7. document external verification that cannot be proven from a local checkout.

## Current Batch Work Items

### 1. Development Toolchain And CI Evidence

Update `pyproject.toml` so `python -m pip install -e ".[dev]"` installs the
tools used by the documented development and CI paths:

- `pytest-cov` for coverage reports;
- `build` and `twine` for package checks;
- `pytest-xdist`, `ruff`, `mypy`, `bandit[toml]`, and `pip-audit` for local,
  CI, and security workflow validation.

Update `.github/workflows/ci.yml` to add required lint and typecheck jobs,
keep the existing pytest matrix and build smoke test, and upload coverage XML
and JUnit XML artifacts. Add `.github/workflows/security.yml` for Bandit,
pip-audit, CodeQL, and Dependency Review.

Acceptance:

- `python -m pytest -q` passes;
- `python -m pytest -q --cov=review_fix_loop --cov-branch --cov-report=term-missing`
  passes locally;
- `python -m ruff check src tests` passes;
- `python -m mypy src/review_fix_loop` passes;
- `python -m bandit -r src/review_fix_loop` passes;
- `python -m pip_audit` reports no known vulnerabilities;
- CI still builds and smoke-tests the wheel;
- CI uploads coverage/JUnit artifacts for each matrix entry.

### 2. Atomic Text Run Outputs

Extend `src/review_fix_loop/run_record.py` with `write_text_atomic()` and use it
for `summary.md`. JSON outputs already use sibling temp files and `os.replace`;
the Markdown summary should follow the same persistence model.

Acceptance:

- existing run-record tests still pass;
- a new regression test proves `summary.md` is written and no sibling temp file
  remains after success.

### 3. Config Override Provenance

Make `.review-fix-loop.local.json` observable without changing default
behavior:

- `load_effective_config()` should return config source metadata in addition to
  the effective config hash and rule hashes;
- `snapshot`, `run-record`, `doctor`, and `validate-config` outputs should show
  whether the local override was applied and where it came from;
- a new `--no-local-override` flag should let CI and release workflows force the
  adapter config to be used without local overrides.

Acceptance:

- default behavior still applies `.review-fix-loop.local.json` when present;
- `--no-local-override` prevents local override application;
- schema validation allows the new snapshot/run-record metadata fields;
- tests cover both applied and disabled override paths.

### 4. Bounded External Gate Output

Replace unbounded decoded stdout/stderr summary construction with a bounded
capture helper. The parser contract stays the same. Gate execution remains
serial by default, and only gates explicitly marked `parallel_safe` can run
concurrently.

Acceptance:

- existing gate parser tests still pass;
- large UTF-8 output remains valid after truncation;
- gate result records include `stdout_truncated`, `stderr_truncated`,
  `stdout_bytes`, and `stderr_bytes`;
- redaction still applies after bounded capture.

## Promoted Work Packages

The following items were originally later-phase candidates and are now included
in this branch:

1. CI split into separate lint, typecheck, test, build, and hygiene jobs;
2. scope-level batched Git diff, HEAD blob lookup, and binary status probing;
3. service/domain boundaries for snapshot freshness and gate execution;
4. external gate trust metadata plus CI refusal for untrusted commands;
5. release automation with PyPI Trusted Publishing;
6. Chinese documentation parity and initial CLI locale support;
7. adapter-defined mode ids with advisory capability fields.

The implementation-ready breakdown and external verification list are maintained in
[Remaining Work Implementation Plan](remaining-work-implementation-plan.md).

## Review-Fix-Re-Review Protocol

This plan is complete only after:

1. the plan has been reviewed against current source, tests, schemas, and docs;
2. any plan defects found during review have been fixed;
3. implementation follows the reviewed current-batch scope;
4. tests and local review-fix-loop snapshot/gate passes run against the live
   edited worktree;
5. a fresh post-fix snapshot and re-review find no new in-scope issues.

## Validation Commands

Run these commands from the repository root:

```bash
python -m pytest -q
python -m pytest -q --cov=review_fix_loop --cov-branch --cov-report=term-missing
python -m ruff check src tests
python -m mypy src/review_fix_loop
python -m bandit -r src/review_fix_loop
python -m pip_audit
python -m build
python -m twine check dist/*
review-fix-loop snapshot --repo . --config adapters/generic/gates.json --mode normal_loop --pass 1 --write-run-record --cache-dir .review-fix-loop
review-fix-loop gate --repo . --config adapters/generic/gates.json --snapshot <snapshot_path> --ci-mode
```

After implementation fixes, create a pass 2 snapshot with
`--previous-run-record <run-record.json>` and re-review only the slices that the
fresh snapshot marks as changed or reuse-forbidden.
