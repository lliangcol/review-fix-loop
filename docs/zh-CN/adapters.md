# Adapters

adapter 把通用 review-loop 契约接到具体仓库。创建时优先从
`adapters/project-template` 开始。

## Adapter 负责什么

adapter 应声明：

- `rule_files` 中的本地规则文件；
- `normal_loop`、`large_merge` 或自定义 mode；
- slice 和风险等级；
- 以 `argv` 数组表示的 gate 命令；
- `when_paths`，用于只在相关路径变化时运行昂贵 gate；
- external gate 的 trust metadata；
- 高风险变更的人工确认边界。

公开示例不能包含私有路径、公司名、secret 或业务专属脚本。

## 公开与私有边界

开源示例应保持通用。如果 adapter 来自私有仓库，应只抽取可复用模式，并移除：

- 私有仓库名、路径、公司名和内部项目标签；
- 依赖私有脚本或私有服务的命令；
- 暴露客户、支付、权益、生产细节的业务规则；
- 命令输出、日志、token、凭据、证书和环境专属配置。

私有 adapter 应保留在消费仓库或私有分发渠道中。公开内容只保留通用的
adapter 结构、风险分类和 gate planning 技巧。

## Gate Config 形状

gate 的常用字段包括：

- `id`：稳定 gate 标识；
- `argv`：不经过 shell expansion 的命令数组；
- `scope`：`staged`、`unstaged`、`untracked`、`merge_base_to_head` 或 `all`；
- `when_paths`：可选路径 glob；
- `modes`：可选 mode id 列表；
- `filter_mode`：`nofilter`、`file`、`added` 或 `diff_context`；
- `fail_level`：阻断所需的最低 severity；
- `blocking`：失败是否阻断 loop；
- `timeout_seconds`：最大本地运行时间；
- `final_always`：final pass 是否强制计划该 gate；
- `trusted`、`allow_in_ci`、`writes_worktree`、`requires_network`、
  `trust_reason`：external gate 信任边界；
- `parallel_safe`、`reads_worktree_only`、`depends_on`：并行执行能力；
- `parser`：`exit-code`、`git-diff-check`、`regex-lines`、
  `json-diagnostics`、`rdjson`、`sarif` 或 `checkstyle`。

`file` 保留 changed files 上的 diagnostics，`added` 保留 added lines，
`diff_context` 保留 unified diff context。没有 file 的工具级失败始终保留。

mode id 从 config 中读取，不再由 CLI 硬编码。常见 mode 仍是 `normal_loop` 和
`large_merge`；项目可以增加更窄的自定义 mode，并用 `requires_merge_base`、
`requires_repo_map`、`max_changed_files` 等 advisory 字段表达 agent 契约。

内置命令：

- `__builtin__:untracked-whitespace`：检查 untracked 文本文件尾随空白，不
  staging、不改 index；
- `__builtin__:policy`：用 JSON diagnostics 表达简单路径策略。

## Authoring Flow

1. 运行 `review-fix-loop init --repo . --output review-fix-loop.gates.json`。
2. 替换 slices 为项目所有权边界。
3. 替换 gates 为已经能在本地运行的命令。
4. 为 external gate 补 trust metadata。
5. 使用 `when_paths` 降低无关 gate 执行。
6. 运行 pass 1 snapshot、修复、pass 2 snapshot，确认 slice invalidation。

## 确认边界

adapter 应声明 agent 可以自动修复什么，以及哪些情况必须停下来等待人工确认。
常见确认边界包括：

- public API、response、DTO 或 error contract 变化；
- 数据库 schema 或数据变更；
- 支付、账单、退款、权益、队列、事务或数据源行为；
- CI/CD、部署、权限、OAuth、MCP 或云配置；
- 依赖新增或升级；
- 大范围迁移、破坏性操作或历史重写。

## 示例

```bash
review-fix-loop snapshot \
  --repo . \
  --config adapters/project-template/gates.json \
  --mode normal_loop \
  --pass 1 \
  --write-run-record
```

默认 run record 写入 `.git/review-fix-loop/runs/...`。只有需要可见的
workspace-local records 时才使用 `--cache-dir .review-fix-loop`，并保持该目录
被 ignore。
