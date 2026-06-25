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

- 本轮开始时 worktree 已有大量已暂存源码、测试和文档改动；这些视为既有用户工作。
- `pyproject.toml` 当前声明 `dependencies = []`，符合零 runtime dependency 约束。
- CI、安全和发布 workflows 存在，并与实现计划整体一致：拆分 lint/type/test/build/
  artifact hygiene jobs，包含 Bandit/pip-audit/CodeQL/Dependency Review，以及 tag
  或 TestPyPI release flow。
- 英文和中文 remaining-work plans 结构配对，并且都区分本地完成标准和外部
  GitHub/PyPI 验证。
- packaged schemas 与 skill reference schemas 的文件名和当前内容一致。
- bundled generic adapter 和 packaged generic template 的 `large_merge` 曾重复声明
  `require_residual_risk_report`；本轮已去重且保持行为不变。

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

- 现有已暂存改动范围较大；发布前应单独按批次审查。
- checkout 中存在本地生成目录（`.review-fix-loop/`、`dist/`、缓存、coverage
  output），必须保持不纳入版本控制。
- GitHub branch protection、workflow green status 和 PyPI/TestPyPI trusted
  publisher setup 无法从本地 checkout 证明。

## Backlog

1. 为 adapter JSON loading 增加显式 duplicate-key guard，避免未来重复配置键只能靠人工审查发现。
2. 增强 README 和主要 docs 的中英文结构 parity 检查。
3. 当前已暂存源码改动稳定后，运行完整 security 和 release validation。

## 最近验证

- `python -m pip install -e ".[dev]"`：失败，当前 uv-managed Python 报告
  `externally-managed-environment` (PEP 668)。未使用 `--break-system-packages`。
- `git diff --check`：通过。
- `git diff --cached --check`：通过。
- `PYTHONPATH=src python -m review_fix_loop.cli validate-config --repo . --config adapters/generic/gates.json --no-local-override`：通过。
- `python -m pytest tests/test_review_loop_contract.py -q`：首次失败，因为新增英文状态文件需要
  `docs/zh-CN/` counterpart；补齐 counterpart 后通过（`9 passed`）。
- `python -m pytest tests/test_gate_config.py::test_all_bundled_gate_configs_validate_against_schema -q`：未运行，原因是该 test id 不存在。
- `python -m pytest tests/test_gate_config.py::test_generic_adapter_matches_packaged_template tests/test_gate_config.py::test_packaged_adapter_configs_validate -q`：通过（`2 passed`）。
- `python -m pytest tests/test_gate_config.py -q`：失败，当前 live worktree 中
  `test_diagnostic_schema_rejects_invalid_severity` 仍有 1 个既有失败。当前 validator 输出
  `field severity must be one of [...]`，测试仍期待 jsonschema 风格的
  `"'fatal' is not one of"` 文案。
- `python -m ruff check ...`：未运行，当前 Python 环境未安装 `ruff`。
- `python -m mypy src/review_fix_loop`：未运行，当前 Python 环境未安装 `mypy`。

## 下一候选

使用标准库为 bundled adapter JSON 文件和 `init` template source 增加 focused
duplicate-key regression test。
