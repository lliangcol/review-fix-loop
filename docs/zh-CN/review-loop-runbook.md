# Review Loop Runbook

本文说明 AI agent 如何在本地完成一轮完整的 review/fix/re-review。它不绑定具体仓库；项目规则、slices 和 gates 由所选 adapter 提供。

## 目标

只有满足以下条件时，循环才算完成：agent 已审查当前 live snapshot，修复 in-scope findings，修复后生成 fresh snapshot，复审 invalidated slices，运行 blocking gates，并报告 residual risks。

## 提示词模式

普通工作树可以使用：

```text
Review the current repository changes, fix in-scope findings with the smallest
useful change, create a fresh snapshot after fixes, and re-review invalidated
slices until no new in-scope findings remain and blocking gates pass.
```

分支或大合并场景需要带 baseline：

```text
Use large_merge mode with baseline origin/main. Separate committed branch diff,
staged changes, unstaged changes, and untracked files. Do not report local dirty
fixes as committed branch changes.
```

## 必读输入

审查前读取：

- core skill guidance，通常是 `skills/review-fix-loop-core/SKILL.md`；
- adapter guidance，例如 `adapters/project-template/SKILL.md`；
- adapter gate config，例如 `adapters/project-template/gates.json`；
- adapter 声明的仓库本地 rule files；
- touched paths 最近的子目录规则文件。

如果声明的规则文件缺失，报告限制，不要编造项目政策。

## Normal Loop

生成 pass 1：

```bash
review-fix-loop snapshot \
  --repo . \
  --config adapters/project-template/gates.json \
  --mode normal_loop \
  --pass 1 \
  --write-run-record
```

只审查 snapshot 要求加载的 paths 和 slices。只修复 in-scope findings。

运行 snapshot 选择的 gates：

```bash
review-fix-loop gate \
  --repo . \
  --config adapters/project-template/gates.json \
  --snapshot <snapshot-json>
```

基于上一轮 run record 生成 pass 2：

```bash
review-fix-loop snapshot \
  --repo . \
  --config adapters/project-template/gates.json \
  --mode normal_loop \
  --pass 2 \
  --previous-run-record <run-record-json> \
  --write-run-record
```

如果某一轮是最终验证快照，在运行 gates 前给 snapshot 命令增加
`--final-pass`。这样即使没有匹配路径变化，标记为 `final_always` 的 gates
也会进入 `planned_gates`。

根据 fresh snapshot 复审 invalidated slices。重复直到满足停止条件。

## Large Merge Loop

当 branch diff 较大，需要分开报告 committed branch diff、staged、unstaged 和 untracked 时，使用 `large_merge`：

```bash
review-fix-loop snapshot \
  --repo . \
  --config adapters/project-template/gates.json \
  --mode large_merge \
  --baseline origin/main \
  --pass 1 \
  --write-run-record
```

最终 large-merge 验证快照同样需要带 `--final-pass`，再运行 gates，确保
final-pass checks 被计划执行。

最终报告应区分：

- fully reviewed files or slices；
- mechanically verified files or slices；
- invariant-checked behavior；
- sampled areas；
- not-reviewed areas；
- residual risks。

## Gate 选择

只运行 snapshot `planned_gates` 中列出的 gates。如果 adapter config 或声明的 rule files 在 snapshot 后变化，先重新生成 fresh snapshot，再运行 gates。

对昂贵或领域专属 gates 使用 adapter `when_paths` selectors，避免普通文档或格式改动触发无关项目检查。

## 自动修复边界

通常可自动修复：

- configured gates 报告的 whitespace 和 formatting diagnostics；
- 已声明 generator command 的 generated indexes 或 metadata；
- adapter 明确标记为安全的 documentation metadata drift。

以下变更先停止并请求确认：public APIs、data、payments、entitlements、queues、transactions、data sources、CI/CD、deployment、permissions、cloud configuration、dependencies、broad migrations 或 history。

## 最终报告

报告：

```text
Pass:
Snapshot:
Must reload:
Reloaded slices:
Reused slices:
Reuse forbidden:
Findings:
Fixes:
Gates:
Stop decision:
Residual risks:
```

在 fresh re-review 没有新的 in-scope findings 且 blocking gates 已通过或被明确豁免前，不要声称成功。
