# Subagent Protocol

Subagents are optional and should only review independent slices.

Each subagent receives:

- current `snapshot_id`;
- selected scope;
- one slice or a disjoint file set;
- `must_reload` paths;
- project rules that affect that slice.

Subagents return findings with severity, evidence, file, line, and residual
risk. The main agent owns fixes, cross-slice synthesis, and final validation.

