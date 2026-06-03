---
name: review-fix-loop-project
description: >
  Use with review-fix-loop-core inside a consuming repository to apply
  project-specific rules, risk classification, and mechanical gates for
  review-fix-re-review workflows.
license: Apache-2.0
version: 0.1.0
compatibility:
  agents:
    - claude-code
    - codex
    - copilot
    - gemini-cli
  install_modes:
    - mount
    - copy
allowed-tools: "python git"
metadata:
  review_fix_loop:
    user-invocable: true
    auto-load: false
    disable-model-invocation: false
    domain: tool
    kb-paths: []
    ownership-scope: project-adapter-template
---

# Review Fix Loop Project Adapter

Use this adapter with `review-fix-loop-core`.

Read project-specific rules first, then run the core workflow. This adapter
points the runtime to `adapters/project-template/gates.json` and defines
project-specific risk and auto-fix boundaries.

## Required Context

Before running the loop, read the nearest applicable project rules:

- `AGENTS.md`, `CLAUDE.md`, or equivalent local agent rule files when present;
- touched-path subdirectory rule files when the target repository uses them;
- this adapter guidance;
- `adapters/project-template/gates.json`.

Do not fail only because a repository does not use these exact rule-file names.
Instead, use the nearest equivalent project policy file and report any missing
or inaccessible rule source.

## Runtime Config

Use:

```bash
review-fix-loop snapshot \
  --repo . \
  --config adapters/project-template/gates.json \
  --mode normal_loop \
  --pass 1 \
  --write-run-record
```

For larger branch reviews, use `large_merge` and pass the repository's intended
baseline when it differs from the adapter default.

Allowed auto-fix categories:

- trailing whitespace;
- generated index drift when the generator command is declared;
- generated skill metadata drift when the generator command is declared;
- documentation metadata drift when explicitly marked safe.

Requires confirmation:

- public API, response, DTO, or error-contract changes;
- database schema or data changes;
- payment, billing, refund, entitlement, queues, transactions, or data-source
  behavior;
- CI/CD, deployment, permissions, OAuth, MCP, or cloud config;
- dependency additions or upgrades;
- broad migrations or history rewrites.

Do not duplicate the full core workflow here.
