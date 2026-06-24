# Template Repository

把 Review Fix Loop 接入新仓库时，可以把本仓库作为模板参考。

## 基本步骤

1. 复制 `adapters/project-template` 或运行 `review-fix-loop init`。
2. 用目标项目的 ownership/risk 区域替换 `slices`。
3. 把 gate 命令替换成目标仓库已经能本地运行的命令。
4. 为 external gate 声明 `trusted`、`allow_in_ci`、`writes_worktree`、
   `requires_network` 和 `trust_reason`。
5. 增加项目规则文件，并放入 `rule_files`。
6. 跑 pass 1 snapshot、gate、修复、pass 2 snapshot。

## 不应复制的内容

不要把私有路径、内部服务名、token、证书、客户数据或生产日志放进公开模板。
公开 adapter 只应展示结构、slice 风险和 gate planning 技术。

## 推荐验证

```bash
review-fix-loop validate-config --repo . --config review-fix-loop.gates.json
review-fix-loop snapshot --repo . --config review-fix-loop.gates.json --mode normal_loop --pass 1
review-fix-loop doctor --repo . --config review-fix-loop.gates.json
```
