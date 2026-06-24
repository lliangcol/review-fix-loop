# 未完成任务实现方案

本文替代之前的多 PR 路线图，改为当前分支可执行范围。复审发现，旧版本把
GitHub required checks、security workflow green、TestPyPI dry run 等远端仓库
管理动作也写成本地验收条件；这些不能在本地 checkout 中证明，所以修正版把本地
实现与外部验证分开。

## 不变量

本分支必须保持：

- runtime package 零安装期依赖；
- CI、安全、发布和文档工具只放在 `.[dev]` 或 GitHub Actions setup；
- adapter config 仍是 JSON 数据；
- snapshot 与 run record 只保留有界 metadata，不保存完整源码或完整 diff；
- schema 变更同步 `src/review_fix_loop/schemas/` 与
  `skills/review-fix-loop-core/references/`；
- 英文和中文用户文档结构配对。

## 已实施工作包

### CI Baselines

CI 拆为 `lint`、`typecheck`、matrix `test`、`build`、`artifact-hygiene`。
test job 使用 `if: always()` 上传 JUnit 和 coverage XML；build job 构建
distribution、运行 `twine check`，并安装 wheel 做 CLI smoke test。

### Security Workflow

新增 `.github/workflows/security.yml`，包含 Bandit、pip-audit、CodeQL 和
Dependency Review。安全工具保持 dev-only。

### Snapshot 性能批处理

新增 `parse_unified_diff_by_path` 与 `diff_line_ranges_for_scope`，按 scope
批量解析 changed-line ranges。HEAD blob lookup 与 blob binary sampling 也走批处理，
同时保留逐文件 fallback。

### CLI、Service、Domain 边界

`cli.py` 保持 parser/dispatch 职责，freshness 与 fresh-tree 规则迁入
`services/snapshot_service.py`。新增 `domain/types.py` 和 gate service wrapper。

### External Gate Trust Boundary

gate config 增加 `trusted`、`allow_in_ci`、`writes_worktree`、
`requires_network`、`trust_reason`。builtin gate 默认 trusted。普通本地模式兼容运行
untrusted external gate 并记录 warning；`gate --ci-mode` 会拒绝未同时声明
`trusted=true` 与 `allow_in_ci=true` 的 external gate。

### Parallel-Safe Gate 执行

新增 `parallel_safe`、`reads_worktree_only`、`depends_on`。默认仍串行；连续 ready
且标记 `parallel_safe` 的 gates 使用 thread pool 并行。结果顺序按 snapshot 的
`planned_gates` 写入。

### Adapter Mode Capability 模型

允许 adapter config 声明自定义 mode id。模板仍保留 `normal_loop` 与
`large_merge`，并校验 `requires_merge_base`、`requires_repo_map`、
`max_changed_files`、`max_diff_bytes_per_slice` 等 advisory capability 字段。

### 文档对齐与 Locale

新增 `--locale` / `REVIEW_FIX_LOOP_LOCALE`，本地化常见人类可读错误，JSON key
保持英文。补齐主要中文文档，并加入 docs parity test。

### Release Automation

新增 `.github/workflows/release.yml`，用于 tag build、wheel smoke test 和 PyPI
Trusted Publishing。release checklist 写明 PyPI/TestPyPI trusted publisher 前置条件
和 dry-run 路径。

## 本地完成标准

本分支本地完成需要全部通过：

1. `python -m pytest -q`；
2. `python -m ruff check src tests`；
3. `python -m mypy src/review_fix_loop`；
4. `python -m build && python -m twine check dist/*`；
5. workflow YAML parse tests；
6. schema sync tests；
7. 最终 fresh `review-fix-loop snapshot` 和 `gate --ci-mode` 无 blocking
   diagnostics。

## 外部验证

这些事项不能从本地 checkout 证明，必须在 GitHub/PyPI 环境完成：

- split CI jobs 存在后配置 branch protection required checks；
- 在 GitHub Actions 确认 `Security` workflow 为 green；
- 为本仓库和 release workflow 配置 PyPI/TestPyPI Trusted Publishing；
- 首次正式 PyPI publish 前运行 TestPyPI 或等价 dry run。
