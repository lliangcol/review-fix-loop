---
name: review-fix-loop-project
description: >
  Use with review-fix-loop-core inside a consuming repository to apply
  project-specific rules, risk classification, and mechanical gates for
  review-fix-re-review workflows.
---

# Review Fix Loop Project Adapter

Use this adapter with `review-fix-loop-core`.

Read project-specific rules first, then run the core workflow. This adapter
points the runtime to `adapters/project-template/gates.json` and defines
project-specific risk and auto-fix boundaries.

Allowed auto-fix categories:

- trailing whitespace;
- generated index drift when the generator command is declared;
- generated skill metadata drift when the generator command is declared;
- documentation metadata drift when explicitly marked safe.

Requires confirmation:

- public API changes;
- database or data changes;
- payment, billing, entitlement, queues, transactions;
- CI/CD, deployment, permissions, OAuth, MCP, or cloud config;
- dependency additions or upgrades;
- broad migrations.

Do not duplicate the full core workflow here.

