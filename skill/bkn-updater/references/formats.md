---
name: bkn-updater
---
# BKN 格式规范（模块 2/3）

> 段/条目格式 + 完整示例。

---

## BKN 格式规范

### Action 条目

```bkn
## Action: {操作名称}

- capability: {英文标识}
- object: {所属对象}
- access_type: read|write|admin
- binding_type: skill
- implements: skill:{skill-name}
- params: {参数1}({类型},required) {参数2}({类型})
- prerequisites: [{前置操作1}, {前置操作2}]
- constraints: [{约束1}, {约束2}]
- risks: [{错误码1}, {错误码2}]
- notes: {注意事项}
- aliases: {别名1}, {别名2}
```

### Skill actions.yaml 条目

```yaml
  {capability}:
    description: {人类可读描述}
    safe: true|false
    command_type: shell|sql|api|dump_tool
    command: "{命令模板}"
    requires:
      {param1}: "{说明}"
    output_interpretation:
      - success: "..."
      - failure: "..."
    notes: "..."
```

### 错误码/症状条目（25 号方案：**不进 BKN 清单**——边承载 ID 空间，别名是值数据）

不建表、不加清单行。两步：

① **补边**（本体）：`bkn/relations/process_topology.bkn` 的 `suspected_in` 段 `映射规则` 区加一行
（跨切面无法定位单进程 → 补 `has_class` 指向 `dimension:*`）：

```bkn
  - `error:{code}` → `process:{进程}`  # {一句话理由}
```

② **补别名**（值数据）：`plugin/constants.py` 的 `ERROR_ALIASES` / `SYMPTOM_ALIASES` 加「现场口语 → 规范 ID」；
机械变体由代码派生，不登记。检索指引是常量规则（`DIAG_RETRIEVAL_GUIDE`），不逐条写。
完整 6 属性（风险级别/触发条件/症状与排查/处置策略/禁止）**查库**，任何时候不进 BKN。
归不进任何维度 → `dimension:unknown` + `gap_log` 自动记录。

> **不再使用「## {错误码}: {简述}」独立段格式**，也**不再写 6 属性本地副本**（21/23 号：定义已入库，
> BKN 只留锚点 + 指针）。跨库检查点下延 `skill:demo-product-db-diagnostics/references/db-checkpoints.md`。

### 关系条目

```bkn
{source} → {relation_type} → {target}
```

---


---

## 完整示例：新增操作「导出规则配置」

**用户输入**：
> 新增操作：导出规则配置，capability=export_rule_config，object=syncrule，skill=demo-product-rule-manager，参数 rule_name(string,required)

**Agent 处理**：

1. `search_files(pattern="export_rule_config")` → 无结果（不重复）
2. 补充约束：询问 → 用户回复「规则必须在 STOPPED 状态」
3. 备份：`cp actions/rule_lifecycle.bkn actions/rule_lifecycle.bkn.bak.20260707`
4. Diff 预览 → 用户确认
5. 追加到 `actions/rule_lifecycle.bkn`：

```bkn
## Action: 导出规则配置

- capability: export_rule_config
- object: syncrule
- access_type: read
- binding_type: skill
- implements: skill:demo-product-rule-manager
- params: rule_name(string,required)
- constraints: [规则状态必须为 STOPPED]
- risks: []
- notes: 导出为 JSON 格式
- aliases: export_rule_config
```

6. 追加到 `relations/`（has_action → references.bkn，implements_skill → action_routing.bkn）：

```bkn
object:syncrule → has_action → export_rule_config
action:export_rule_config → implements_skill → skill:demo-product-rule-manager
```

7. 追加到 `skill/demo-product-rule-manager/actions.yaml`：

```yaml
  export_rule_config:
    description: Export sync rule configuration
    safe: true
    command_type: shell
    command: "cd $HOME/.demo-product/stream-agent && .venv/bin/python skill/demo-product-rule-manager/scripts/export_rule.py --rule-name {rule_name}"
    requires:
      rule_name: "Sync rule name"
    output_interpretation:
      - success: "导出成功"
      - failure: "规则不存在或状态不是 STOPPED"
```

8. 重启服务进程生效（`reload.py` 只重建执行它的短命进程的全局，常驻服务不生效）
9. 验证：`search_files(pattern="导出规则配置")` → 命中

---


---

## 完整示例：新增 Skill「demo-product-iadebug」

**用户输入**：
> 新增一个 iadebug 调试 Skill，包含列出规则、查看 track、强制恢复等操作。

**Agent 处理**：

1. 确认 skill-name 为 `demo-product-iadebug`
2. 创建 `skill/demo-product-iadebug/SKILL.md`：触发条件、命令示例、安全警告
3. 创建 `skill/demo-product-iadebug/actions.yaml`：定义 `iadebug_list_rules`、`iadebug_resumeforce` 等 action
4. 创建 `skill/demo-product-iadebug/README.md`：安装环境、命令速查、安全警告
5. 创建 `bkn/actions/iadebug.bkn`：每个 action 的 capability/object/implements/params/risks
6. 更新 `bkn/relations/`：references.bkn 加 object → has_action → capability；action_routing.bkn 加 `action:<capability> → implements_skill → skill:demo-product-iadebug`
7. 若涉及 -4002 诊断：`bkn/relations/process_topology.bkn` 核对 `suspected_in` 边 + `plugin/constants.py::ERROR_ALIASES` 核对别名（25 号：无锚点表）+ `plugin/skill_manifest.yaml` 核对 Skill 登记
8. 重启服务进程生效 + 验证

---
