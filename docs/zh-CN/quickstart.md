# 中文快速开始

本页展示如何在本地跑完一轮 review/fix/re-review，不依赖外部模型服务或托管 PR 机器人。

## 安装

以下示例命令假设你在本仓库 checkout 中运行，或目标仓库已经包含对应 adapter 文件。接入其他仓库时，请先复制 `adapters/project-template`，或传入 adapter 配置的绝对路径。

```bash
python -m pip install -e ".[dev]"
```

## 生成 Pass 1 Snapshot

```bash
review-fix-loop snapshot \
  --repo . \
  --config adapters/generic/gates.json \
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
  --config adapters/generic/gates.json \
  --snapshot .review-fix-loop/runs/<run-id>/snapshot.json
```

gate 只会执行 snapshot 中选择的 `planned_gates`。如果 gate 配置或规则文件在 snapshot 后发生变化，需要重新生成 snapshot。

## 修复后生成 Pass 2

```bash
review-fix-loop snapshot \
  --repo . \
  --config adapters/generic/gates.json \
  --mode normal_loop \
  --pass 2 \
  --previous-run-record .review-fix-loop/runs/<run-id>/run-record.json \
  --write-run-record \
  --cache-dir .review-fix-loop
```

Pass 2 必须传入上一轮 `run-record.json`。输出中的 `must_reload` 和 `reuse_forbidden_slices` 会告诉 agent 哪些内容不能复用旧上下文。
