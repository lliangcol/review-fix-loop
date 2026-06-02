# Adapters

Adapters connect the generic review-loop contract to a specific repository. Start from `adapters/project-template` when creating one.

## What An Adapter Owns

An adapter should define:

- local rule files in `rule_files`;
- modes such as `normal_loop` and `large_merge`;
- slices and risk levels;
- gate commands as `argv` arrays;
- clear high-risk confirmation boundaries.

Keep adapters narrow. Do not place private paths, company names, secrets, or business-domain scripts in public examples.

## Gate Config Shape

The config file is JSON. A gate includes:

- `id`: stable gate identifier;
- `argv`: command array executed without shell expansion;
- `scope`: `staged`, `unstaged`, `untracked`, `merge_base_to_head`, or `all`;
- `filter_mode`: how diagnostics should be associated with changed paths;
- `fail_level`: minimum severity that fails the gate;
- `blocking`: whether failures block the loop;
- `parser`: `exit-code`, `git-diff-check`, `regex-lines`, or `json-diagnostics`.

Use `{baseline}`, `{merge_base}`, and `{snapshot_id}` tokens in `argv` when a gate needs snapshot-derived values.

## Authoring Flow

1. Copy `adapters/project-template` into your repository or into a local adapter directory.
2. Replace slices with your project ownership boundaries.
3. Replace gates with commands that already work locally.
4. Add rule files that describe review policy and risk boundaries.
5. Run pass 1 snapshot, fix, then pass 2 snapshot to confirm slice invalidation behaves as expected.

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
