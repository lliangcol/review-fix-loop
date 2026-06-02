# Comparisons

Review Fix Loop is intentionally smaller than a hosted review platform. It focuses on stale-context prevention for local AI review loops.

| Project type | Strong fit | Where Review Fix Loop differs |
| --- | --- | --- |
| PR-Agent | Hosted or integrated PR review automation | Review Fix Loop does not review PRs or call models; it governs local re-review freshness. |
| reviewdog | Reporting diagnostics from linters and tools | Review Fix Loop can run gates, but its main contract is fresh snapshots after fixes. |
| pre-commit | Fast local hooks before commit | Review Fix Loop is pass-aware and records snapshot metadata across review passes. |
| Danger JS | Team conventions and PR checks as code | Review Fix Loop is local-first and agent-oriented, not a PR comment automation layer. |

## When To Use Review Fix Loop

Use it when an AI agent needs to prove that pass N review uses live pass N repository state instead of pass N-1 context.

## When Not To Use It

Do not use it as a hosted PR bot, a replacement for CI, a model provider, or a universal code review platform.
