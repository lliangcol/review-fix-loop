# Review Fix Loop 维护状态

最近更新：2026-06-25

## 项目定位

Review Fix Loop 是面向 AI review/fix/re-review 循环的本地优先 CLI 合同。
它约束 agent 在修复后何时必须从 live Git worktree 重新获取证据。它不自行审查代码、
不调用模型 API、不提供 hosted service、不充当 GitHub App，也不是自动修复平台。

## 硬约束

- `pyproject.toml` 的 runtime dependencies 保持为空；测试、schema、lint、type、
  security 和 release 工具只放在 `.[dev]` 或 GitHub Actions。
- core 不引入模型 API、云服务、网络依赖或外部 reviewer 行为。
- adapter config 保持 JSON 数据，不变成 Python plugin。
- snapshot、run record 和 gate output 只持久化有界脱敏 metadata；不得持久化完整源码、
  完整 diff、secret、未脱敏 stdout/stderr、私有路径或环境细节。
- schema 变更必须同步 `src/review_fix_loop/schemas/` 与
  `skills/review-fix-loop-core/references/`。
- 用户可见行为改动需要同步英文和中文文档；JSON、schema 和 artifact 字段保持英文。
- 不提交 `.review-fix-loop/`、`dist/`、`build/`、`*.egg-info`、缓存、
  `__pycache__/` 或本地运行产物。
- 验证结果必须按实际情况记录为已运行、失败、跳过或未运行；不得推断为通过。

## 已检查事实源

- `git status --short`
- `README.md`
- `README.zh-CN.md`
- `pyproject.toml`
- `.github/workflows/ci.yml`
- `.github/workflows/security.yml`
- `.github/workflows/release.yml`
- `CONTRIBUTING.md`
- `docs/remaining-work-implementation-plan.md`
- `docs/zh-CN/remaining-work-implementation-plan.md`
- `adapters/generic/gates.json`
- `src/review_fix_loop/templates/generic.gates.json`
- `src/review_fix_loop/schemas/*.schema.json`
- `skills/review-fix-loop-core/references/*.schema.json`
- `tests/test_review_loop_contract.py`

## 关键目录

- `src/review_fix_loop/`：runtime package 和 CLI 实现。
- `src/review_fix_loop/schemas/`：打包的 JSON schemas。
- `src/review_fix_loop/templates/`：`init` 使用的 bundled adapter templates。
- `adapters/`：仓库和项目 adapter 示例。
- `skills/review-fix-loop-core/`：skill packaging 和 schema references。
- `.github/workflows/`：CI、安全和发布自动化。
- `docs/` 与 `docs/zh-CN/`：成对的用户文档。
- `tests/`：runtime、schema、workflow 和 contract tests。

## 当前审计记录

- 当前分支是 `main`，跟踪 `origin/main`。
- `pyproject.toml` 当前声明 `dependencies = []`，符合零 runtime dependency 约束。
- CI、安全和发布 workflows 存在，并与实现计划整体一致：拆分 lint/type/test/build/
  artifact hygiene jobs，包含 Bandit/pip-audit/CodeQL/Dependency Review，以及 tag
  或 TestPyPI release flow。
- 英文和中文 remaining-work plans 结构配对，并且都区分本地完成标准和外部
  GitHub/PyPI 验证。
- packaged schemas 与 skill reference schemas 的文件名和当前内容一致。
- bundled generic adapter 和 packaged generic template 的 `large_merge` 曾重复声明
  `require_residual_risk_report`；本轮已去重且保持行为不变。
- adapter/config JSON loading 现在会在 `validate-config` 和
  `validate-schema --schema gate-config` 两条路径拒绝重复 object key。
- docs parity 测试现在同时检查 `docs/` 下英文到中文、中文到英文的 Markdown
  counterpart。

## 验证命令

环境允许时优先运行完整本地验证：

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
python -m pytest -q --cov=review_fix_loop --cov-branch --cov-report=term-missing
python -m ruff check src tests
python -m mypy src/review_fix_loop
python -m bandit -r src/review_fix_loop
python -m pip_audit
python -m build
python -m twine check dist/*
git diff --check
review-fix-loop validate-config --repo . --config adapters/generic/gates.json --no-local-override
review-fix-loop snapshot --repo . --config adapters/generic/gates.json --mode normal_loop --pass 1 --write-run-record --cache-dir .review-fix-loop
review-fix-loop gate --repo . --config adapters/generic/gates.json --snapshot .review-fix-loop/runs/<run-id>/snapshot.json --ci-mode --no-local-override
```

schema 和 workflow 漂移检查：

```bash
python -m pytest tests/test_review_loop_contract.py -q
python -m pytest tests/test_gate_config.py -q
```

## Schema 同步点

- `src/review_fix_loop/schemas/gate-config.schema.json`
- `src/review_fix_loop/schemas/snapshot.schema.json`
- `src/review_fix_loop/schemas/run-record.schema.json`
- `src/review_fix_loop/schemas/diagnostic.schema.json`
- `skills/review-fix-loop-core/references/gate-config.schema.json`
- `skills/review-fix-loop-core/references/snapshot.schema.json`
- `skills/review-fix-loop-core/references/run-record.schema.json`
- `skills/review-fix-loop-core/references/diagnostic.schema.json`

## 已知风险

- checkout 中存在本地生成目录（`.review-fix-loop/`、`dist/`、缓存、coverage
  output），必须保持不纳入版本控制。
- GitHub branch protection、workflow green status 和 PyPI/TestPyPI trusted
  publisher setup 无法从本地 checkout 证明。
- 当前 uv-managed Python 环境会用 PEP 668 `externally-managed-environment`
  拒绝直接 editable install；声明完整本地 release validation 前需要使用隔离 dev 环境。

## Backlog

1. 记录或脚本化兼容 PEP 668 的本地 dev bootstrap，让 `.[dev]` 工具链无需
   `--break-system-packages` 即可运行。
2. 在已安装 dev tools 的环境中运行完整 security 和 release validation。
3. 如果后续文档继续漂移，再考虑更严格的中英文 heading structure parity 检查。

## 最近验证

- `python -m pytest -q`：duplicate-key guard 与双向 docs parity 测试轮次后通过
  （`107 passed`）。
- `python -m pytest tests/test_review_loop_contract.py -q`：加入双向 docs counterpart
  覆盖后通过（`9 passed`）。
- `PYTHONPATH=src python -m review_fix_loop.cli validate-config --repo . --config adapters/generic/gates.json --no-local-override`：通过。
- duplicate-key 和 docs parity 轮次的 fresh `snapshot --pass 1 --write-run-record`
  与 `gate --ci-mode --no-local-override` 均通过。
- `git diff --check` 与 `git diff --cached --check`：通过。
- `python -m pip install -e ".[dev]"`：失败，当前 uv-managed Python 报告
  `externally-managed-environment` (PEP 668)。未使用 `--break-system-packages`。
- 当前 Python 环境中 `ruff`、`mypy`、`build`、`bandit`、`pip_audit` 和
  `pytest-cov` 不可用，最近轮次未运行。

## 下一候选

记录或脚本化兼容 PEP 668 的本地 dev bootstrap 路径，让这个 Windows checkout
可以稳定运行完整 `.[dev]` 验证工具链。
