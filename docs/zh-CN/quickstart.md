# 中文快速开始

本页展示如何在本地跑完一轮 review/fix/re-review，不依赖外部模型服务或托管 PR 机器人。

## 安装

以下示例命令假设你在本仓库 checkout 中运行，或目标仓库已经包含对应 adapter 文件。接入其他仓库时，请先复制 `adapters/project-template`，或传入 adapter 配置的绝对路径。

```bash
python -m pip install -e ".[dev]"
```

## 初始化配置

```bash
review-fix-loop init --repo . --output review-fix-loop.gates.json
review-fix-loop validate-config --repo . --config review-fix-loop.gates.json
```

如果仓库存在 `.review-fix-loop.local.json`，`validate-config`、`doctor` 和
`snapshot` 会报告该本地 override 是否生效。CI 或 release 检查需要忽略本地
override 时，使用 `--no-local-override`。

## 生成 Pass 1 Snapshot

```bash
review-fix-loop snapshot \
  --repo . \
  --config review-fix-loop.gates.json \
  --mode normal_loop \
  --pass 1 \
  --write-run-record \
  --cache-dir .review-fix-loop
```

输出 JSON 会包含 `snapshot_id`、`snapshot_path`、`run_record_path`、`must_reload`、`planned_gates` 等字段。

如果不传 `--cache-dir`，run record 默认写入 `.git/review-fix-loop/runs/...`。如果使用 `.review-fix-loop`，该目录是本地运行产物，不应提交。

## 执行 Gates

```bash
review-fix-loop gate \
  --repo . \
  --config review-fix-loop.gates.json \
  --snapshot .review-fix-loop/runs/<run-id>/snapshot.json
```

gate 只会执行 snapshot 中选择的 `planned_gates`。如果 gate 配置或规则文件在 snapshot 后发生变化，需要重新生成 snapshot。
CI 中建议加 `--ci-mode`，这样新加入的 external gate 只有在 adapter 标记
`trusted=true` 且 `allow_in_ci=true` 后才会执行。

## 修复后生成 Pass 2

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

Pass 2 必须传入上一轮 `run-record.json`。输出中的 `must_reload` 和 `reuse_forbidden_slices` 会告诉 agent 哪些内容不能复用旧上下文。

最终确认轮需要加 `--final-pass`，这样 `final_always` gates 会被纳入
`planned_gates`。

## 查看与校验

```bash
review-fix-loop inspect --snapshot .review-fix-loop/runs/<run-id>/snapshot.json
review-fix-loop validate-schema --schema snapshot --file .review-fix-loop/runs/<run-id>/snapshot.json
review-fix-loop doctor --repo . --config review-fix-loop.gates.json
```

当 effective config 必须排除 `.review-fix-loop.local.json` 时，可在
`snapshot`、`gate`、`validate-config` 或 `doctor` 中加入
`--no-local-override`。

常见人类可读错误可通过 `--locale zh-CN` 或
`REVIEW_FIX_LOOP_LOCALE=zh-CN` 本地化；JSON key 保持英文不变。

## 常见错误

`--pass > 1 requires --previous-run-record`

运行 pass 2 时传入上一轮的 `run-record.json`。

`effective config hash differs from snapshot config_hash; create a fresh snapshot`

snapshot 生成后 gate config 发生了变化。运行 gates 前先生成新的 snapshot。

`rule file hashes differ from snapshot rule_hashes; create a fresh snapshot`

配置的 rule file 在 snapshot 后发生了变化。复审前先生成新的 snapshot。

`JSON file not found`

检查 `snapshot_path` 或 `run_record_path`；run ID 会按时间戳写入所选 run root。
