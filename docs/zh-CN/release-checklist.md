# Release Checklist

默认首个 release 目标是 `v0.1.0`。

## 发布前确认

- 已运行 `git fetch --tags`。
- tag `v0.1.0` 尚不存在。
- GitHub Releases 中尚无 `v0.1.0`。
- `pyproject.toml` version 与 `review_fix_loop.__version__` 一致。
- PyPI 或 TestPyPI 已为本仓库、workflow 和 environment 配置 Trusted
  Publisher。

## 本地检查

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q
python -m ruff check src tests
python -m mypy src/review_fix_loop
python -m bandit -r src/review_fix_loop
python -m pip_audit
python -m build
python -m twine check dist/*
review-fix-loop --help
review-fix-loop list-adapters
review-fix-loop validate-schema --schema gate-config --file adapters/generic/gates.json --repo .
git diff --check
git ls-files | Select-String -Pattern '(__pycache__|\.pytest_cache|\.mypy_cache|\.ruff_cache|\.egg-info|^dist/|^build/|^\.review-fix-loop/)'
```

最后一条命令不应输出内容。

## 创建发布

```bash
git tag v0.1.0
git push origin v0.1.0
```

`Release` workflow 会构建 sdist/wheel、执行 twine check、安装 wheel 做 CLI
smoke test，然后通过 PyPI Trusted Publishing 发布。正式发布前建议先用
manual dispatch 的 `publish_to_testpypi=true` 做 dry run。

## Release Notes

notes 至少覆盖 fresh snapshot contract、slice invalidation、planned gates、
redacted run records、external gate trust boundary、parallel-safe gates，以及
不依赖 hosted PR bot / GitHub App / model API key / 外部服务。
