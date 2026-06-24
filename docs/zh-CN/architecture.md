# 架构

Review Fix Loop 是本地工作流契约。它不替 agent 做代码审查，而是告诉 agent
旧审查上下文何时已经失效，必须从 live Git worktree 重新取 snapshot。

## Snapshot

`snapshot` 命令读取当前 Git 仓库，并按 scope 区分 staged、unstaged、untracked
以及 `merge_base..HEAD` 分支 diff。entry 只包含路径、状态、有界 hash、binary
标记、slice 和 changed-line ranges，不包含完整源码或完整 diff。大文件 hash
只采样有界内容；symlink 按 link target hash，不跟随目标文件。

## Slice 失效

adapter 定义 `source`、`tests`、`docs` 等 slice。Pass 2 及之后，当前 snapshot
会和上一轮 run record 比较。slice hash、config hash、rule file hash 变化，或
上一轮在该 slice 有 fixes / 未解决 diagnostics，都禁止复用旧上下文。

输出中的 `must_reload`、`reloaded_slices`、`reused_slices` 和
`reuse_forbidden_slices` 是下一轮审查的边界。

## Planned Gates

gate 在 snapshot 阶段被选择，执行时只运行 `planned_gates`。执行前会确认当前
config 和 rule file hash 仍与 snapshot 一致，否则要求 fresh snapshot。
`filter_mode` 在 parser 之后应用，因此工具级失败不会被 changed-line filter
误删。

external gate 可以声明 trust metadata。builtin gate 默认 trusted。普通本地模式
保持兼容，会运行 untrusted external gate 并在结果中记录 warning；`gate
--ci-mode` 下，external gate 必须同时满足 `trusted=true` 和 `allow_in_ci=true`。

gate 默认串行执行。`parallel_safe=true` 可并行执行，`depends_on` 用于声明依赖。
run record 中结果顺序始终按 snapshot 的 planned gate 顺序写入。

## Mode 能力

mode id 由 adapter 声明，不再限于硬编码列表。内置模板仍提供 `normal_loop` 和
`large_merge`，也可以定义自定义 mode。

mode 可带 advisory 字段，如 `requires_merge_base`、`requires_final_pass`、
`requires_repo_map`、`requires_residual_risk_report`、`max_changed_files`、
`max_diff_bytes_per_slice`。这些字段会进入 config hash；除 snapshot、slice、
gate 契约外，大多由 agent/skill 解释执行。

## Locale

JSON key、schema 字段和 artifact path 保持英文。常见人类可读错误可通过
`--locale zh-CN` 或 `REVIEW_FIX_LOOP_LOCALE=zh-CN` 本地化。
