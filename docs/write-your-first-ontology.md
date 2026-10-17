# 写你的第一个本体（30 分钟）

> 目标：给一个「同步任务」领域写出 2 个对象、1 条关系、1 个动作，让 lint 通过、并能被工具查询。

## 1. 选域（5 分钟）

只选你这次要回答的问题涉及的域。例如：「任务卡住时该看哪些日志、找哪个 Skill」。

## 2. 写对象（10 分钟）

`bkn/objects/worknode.bkn`：

```markdown
---
name: 工作节点
id: worknode
description: 承载同步任务的运行时节点
aliases: [节点, 同步节点]
---

# Object: Worknode (工作节点)

| 属性 | 语义 |
|---|---|
| 状态 | 节点运行状态（取值由产品定义） |
| 端口 | 由 `{db_manager_skill}` 提供（值委托） |
```

## 3. 写关系（5 分钟）

```markdown
<!-- type: relation -->
## Relation: 节点运行于主机
- **关系类型**: runs_on
- **源对象**: worknode
- **目标对象**: host
- **类型**: N:1
- **映射规则**:
  - `worknode` → `host`
```

## 4. 写动作（5 分钟）

```markdown
<!-- type: action -->
## Action: 启动同步规则
- capability: start_sync_rule
- object: worknode
- access_type: write
- binding_type: skill
- implements: skill:my-rule-manager
- params: 规则标识（字段由 Skill 定义）
- aliases: start_rule, 启动规则
```

## 5. 登记 Skill 并校验（5 分钟）

`plugin/skill_manifest.yaml` 里登记 `skill:my-rule-manager`，然后：

```bash
python3 -m plugin.scripts.lint_bkn --error-only --bkn-root bkn
python3 -m pytest -q
```

## 常见 lint 报错

| 报错 | 含义 | 改法 |
|---|---|---|
| `命令/参数值/路径` 类 error | 本体越界到做法 | 改成 `skill:<id>` 指针 |
| `裸错误码` | 码进了本体 | 删除，码只作入口（FAQ Q27） |
| `悬空 skill:` | manifest 未登记 | 在 `skill_manifest.yaml` 加一行 |
| `非实例登记表格` | 说明性表格进了本体 | 挪到 Skill references |

