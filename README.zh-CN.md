# Review Fix Loop

> 面向 AI agents 的本地优先 fresh re-review 工作流合同。

[English](README.md) / 简体中文

Review Fix Loop 不是另一个 PR 机器人，而是让 AI 多轮复审在每次修复后都重新对齐真实代码状态的本地优先工作流合同。它的核心目标是防止 agent 在 pass 2 复审时继续使用 pass 1 的旧 diff 或旧 findings。

## 为什么需要它

AI 编程工具常见工作流是：

1. 先审查当前改动；
2. 根据 findings 修改代码；
3. 再复审一次确认是否收敛。

问题在第 3 步：如果 agent 沿用第一轮上下文里的旧 diff，复审结果就会偏离真实工作区。Review Fix Loop 要求每一轮修复后重新生成 live snapshot，再根据当前 snapshot 选择 gates 和需要重载的 slices。

## 快速开始

以下命令假设你在本仓库 checkout 中运行，或目标仓库已经包含对应 adapter 文件。接入其他仓库时，请先复制 `adapters/project-template`，或传入 adapter 配置的绝对路径。

```bash
python -m pip install -e ".[dev]"
```

初始化目标仓库的默认 adapter：

```bash
review-fix-loop init --repo . --output review-fix-loop.gates.json
review-fix-loop validate-config --repo . --config review-fix-loop.gates.json
```

生成 pass 1 snapshot：

```bash
review-fix-loop snapshot \
  --repo . \
  --config review-fix-loop.gates.json \
  --mode normal_loop \
  --pass 1 \
  --write-run-record \
  --cache-dir .review-fix-loop
```

执行当前 snapshot 选择的 gates：

```bash
review-fix-loop gate \
  --repo . \
  --config review-fix-loop.gates.json \
  --snapshot .review-fix-loop/runs/<run-id>/snapshot.json
```

修复后生成 pass 2 fresh snapshot：

```bash
review-fix-loop snapshot \
  --repo . \
  --config review-fix-loop.gates.json \
  --mode normal_loop \
  --pass 2 \
  --previous-run-record .review-fix-loop/runs/<run-id>/run-record.json \
  --write-run-record \
  --cache-dir .review-fix-loop
```

`.review-fix-loop/` 是本地 run record 目录，不应提交到仓库。
最终确认轮需要加 `--final-pass`，这样 `final_always` gates 会进入
`planned_gates`，并写入不同的 snapshot identity。

## 适用人群

- 经常使用 Claude、Codex、Cursor、Aider 等 AI 编程工具做 review/fix/re-review 的开发者。
- 希望在本地保留代码和运行记录的团队。
- 维护 agent 工作流规范、gate 规则或 adapter 模板的人。

## 当前边界

Review Fix Loop 不托管服务、不上传源码、不替代 CI、不需要模型 API key，也不是 GitHub App。它提供的是本地 snapshot、slice invalidation、planned gates 和 redacted run records 的工作流合同。

## 文档

- [中文快速开始](docs/zh-CN/quickstart.md)
- [架构](docs/zh-CN/architecture.md)
- [Adapter 指南](docs/zh-CN/adapters.md)
- [对比说明](docs/zh-CN/comparisons.md)
- [合同说明](docs/zh-CN/contracts.md)
- [深度研究执行计划](docs/zh-CN/deep-research-execution-plan.md)
- [未完成任务完整实现方案](docs/zh-CN/remaining-work-implementation-plan.md)
- [Review loop 运行手册](docs/zh-CN/review-loop-runbook.md)
- [模板仓库指南](docs/zh-CN/template-repository.md)
- [中文 FAQ](docs/zh-CN/faq.md)
- [English](README.md)

## 开发

```bash
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pytest -q --cov=review_fix_loop --cov-branch --cov-report=term-missing
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m mypy src/review_fix_loop
.\.venv\Scripts\python.exe -m bandit -r src/review_fix_loop
.\.venv\Scripts\python.exe -m pip_audit
.\.venv\Scripts\python.exe -m build
.\.venv\Scripts\python.exe -m twine check dist/*
```

运行时包保持零安装依赖；`dev` extra 只用于测试、质量检查、安全检查和发布检查。
本地开发请使用隔离虚拟环境；uv-managed 或其他 externally managed Python 可能会因
PEP 668 拒绝直接 editable install。
