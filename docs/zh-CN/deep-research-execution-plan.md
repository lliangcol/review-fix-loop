# 深度研究执行计划

本文把 `D:/Documents/GitHub/review-fix-loop/deep-research-report.md` 转换成
可执行、可复审、可验证的实施计划。原研究报告覆盖范围较大；本文记录在建立
质量 baseline 后已经提升到当前分支的本地工作，并把它们与只能在外部环境验证
的发布事项分开。

## 范围

当前批次必须保留核心产品合同：

- core package 保持零安装期运行依赖；
- core package 不接入模型 API、托管服务或网络依赖；
- snapshot 与 gate artifact 继续保持脱敏，不落完整源码或完整 diff；
- 修复后必须从 live worktree 重新生成 fresh snapshot 再复审。

当前批次执行这些可以一起交付和验证的高价值事项：

1. 对齐 README、CI 与 security workflow 需要的开发工具链；
2. 将 CI 拆成 lint、typecheck、matrix test、build、artifact-hygiene job，
   并上传 coverage 与 JUnit 测试证据 artifact；
3. 让文本 run-record 输出使用和 JSON 一致的原子写策略；
4. 让本地 config override 来源在 CLI 输出与持久化记录中可见，并提供
   `--no-local-override` 供 CI 禁用本地 override；
5. 对外部 gate stdout/stderr 做有界捕获，避免超大输出被无界解码并写入摘要；
6. 批量化 snapshot diff/blob 探测、增加 service/domain 边界、增加 gate trust
   与并行执行 metadata、支持自定义 adapter mode、加入初版 locale，并增加
   release automation；
7. 记录无法从本地 checkout 证明的外部验证事项。

## 当前批次工作项

### 1. 开发工具链与 CI 证据

更新 `pyproject.toml`，让 `python -m pip install -e ".[dev]"` 安装 README 与
CI 路径实际需要的工具：

- `pytest-cov` 用于 coverage 报告；
- `build` 与 `twine` 用于包构建检查；
- `pytest-xdist`、`ruff`、`mypy`、`bandit[toml]`、`pip-audit` 用于本地、
  CI 与 security workflow 验证。

更新 `.github/workflows/ci.yml`，增加必跑的 lint 与 typecheck job，保留现有
pytest matrix 与 wheel smoke test，并上传 coverage XML 与 JUnit XML artifact。
新增 `.github/workflows/security.yml`，运行 Bandit、pip-audit、CodeQL 与
Dependency Review。

验收：

- `python -m pytest -q` 通过；
- `python -m pytest -q --cov=review_fix_loop --cov-branch --cov-report=term-missing`
  本地通过；
- `python -m ruff check src tests` 通过；
- `python -m mypy src/review_fix_loop` 通过；
- `python -m bandit -r src/review_fix_loop` 通过；
- `python -m pip_audit` 未发现已知漏洞；
- CI 继续构建并 smoke-test wheel；
- CI 为每个 matrix entry 上传 coverage/JUnit artifact。

### 2. 文本 run output 原子写

在 `src/review_fix_loop/run_record.py` 增加 `write_text_atomic()`，并用于
`summary.md`。JSON 输出已经使用 sibling temp file 和 `os.replace`，Markdown
摘要也应使用相同持久化模型。

验收：

- 现有 run-record 测试继续通过；
- 新增回归测试证明 `summary.md` 会写入成功，且成功后不遗留 sibling temp file。

### 3. Config Override 来源可观测

不改变默认行为的前提下，让 `.review-fix-loop.local.json` 可观测：

- `load_effective_config()` 除 effective config hash 与 rule hashes 外，还返回
  config source 元数据；
- `snapshot`、`run-record`、`doctor`、`validate-config` 输出展示 local override
  是否生效以及来源路径；
- 新增 `--no-local-override`，供 CI 与 release workflow 强制只使用 adapter config。

验收：

- 默认仍会在存在 `.review-fix-loop.local.json` 时应用本地 override；
- `--no-local-override` 能阻止本地 override；
- schema validation 接受新的 snapshot/run-record 元数据字段；
- 测试覆盖 override 生效与禁用两条路径。

### 4. 外部 Gate 输出有界捕获

把无界 stdout/stderr 解码摘要改为有界捕获 helper。parser 合同保持不变。
gate 默认仍串行执行，只有显式标记 `parallel_safe` 的 gate 才能并行。

验收：

- 现有 gate parser 测试继续通过；
- 大体量 UTF-8 输出被截断后仍保持有效文本；
- gate result 记录包含 `stdout_truncated`、`stderr_truncated`、`stdout_bytes`、
  `stderr_bytes`；
- bounded capture 后仍执行脱敏。

## 已提升到当前分支的工作包

以下事项原本是后续阶段候选项，现在已经纳入当前分支：

1. CI 拆成 lint、typecheck、test、build、hygiene 多个 job；
2. scope 级批量 Git diff、HEAD blob lookup 与 binary status 探测；
3. snapshot freshness 与 gate execution 的 service/domain 边界；
4. external gate trust metadata，以及 CI 中拒绝 untrusted command；
5. PyPI Trusted Publishing 发布流水线；
6. 中文文档配对与 CLI locale 初版；
7. adapter-defined mode id 与 advisory capability 字段。

可执行拆解和外部验证清单见
[未完成任务完整实现方案](remaining-work-implementation-plan.md)。

## Review-Fix-Re-Review 协议

只有满足以下条件，计划才算完成：

1. 已根据当前源码、测试、schema、文档审查本计划；
2. 计划 review 中发现的问题已经修复；
3. 实现严格遵循已复审的当前批次范围；
4. 针对 live edited worktree 运行测试和本地 review-fix-loop snapshot/gate；
5. 修复后的 fresh snapshot 与复审不再发现新的 in-scope 问题。

## 验证命令

在仓库根目录运行：

```bash
python -m pytest -q
python -m pytest -q --cov=review_fix_loop --cov-branch --cov-report=term-missing
python -m ruff check src tests
python -m mypy src/review_fix_loop
python -m bandit -r src/review_fix_loop
python -m pip_audit
python -m build
python -m twine check dist/*
review-fix-loop snapshot --repo . --config adapters/generic/gates.json --mode normal_loop --pass 1 --write-run-record --cache-dir .review-fix-loop
review-fix-loop gate --repo . --config adapters/generic/gates.json --snapshot <snapshot_path> --ci-mode
```

实现修复后，使用 `--previous-run-record <run-record.json>` 生成 pass 2 snapshot，
并只复审 fresh snapshot 标记为 changed 或 reuse-forbidden 的 slices。
