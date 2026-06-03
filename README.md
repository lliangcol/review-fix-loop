# Review Fix Loop

> Local-first fresh re-review contract for AI agents.

[![CI](https://github.com/lliangcol/review-fix-loop/actions/workflows/ci.yml/badge.svg)](https://github.com/lliangcol/review-fix-loop/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10--3.14-blue)
[![License](https://img.shields.io/badge/license-Apache--2.0-green)](LICENSE)

Review Fix Loop prevents stale-diff reuse in AI review/fix/re-review loops. After an AI agent fixes findings, the next review pass must start from a fresh live snapshot of the Git worktree, selected gates, and durable redacted run records.

## Why It Exists

AI coding agents often work in loops:

1. review the current diff;
2. fix findings;
3. re-review to decide whether the work is done.

The failure mode is subtle: pass 2 can accidentally reuse pass 1 diff text or pass 1 findings after files have changed. That makes the re-review stale. Review Fix Loop turns the loop into a local contract: every pass reloads changed slices from the live repository before the agent reasons again.

## What Makes It Different

| Tool type | Primary job | Fresh snapshot after fixes | Local-first | Boundary |
| --- | --- | --- | --- | --- |
| Hosted PR bot | Review pull requests in a hosted service | Depends on the bot workflow | Usually no | External service, account, and repository permissions |
| reviewdog / pre-commit | Run diagnostics and hooks | Not the main contract | Yes | Great for checks, not a re-review loop protocol |
| Review Fix Loop | Govern AI review/fix/re-review loops | Yes | Yes | No hosted bot, no model API, no external service |

## 5-Minute Quickstart

Run these commands from this repository checkout, or from a target repository that already contains the referenced adapter file. For another repository, copy `adapters/project-template` first or pass an absolute config path.

```bash
python -m pip install -e ".[dev]"
```

Create a pass 1 snapshot and write local run records:

```bash
review-fix-loop snapshot \
  --repo . \
  --config adapters/generic/gates.json \
  --mode normal_loop \
  --pass 1 \
  --write-run-record \
  --cache-dir .review-fix-loop
```

Run gates selected by that snapshot:

```bash
review-fix-loop gate \
  --repo . \
  --config adapters/generic/gates.json \
  --snapshot .review-fix-loop/runs/<run-id>/snapshot.json
```

After fixing code, create pass 2 from the previous run record:

```bash
review-fix-loop snapshot \
  --repo . \
  --config adapters/generic/gates.json \
  --mode normal_loop \
  --pass 2 \
  --previous-run-record .review-fix-loop/runs/<run-id>/run-record.json \
  --write-run-record \
  --cache-dir .review-fix-loop
```

Reusing pass 1 diff text or pass 1 findings without this fresh snapshot is an invalid workflow.

## Who It Is For

- AI coding agent power users working with Claude, Codex, Cursor, Aider, or similar local workflows.
- Privacy-sensitive teams that want review-loop governance without uploading source to a hosted reviewer.
- Workflow-governance maintainers who need repeatable rules for snapshot, gate, and run-record handling.
- Adapter authors who want project-specific gates without rewriting the core loop contract.

## How It Works

```text
live Git worktree -> snapshot -> agent review -> fixes -> gates -> fresh snapshot -> re-review
```

Snapshots separate staged, unstaged, untracked, and branch-diff scopes. Slices are invalidated when their hashes, rule files, or gate config change. Run records keep durable metadata while avoiding full source text, full diffs, secrets, and unredacted command output.

## Current Boundaries

Review Fix Loop is not a hosted PR bot, not a GitHub App, not a hook framework, and not a model service. It does not require GitHub App credentials, cloud sandboxes, model API keys, or external services.

## Documentation

- [Quickstart](docs/quickstart.md)
- [Architecture](docs/architecture.md)
- [Adapters](docs/adapters.md)
- [Comparisons](docs/comparisons.md)
- [Contracts](docs/contracts.md)
- [Review loop runbook](docs/review-loop-runbook.md)
- [Template repository guide](docs/template-repository.md)
- [FAQ](docs/faq.md)
- [简体中文](README.zh-CN.md)

## Development

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
python -m build
python -m twine check dist/*
```

The runtime package has no install-time dependencies. Development extras are only for tests and release checks.
