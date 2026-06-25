# 中文 FAQ

## 为什么必须 fresh snapshot？

因为 AI agent 可能把第一轮 diff 或 findings 带到第二轮继续使用。修复后真实工作区已经变化，复审必须从新的 live snapshot 开始。

## 会上传源码吗？

不会。CLI 在本地运行，不调用模型 API，也不依赖外部服务。

## run record 是否完全不含项目信息？

不是。run record 会保存路径、hash、gate ID、诊断摘要等元数据，用于下一轮判断上下文是否过期。它避免保存完整源码、完整 diff、secrets 和未脱敏命令输出。

## 它替代 CI 吗？

不替代。CI 仍然负责完整验证。Review Fix Loop 解决的是 agent 多轮修复后复审上下文是否新鲜的问题。

## large merge 怎么处理？

使用 `--mode large_merge`，并配置或传入 baseline，例如 `origin/main`。snapshot 会区分分支 diff 和本地 dirty worktree。

## 能和 Claude、Codex、Cursor、Aider 一起用吗？

可以。它不绑定模型或编辑器。关键是要求 agent 在每次复审前读取 fresh snapshot。

## 什么不应该提交？

不要提交 workspace-local run records，例如 `.review-fix-loop/`、build output、
caches 或 virtual environments。
