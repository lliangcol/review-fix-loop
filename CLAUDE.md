# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Review Fix Loop is a local-first CLI that governs AI review/fix/re-review loops. It does **not** review code itself, call any model API, or talk to a hosted service. Its single job is to give an AI agent a reliable contract for knowing when prior review context has gone stale: after fixes, the next pass must reload changed slices from a fresh live snapshot of the Git worktree. The core package has **zero install-time dependencies** (`jsonschema` is dev-only) and must stay that way.

## Commands

```bash
python -m pip install -e ".[dev]"   # install with pytest, jsonschema, build, twine
python -m pytest -q                  # full test suite
python -m pytest tests/test_snapshot.py -q          # one file
python -m pytest tests/test_snapshot.py::test_name   # one test
python -m build && python -m twine check dist/*      # build + metadata check (CI does this)
```

There is no separate lint step; CI (`.github/workflows/ci.yml`) runs pytest, build, a wheel-install smoke test, and asserts no generated artifacts (`__pycache__`, `dist/`, `.egg-info`, etc.) are tracked. CI matrix is Python 3.10–3.14 on ubuntu/windows/macos, so keep code cross-platform (this dev box is Windows) and within 3.10 syntax.

The CLI entry point is `review-fix-loop` → `review_fix_loop.cli:main`. Subcommands: `snapshot`, `gate`, `init`, `list-adapters`, `validate-config`, `validate-schema`, `doctor`, `inspect`. See `README.md` for the end-to-end quickstart.

## Architecture

The whole package lives in `src/review_fix_loop/`. `cli.py` is the orchestration layer; everything it calls is a focused module:

- **`git_snapshot.py`** — `collect_scopes` reads the live repo and bins changes into scopes (`staged`, `unstaged`, `untracked`, `merge_base_to_head`). Entries carry paths, status, **bounded** content hashes (large files sampled head+tail; symlinks hashed by link target), binary markers, and changed-line ranges — never full source or full diffs. `compute_scope_hashes` produces the per-scope fingerprints used for staleness checks.
- **`slices.py`** — assigns each entry to an adapter-defined slice (`source`, `tests`, `docs`, …) via glob paths, then computes per-slice hashes.
- **`cli.py:compute_freshness`** — the core contract. On pass ≥ 2 it diffs the current snapshot against the previous run record and marks a slice `reuse_forbidden` when its hash changed, the config/rule hashes changed, or the previous pass had fixes or unresolved diagnostics in that slice. Output fields: `must_reload`, `reloaded_slices`, `reused_slices`, `reuse_forbidden_slices`.
- **`gates.py`** — `plan_gates` selects which gates apply at snapshot time (by scope, `when_paths`, `modes`, `final_always`); `run_planned_gates` executes them. Gate execution re-verifies that the live config/rule hashes still match the snapshot and **refuses to run if they drifted** — forcing a fresh snapshot. `filter_mode` (reviewdog-style `added`/`diff_context`/`file`/`nofilter`) is applied *after* parsing so tool-level failures are never silently dropped. `argv[0]` of `__builtin__:<name>` (e.g. `__builtin__:untracked-whitespace`, `__builtin__:policy`) invokes in-process gates instead of a subprocess.
- **`diagnostics.py`** — parsers for gate output: `git-diff-check`, `regex-lines`, `json-diagnostics`, `rdjson`, `sarif`, `checkstyle`, `exit-code`.
- **`config.py`** — `load_effective_config` loads the adapter gate config, deep-merges an optional repo-local `.review-fix-loop.local.json`, normalizes/hashes declared `rule_files`, and runs `validate_config`. The valid-value sets (`VALID_SCOPES`, `VALID_MODES`, `VALID_PARSERS`, etc.) live here and are the source of truth for config validation.
- **`run_record.py`** — when `--write-run-record` is set, writes `snapshot.json`, `run-record.json`, `gates.json`, `summary.md` under the cache dir (default `.review-fix-loop/runs/<run-id>/`). Run records are the hand-off to the next pass.
- **`utils.py`** — hashing (`sha256_json`/`sha256_text`), glob matching, and **redaction** (`redact_text`/`redact_data`) applied to gate argv, summaries, diagnostics, and the persisted config copy before they hit disk.
- **`assets.py` / `schema_validation.py`** — locate bundled adapter templates and JSON schemas. Both `templates/*.json` and `schemas/*.json` are declared as `package-data` in `pyproject.toml` so `init` and `validate-schema` work from an installed wheel.

Key invariant: a snapshot is identified by `snapshot_id = sha256_json(snapshot_seed)`. Anything that changes the effective config, rule files, scope contents, or planned gates changes the id — and a changed id is what invalidates reuse downstream.

## Adapters

Adapters are JSON gate configs, not code. `adapters/generic/gates.json` is the bundled default (also packaged as `templates/generic.gates.json`); `adapters/project-template/` and `examples/adapters/*` show project-specific variants. A config declares `modes` (`normal_loop`, `large_merge`), `slices` (id + glob `paths` + `risk`), `gates`, and optional `rule_files`. When changing config shape, update **three** things together: the validation logic in `config.py`, the JSON schema in `src/review_fix_loop/schemas/gate-config.schema.json`, and the bundled adapter examples. The four schemas (`gate-config`, `snapshot`, `run-record`, `diagnostic`) are duplicated under `skills/review-fix-loop-core/references/` for skill packaging — keep them in sync with `src/.../schemas/`.

## The skill

`skills/review-fix-loop-core/` packages this tool as an agent skill. `SKILL.md` documents the loop protocol an agent should follow; `scripts/snapshot.py` and `scripts/gate.py` are thin shims that prepend `src/` to `sys.path` and call `review_fix_loop.cli:main`. The behavioral contract (fresh-snapshot rule, stop conditions, large-merge coverage reporting) lives in `SKILL.md` and `docs/review-loop-runbook.md`.

## Docs

`docs/architecture.md` is the authoritative high-level description; `docs/` also holds the quickstart, adapter guide, FAQ, runbook, and a `zh-CN/` translation set (README and docs are bilingual — update both when changing user-facing behavior).
