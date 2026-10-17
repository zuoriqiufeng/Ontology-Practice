---
name: bkn
description: BKN (Business Knowledge Network) 业务+运维双问题域知识网络生成器 — 基于 KWeaver 官方 BKN 规范（Object/Relation/Action/Risk），为数据库同步等业务场景自动生成 Markdown 格式的业务本体定义，作为 AI Agent 的 Source of Truth。将自然语言需求编排为 Agent 可渐进式披露的结构化业务知识网络。生成前经 Step 0 与用户确认问题域（仅业务 / 仅运维 / 业务+运维，不默认绑定）。
version: 2.4.0
author: Info2Soft AI Team
dependencies: []
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [BKN, KWeaver, Agent Context, Ontology, Database Sync, Business Knowledge Network, Context Engineering]
---

# BKN 语法规范（模块 2/5）

> 段类型（四元）语法 + 边界硬约束。

---

## BKN Markdown 语法规范

### Object 定义

实际 BKN 用 **KV 对**描述属性（与解析器 `_extract_key_values` 一致）；**表格只允许实例登记**
（行首带命名空间 ID，或段内声明 `> 行 = <注册集> 实例`）——状态机/进程矩阵/多维对照表均已废止，值下延 Skill。

**对象文件必须带 YAML frontmatter**（v1.5 起，见 `bkn/SCHEMA.md` 与 `doc/build/demo-product-bkn/24-bkn_ontology.md`）：

```markdown
---
name: <对象中文名>          # 必填
id: <对象英文ID_与文件名一致>  # 必填，下划线小写
description: <一句话描述>    # 必填
aliases:                    # 可选，同义词列表
  - <同义词1>
  - <文档名>
---

# Object: <对象名>

- **标识**: <唯一标识字段>
- **描述**: <一句话描述该业务对象>
- <属性名1>: <取值或约束说明>
- <属性名2>: <取值或约束说明>
- 状态: <STATE_A | STATE_B | STATE_C>       ← 枚举值用 | 分隔
- **数据源**: <底层数据来源>
```

frontmatter 落入 resolver 的 `_head` section，不影响正文 section/table/kv 解析。属性类型用 `bkn/SCHEMA.md` 的 9 枚举（string/decimal/integer/boolean/datetime/enum/object/array/json）。

示例（对齐产品级 BKN 的对象属性写法）：

```markdown
- name: 节点名称（用户自定义或 hostname）
- status: 未激活 / 在线 / 离线
- dat_port: 数据端口（由 {node_manager_skill} 在安装/启动阶段分配）
```

### Relation 定义

```markdown
## Relation: <关系名>

- **关系类型**: <snake_case，29 种白名单内>
- **中文名**: <中文关系名>
- **源对象**: <ObjectA>
- **目标对象**: <ObjectB>
- **类型**: 1:1 | 1:N | N:M
- **描述**: <关系语义>
- **映射规则**:
  - `<A.attr>` → `<B.attr>`
```

> 产品级 BKN **已采用**上方 KWeaver 段落格式（`bkn/relations/*.bkn` 整目录入图），并在段内增加机读扩展字段 `- **关系类型**: <snake_case>` 作为 graph 的 `rel_type` key：白名单共 **29 种**，权威为 `plugin/relations.py::RelationTraverser.RELATION_TYPES`，中文字典见 `bkn/relations/RELATION_TYPES.md`。新增关系时：写 `## Relation:` 段、**强制**声明 `关系类型` 与 `中文名`；类型级直接填 `源对象/目标对象`，实例级路由在 `映射规则` 区逐行 `` `src` → `tgt` `` 穷举。缺 / 非法 `关系类型` 的段落会被解析器跳过不入图。
>
> **关系类型白名单是唯一登记点**：新增实例只加「映射规则」行，**不改类型**；只有新增一种关系语义才动 `RELATION_TYPES`（本体评审制，见「新增本体准入四关」）。
>
> **抽象节点约定**（v1.5）：关系层语义抽象、无实体定义的目标加 `(abstract)` 后缀（如 `` `operation:Oracle开启归档(abstract)` ``），入图时解析器剥离后缀；lint 不对抽象目标报缺实体。
> **源端/目标端角色由边类型承载**：`syncrule --reads_from--> dbnode` / `syncrule --writes_to--> dbnode`；**禁止**给节点名加 `:source`/`:target` 后缀（该编码已废除，不产生虚节点/孤立节点）。

#### 两种 BKN→Skill 接线方式（区分）

- **`implements_skill`（动作实现，是关系类型——写进边）**：Action capability 由 Skill 实现。Action 自描述写在 `actions/*.bkn` 的 `- implements: skill:<name>`；路由边登记在 `bkn/relations/action_routing.bkn` 的 `implements_skill` 段 `映射规则` 区：`` `action:<capability>` → `skill:<name>` ``。解析器（`get_skills_for_action`）据此把 capability 路由到 Skill。
- **值委托（指针，不是关系类型）**：BKN 上下文文件把具体端口/路径/默认值/SQL 委托给查询/校验型 Skill。这类 Skill **不进** `actions/*.bkn`，也不进 `bkn/relations/*.bkn` 边表；只在委托文件正文写「由 `skill:<name>` 提供」指针，并在 `plugin/skill_manifest.yaml` 登记。例：
  - `objects/database.bkn` 对象段正文：`源端配置要求与验证命令由 {db_manager_skill} 提供`
  - `topology.bkn` 正文：`<helper_data_port>` 占位 + `由 {deploy_skill} 渲染`（原 topology-visualizer，同日并入）

判断用哪个：用户/模型要"执行一个动作" → `implements_skill`（写进边）；要"取一个具体值/渲染/校验" → 正文「由 `skill:xxx` 提供」指针（值委托，不是关系类型）。

### Action 定义 (v3 — implements: skill 模式)

```markdown
## Action: <动作名>

- capability: <英文标识>
- object: <归属对象>
- access_type: <read | write | admin>     ← v1.5 起必填，默认 write
- binding_type: skill                     ← v1.5 起；当前仅 skill 启用（mcp/local/api 预留）
- implements: skill:<skill名称>   ← 只引用Skill, 不放命令/脚本
- dangerous: true                         ← 仅危险操作标（failover/强制恢复/位点重置/差异修复/删除规则类）
- params: <参数1>(<类型>,required) <参数2>(<类型>)
- prerequisites: [<前置操作1>, <前置操作2>]
- constraints: [<约束1>, <约束2>]
- risks: [<错误码1>, <错误码2>]
- notes: <注意事项>
- aliases: <别名1>, <别名2>        ← 可选，用于 capability 别名匹配
```

`aliases` 是可选 KV，用英文/中文逗号分隔。当模型使用缩写或英文 enum（如 `create_rule`）时，Plugin 可通过别名命中 capability（如 `create_sync_rule`）。

> **access_type 读写分离**（v1.5 规则 15）：纯查询/只读操作原则上**不新增** Action 段——Agent 通过对象定义 + `search_qdrant` 即可实现查询；write/admin 类才走完整 Action 段。

> **KV key 规范**: 键名支持中英文、数字、下划线，解析器会跳过 markdown 特殊符号（如 `>`、`|`、`#`）。

> **边界硬约束（顶级规则）**: BKN 只定义稳定的 capability + params + constraints，**绝不**写 command/脚本路径/SQL/参数含义/输出解读/机器路由表。脚本路径、环境、PYTHONPATH、命令模板随版本变化，归 Skill。新增操作改 BKN，改脚本路径只改 Skill，两者独立演进。完整禁止清单与正确/错误对照见下文「BKN-Skill 边界硬约束」顶级章节。Plugin 虽有 `_filter_command_fields` 兜底脱敏，生成的 BKN 仍应原生合规，不依赖安全网。

### Risk 定义

```markdown
## Risk: <风险名>

- **关联对象/动作**: <Object | Action>
- **风险级别**: critical | warning | info     ← v1.5 起 3 级枚举（CRITICAL→critical, HIGH→warning, MEDIUM→info）
- **触发条件**: <什么情况下触发>
- **约束行为**: <禁止/限制什么操作>
- **处置策略**: <自动/人工/降级>
- **告警规则**: <如何通知>
```

> **约束表格的机器可读列**（v1.5，产品级 BKN 的 constraints 模式）：操作约束按级别分段（L0 常驻 / L2 写操作加载），表格含「约束ID」「类型」两列：
> - **约束ID**：机器可读键（如 `cannot_delete_RUNNING`），与 `relations/action_routing.bkn` 的 `constrained_by` 边逐条对齐；
> - **类型**：8 种 risk_type 枚举之一（threshold/state_prerequisite/param_constraint/forbidden_sequence/resource_limit/compatibility/data_loss/performance）；
> - `state_prerequisite` 类型的约束ID 需遵循命名约定（`cannot_<verb>_<STATE>` / `<obj>_must_be_<STATE>` 等，见 `bkn/SCHEMA.md` 3.1 节）——RiskGuard 据此自动翻译为代码校验，新增约束不改代码。

### Scenario 场景（非段类型）

场景**不是段类型白名单成员**：`scenario` 段类型已归档，场景文件为 `objects/scenario-*.bkn`，段标 `<!-- type: entity -->`，命名空间 `scenario:*` 供边引用。产品级 BKN 的场景文件需包含 `基本信息` section，供 Plugin 动态发现与路由：

```markdown
## 基本信息

- 场景 ID: <唯一标识>
- 场景名称: <中文显示名>
- 关键词: <关键词1>、<关键词2>、...
- 涉及产品: <产品名>
- 配套产品: ...        ← 可选
- 拓扑模式: ...        ← 可选
```

场景匹配路由在 Tool 层常量（`plugin/resolver.py::_SCENARIO_ROUTING_RULES`），不写入本体。


---

## BKN-Skill 边界硬约束（顶级规则）

> 这是与 Object / Relation / Action / Risk **同级**的顶级硬约束，不是补充说明。违反即视为 BKN 缺陷。

### 禁止清单（BKN 中不得出现）

- 可执行命令模板（如 `./dumpredo -S -t "..."`、`python3 start_rule.py --uuid xxx`）
- 具体参数说明（如 `-0/-1/-2/-3` 含义、`--force` 语义）
- 输出字段逐行解读
- 决策树与具体执行步骤
- 脚本路径、SQL 语句、CLI 命令、环境变量设置命令（提及需求可以；给出命令不行）
- 硬引用 Skill 内部文件路径（如 `{db_manager_skill}/references/xxx.md`）
- 机器可读路由表（如 symptom → DB → action YAML 块）
- 具体端口 / 绝对路径 / 权威默认值（如 `1521`、`~/idata/cache/`、`100M`）—— 写占位 + Skill 指针

### 正确 / 错误对照

| 正确（可以写） | 错误（不能写） |
|------|------|
| `负责 Skill: {db_diagnostics_skill}` | `./dumpredo -i /path/to/redo -s 0123456` |
| `implements: skill:<待补充>` | `./start_rule.sh --uuid abc123` |
| `操作: 解析 Redo Log 定位增量同步异常点` | `dumpredo 输出各列含义: OP=操作类型, SCN=系统变更号` |
| `参考: → relations/process_topology.bkn（归路边）` | `具体命令见 {db_diagnostics_skill}/references/oracle-dump-tools-full.md` |
| `注意: 目标端 ABNORMAL 状态无法创建规则` | `执行: python3 <脚本绝对路径>/start_rule.py --uuid xxx` |
| `端口: <db_port>（由 {db_manager_skill} 提供）` | `Oracle <port>, MySQL <port>` |
| `强制删除由 {sync_manager_skill} 的 delete_rule 处理` | `删除需加 --force yes` |

### 兜底安全网

`plugin/tools.py` 的 `_filter_command_fields` 对 BKN 输出做键级 + 值级脱敏（SQL/绝对路径/默认端口/工具名/`--force`/可执行命令命中即替换并记录 gap）。但这是**安全网，不是设计依据**：生成的 BKN 应原生遵守本约束，而不是依赖被脱敏。

---

## 机制因果域与结构域（边的域归属与走法）

关系类型按域分组，机制层与结构层：

| 域 | 关系类型 | 语义 |
|----|---------|------|
| **M-因果** | `triggers` / `amplifies` / `manifests_as` / `subclass_of` | 机制间直接因果 / 间接放大传导 / 机制在观测面的表现 / 类层次 |
| **M-屏障** | `mitigated_by` | 机制受哪条约束或动作阻止/削弱（目标为裸名约束 ID） |
| **结构域** | `connects_to` | 网络链路两端连接单元（无向；方向/协议/端口角色是 `link:*` 属性） |

- 这些边**怎么走**由 `plugin/edge_semantics.yaml` 声明（**属值数据，BKN 不得引用**）：`transitive`（可传递：`feeds` / `runs_on` / `subclass_of`）/ `compositions`（跨类型复合：`registered_on ∘ runs_on`）/ `symmetric`（无向）/ `inherited_domains` ＋ `inherited_incoming_domains`（子类可继承的域，出边与入边两侧）/ `walk_policy`（可穿边 **25 种** / 停止前缀 `skill:` `log:` `dimension:` `mechanism:` / `max_depth=5` / `max_paths=12`）。本体只声明边，走法归工具层。
  - ⚠️ **`reverse_ok` 已于 2026-10-13 删除**（`C-20261013-04`，裁定「不能推就删」——它既无消费方，又与实现矛盾）。**勿再把它写进语法说明**。
  - **数值唯一源 ＝ `plugin/edge_semantics.yaml`**；改边走法必须同批改 `skill/bkn-plugin/references/edge-semantics.md`、`doc/capability/ontology-inference.md` §3 与 `doc/build/demo-product-bkn/24-bkn_ontology.md` §3.1/§3.3（2026-10-15 已按此收口）。
- 机制层的**内容**当前按证据纪律留空（机制集与父类集为空，映射规则为空是设计状态）；填机制须 ≥3 个独立案例支撑，**不要凭一两个案例反推**。
