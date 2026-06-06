# Quickstart

This guide gets a local repository through one review/fix/re-review loop without any external service.

## Install

The example commands below assume you are running from this repository checkout, or from a target repository that already contains the referenced adapter file. For another repository, copy `adapters/project-template` first or pass an absolute config path.

```bash
python -m pip install -e ".[dev]"
```

The runtime package has no install-time dependencies. The `dev` extra is for tests and release checks.

## Initialize A Config

Create a repository-local adapter config from the bundled generic template:

```bash
review-fix-loop init --repo . --output review-fix-loop.gates.json
review-fix-loop validate-config --repo . --config review-fix-loop.gates.json
```

Use `review-fix-loop list-adapters --repo .` to see bundled and checkout-local adapters.

## Create Pass 1

Run a snapshot against the initialized adapter:

```bash
review-fix-loop snapshot \
  --repo . \
  --config review-fix-loop.gates.json \
  --mode normal_loop \
  --pass 1 \
  --write-run-record \
  --cache-dir .review-fix-loop
```

Expected output is JSON with fields such as:

- `snapshot_id`
- `snapshot_path`
- `run_record_path`
- `must_reload`
- `planned_gates`
- `entries`

When `--cache-dir` is omitted, run records are written under `.git/review-fix-loop/runs/...`. When `--cache-dir .review-fix-loop` is used, records are written under `.review-fix-loop/runs/...`; that directory is ignored and should not be committed.

## Run Gates

Use the `snapshot_path` from the pass 1 output:

```bash
review-fix-loop gate \
  --repo . \
  --config review-fix-loop.gates.json \
  --snapshot .review-fix-loop/runs/<run-id>/snapshot.json
```

The gate command executes only `planned_gates` from the snapshot. If the effective gate config or rule files changed after the snapshot was created, gate execution fails and asks for a fresh snapshot.

## Fix, Then Create Pass 2

After the agent or developer fixes findings, create a fresh pass 2 snapshot:

```bash
review-fix-loop snapshot \
  --repo . \
  --config review-fix-loop.gates.json \
  --mode normal_loop \
  --pass 2 \
  --previous-run-record .review-fix-loop/runs/<run-id>/run-record.json \
  --write-run-record \
  --cache-dir .review-fix-loop
```

Pass 2 and later require `--previous-run-record`. The output tells the agent which paths must be reloaded and which slices cannot reuse old context.

For a final verification pass, add `--final-pass` so gates marked `final_always` are planned and the snapshot identity records that final-pass status.

## Inspect And Validate Artifacts

```bash
review-fix-loop inspect --snapshot .review-fix-loop/runs/<run-id>/snapshot.json
review-fix-loop inspect --run-record .review-fix-loop/runs/<run-id>/run-record.json --format json
review-fix-loop validate-schema --schema snapshot --file .review-fix-loop/runs/<run-id>/snapshot.json
review-fix-loop doctor --repo . --config review-fix-loop.gates.json
```

Add `--include-repo-map` to `snapshot` when a large Python change benefits from a compact symbol map in the snapshot.

## Common Errors

`--pass > 1 requires --previous-run-record`

Run pass 2 with the previous run's `run-record.json`.

`effective config hash differs from snapshot config_hash; create a fresh snapshot`

The gate config changed after the snapshot. Create a new snapshot before running gates.

`rule file hashes differ from snapshot rule_hashes; create a fresh snapshot`

A configured rule file changed after the snapshot. Create a new snapshot before re-review.

`JSON file not found`

Check the `snapshot_path` or `run_record_path`; run IDs are timestamped under the selected run root.
