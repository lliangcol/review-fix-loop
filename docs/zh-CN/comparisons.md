# Comparisons

Review Fix Loop 不是代码审查模型、不是 hosted PR bot，也不是 CI 替代品。它的
职责更窄：在 agent 修复问题后，用 fresh live snapshot 判断哪些上下文已经
过期，哪些 gate 应该运行。

## 何时使用 Review Fix Loop

当 AI agent 需要证明第 N 轮审查基于第 N 轮 live repository state，而不是
第 N-1 轮上下文时，使用 Review Fix Loop。

它和常见工具的边界是：

- CI 负责仓库级验证、发布门禁和远端环境信号；Review Fix Loop 负责本地
  review/fix/re-review 的上下文新鲜度。
- pre-commit 管理固定 hook；Review Fix Loop 记录 snapshot、slice hash、
  planned gates 和 run record。
- reviewdog 负责把工具输出映射到代码评论；Review Fix Loop 可以解析
  RDJSON、SARIF、Checkstyle 等输出，但不发布 PR 评论。
- AI agent 负责理解、审查和修复代码；Review Fix Loop 只提供 fresh snapshot、
  reuse forbidden slices、planned gates 和 redacted run record 契约。

## 何时不使用

不要把它当成 hosted PR bot、CI 替代品、模型提供方或通用代码审查平台。
