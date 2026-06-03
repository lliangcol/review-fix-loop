# Adapters

Adapters connect the generic review-loop contract to a specific repository. Start from `adapters/project-template` when creating one.

## What An Adapter Owns

An adapter should define:

- local rule files in `rule_files`;
- modes such as `normal_loop` and `large_merge`;
- slices and risk levels;
- gate commands as `argv` arrays;
- `when_paths` selectors for gates that should run only for specific changed
  paths;
- clear high-risk confirmation boundaries.

Keep adapters narrow. Do not place private paths, company names, secrets, or business-domain scripts in public examples.

## Public And Private Boundaries

Open-source examples should stay generic. If a working adapter comes from a
private repository, extract the reusable pattern but remove:

- private repository names, paths, company names, and internal project labels;
- commands that rely on private scripts or private services;
- business-domain rules that expose customer, payment, entitlement, or
  production details;
- captured command output, logs, tokens, credentials, certificates, and
  environment-specific configuration.

Keep private adapters in the consuming repository or in a private distribution
channel. Publish only the generalized adapter structure, risk categories, and
gate-planning techniques.

## Gate Config Shape

The config file is JSON. A gate includes:

- `id`: stable gate identifier;
- `argv`: command array executed without shell expansion;
- `scope`: `staged`, `unstaged`, `untracked`, `merge_base_to_head`, or `all`;
- `when_paths`: optional path globs; when present, the gate is planned only if
  changed paths in the gate scope match one of these globs;
- `modes`: optional list that restricts a gate to `normal_loop` or
  `large_merge`;
- `filter_mode`: how diagnostics should be associated with changed paths;
- `fail_level`: minimum severity that fails the gate;
- `blocking`: whether failures block the loop;
- `timeout_seconds`: maximum local runtime for the gate;
- `final_always`: whether a gate should run on a final-pass snapshot even when
  no matching path changed;
- `parser`: `exit-code`, `git-diff-check`, `regex-lines`, or `json-diagnostics`.

Use `{baseline}`, `{merge_base}`, and `{snapshot_id}` tokens in `argv` when a gate needs snapshot-derived values.

## Authoring Flow

1. Copy `adapters/project-template` into your repository or into a local adapter directory.
2. Replace slices with your project ownership boundaries.
3. Replace gates with commands that already work locally.
4. Add rule files that describe review policy and risk boundaries.
5. Use `when_paths` for expensive or domain-specific gates so they run only
   when relevant files changed.
6. Run pass 1 snapshot, fix, then pass 2 snapshot to confirm slice invalidation behaves as expected.

## Confirmation Boundaries

Adapters should state what an agent may fix automatically and what must stop
for human confirmation. Common confirmation boundaries include:

- public API, response, DTO, or error-contract changes;
- database schema or data changes;
- payment, billing, refund, entitlement, queue, transaction, or data-source
  behavior;
- CI/CD, deployment, permissions, OAuth, MCP, or cloud configuration;
- dependency additions or upgrades;
- broad migrations, destructive operations, or history rewrites.

## Example

```bash
review-fix-loop snapshot \
  --repo . \
  --config adapters/project-template/gates.json \
  --mode normal_loop \
  --pass 1 \
  --write-run-record
```

By default, run records go under `.git/review-fix-loop/runs/...`. Use `--cache-dir .review-fix-loop` only when you want visible workspace-local records, and keep that directory ignored.
