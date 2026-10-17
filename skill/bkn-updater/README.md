## 安装 Skill

代码仓库固定放在目标机器的 `$HOME/.demo-product/stream-agent`。
`bkn-updater` 是 BKN / Skill 维护工具，不需要额外的 Python 依赖，直接作为 Hermes Skill 加载即可。

## 运行环境

- Hermes 会话环境
- 可读写 `bkn/` 和 `skill/` 目录
- 可选：能够重启常驻服务进程以生效 `.bkn` 改动（`plugin/scripts/reload.py` 只重建执行它的短命进程的全局，常驻服务不生效）

## 使用方式

当用户说以下任一关键词时加载本 Skill：

```
更新 BKN / 添加操作 / 新增错误码 / 补充兼容性 / 把这个加到 BKN
BKN 里没有这个 / BKN 缺少 / 新增 Skill / 把 skill 加到 BKN
```

### 新增操作示例

```
用户: 新增操作：导出规则配置，capability=export_rule_config，object=syncrule，skill=demo-product-rule-manager

Agent:
  1. 查重
  2. 询问缺失参数/约束
  3. 备份 bkn/actions/rule_lifecycle.bkn
  4. 追加 Action 定义
  5. 追加关系：`bkn/relations/references.bkn`（object → has_action → capability）+ `bkn/relations/action_routing.bkn`（action:<capability> → implements_skill → skill:<skill-name>）
  6. 追加 skill/demo-product-rule-manager/actions.yaml 命令模板
  7. 重启服务进程生效
  8. 验证
```

### 新增 Skill 示例

```
用户: 新增一个 iadebug 调试 Skill

Agent:
  1. 创建 skill/demo-product-iadebug/SKILL.md
  2. 创建 skill/demo-product-iadebug/actions.yaml
  3. 创建 skill/demo-product-iadebug/README.md
  4. 创建 bkn/actions/iadebug.bkn
  5. 更新 `bkn/relations/references.bkn` + `bkn/relations/action_routing.bkn`（涉及进程拓扑时再改 `bkn/relations/process_topology.bkn`）
  6. 如涉及诊断，更新 `bkn/relations/process_topology.bkn` 的 `suspected_in`/`has_class` 边（症状、错误码 → 进程/维度的归类）与 `bkn/relations/action_routing.bkn`（动作路由）
  7. 重启服务进程生效
  8. 验证
```

## 核心原则

- **BKN 只给思路**：`bkn/` 中只保留人类可读的业务语义、约束、风险、关系。
- **Skill 给具体设计**：`skill/<name>/actions.yaml` 中保存具体命令模板、参数、安全级别。
- **禁止自动覆盖**：写入前必须备份 + 展示 diff + 用户确认。

## 所属 Actions

本 Skill 是元维护 Skill，不通过 `actions.yaml` 暴露具体操作命令；其能力通过 Hermes Tool（`search_files`、`read_file`、`write_file`、`terminal`）实现。

## 参考文件

| 文件 | 内容 |
|------|------|
| `skill/bkn-updater/SKILL.md` | 完整更新流程与格式规范 |
| `skill:bkn-plugin`（SKILL.md） | Plugin 架构说明（权威；原 `references/plugin-architecture.md` 过期快照已删） |
| `skill/bkn-updater/references/update-workflow.md` | 历史更新工作流 |
| `references/workflow-steps.md` | 新增 Skill / Action 的 SOP（原 `doc/update/add-skill.md`，2026-10-15 清理） |
| `references/workflow-steps.md` | 修改 Skill 的 SOP（同上一行；原 `doc/update/change-skill.md`，2026-10-15 清理） |
