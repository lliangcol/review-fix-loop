# Comparisons

Review Fix Loop 不是代码审查模型、不是 hosted PR bot，也不是 CI 替代品。它的
职责更窄：在 agent 修复问题后，用 fresh live snapshot 判断哪些上下文已经
过期，哪些 gate 应该运行。

## 与 CI

CI 负责仓库级验证、发布门禁和远端环境信号。Review Fix Loop 负责本地
review/fix/re-review 的上下文新鲜度，帮助 agent 避免复用旧 diff。

## 与 pre-commit

pre-commit 管理固定 hook。Review Fix Loop 记录 snapshot、slice hash、
planned gates 和 run record，让下一轮 agent 知道必须重新读取哪些 slice。

## 与 reviewdog

reviewdog 负责把工具输出映射到代码评论。Review Fix Loop 可以解析类似
RDJSON、SARIF、Checkstyle 等输出，并在 parser 之后应用 changed-line filter，
但它不发布 PR 评论。

## 与 AI Agent

AI agent 负责理解、审查和修复代码。Review Fix Loop 只提供本地契约：
fresh snapshot、reuse forbidden slices、planned gates、redacted run record。
