# Release Checklist

Default first release target: `v0.1.0`.

Before publishing, confirm:

- `git fetch --tags` has completed.
- `git tag --list` is empty or does not include `v0.1.0`.
- The GitHub Releases page does not already contain `v0.1.0`.
- `pyproject.toml` version and `review_fix_loop.__version__` are both `0.1.0`.

## Local Checks

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q
if (Test-Path dist) { Remove-Item -Recurse -Force dist }
if (Test-Path build) { Remove-Item -Recurse -Force build }
python -m build
python -m twine check dist/*
git diff --check
git ls-files | Select-String -Pattern '(__pycache__|\.pytest_cache|\.egg-info|^dist/|^build/)'
```

The final command should produce no output.

## Create The Release

```bash
git tag v0.1.0
git push origin v0.1.0
```

Create a GitHub Release for `v0.1.0` with notes covering:

- fresh snapshot contract;
- slice invalidation;
- planned gates;
- redacted run records;
- no hosted PR bot, GitHub App, model API key, or external service;
- early adapter ecosystem.

## GitHub UI Checklist

- Confirm Actions has at least one green CI run.
- Set About text to: `Local-first fresh re-review contract for AI agents. Prevent stale-diff reuse with live snapshots, selected gates, and redacted run records.`
- Add topics: `ai-agent`, `code-review`, `review-loop`, `stale-diff`, `git`, `python`, `local-first`, `developer-tools`, `reviewdog`, `pre-commit`.
- Add a social preview image using the message `Fresh Snapshot for AI Review Loops`.
- Enable Discussions with Announcements, Q&A, Ideas, and Showcase categories.
- Seed Discussions with:
  - `What stale-diff failures have you seen in AI review loops?`
  - `Which adapters should Review Fix Loop support first?`
  - `Showcase: local review/fix/re-review workflows`
- If desired, enable the GitHub template repository setting.

## Badges After Release

Add a Release badge only after the GitHub Release exists. Add a PyPI badge only after a real PyPI or TestPyPI publish exists.
