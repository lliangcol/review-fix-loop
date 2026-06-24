# Contracts

本页定义 agent 使用 Review Fix Loop 时必须遵守的核心契约。

## Fresh Snapshot

修复后必须重新运行 live snapshot。复审不能继续依赖上一轮 diff、上一轮
findings 或记忆中的文件片段。

## Slice Reload

如果 snapshot 把某个 slice 标记进 `reuse_forbidden_slices`，agent 必须重新读取
该 slice 的当前文件内容，再继续审查。

## Gate Execution

agent 只能运行 snapshot 的 `planned_gates`。如果 config 或 rule files 在
snapshot 后变化，必须先重新 snapshot。CI 中应使用 `gate --ci-mode`，确保
untrusted external gate 不会被意外执行。

## Redaction

run record 可以保存路径、hash、gate id、diagnostic summary 和 stop decision，
但不能保存完整源码、完整 diff、secret 或未脱敏命令输出。

## Stop Decision

只有 fresh re-review 不再发现 in-scope 新问题、blocking gates 通过、residual
risk 已明确记录时，才能停止。
