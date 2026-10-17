# BKN 类型枚举标准（SCHEMA）

> 本文档定义 BKN 中所有类型枚举的标准值，是 `.bkn` 文件编写与解析的唯一参考。
> 机器可读常量定义在 `plugin/constants.py`（lint 脚本从该文件导入，不解析本文档）。
> 两者必须保持一致——修改枚举时两边同步。

---

## 0. 段类型与目录

> **段类型终态**：本体层只留本体——段类型白名单 **4 种**，
> 与 KWeaver 四元（Object/Relation/Action/Risk）一一对应：
> `index`/`matrix`、`symptom`/`class`、`scenario`（三者均不属段类型白名单；方案类对象 = entity 定义）
> 均已退场，历史类型见 `CHANGELOG.md` 归档表。
> 目录只留 **4 个核心类别 + templates**（原 `processes/` `environment/` `operations/` `scenarios/`
> 已按语义类别并入，见 `bkn/SKILL.md` 目录树）。
> 本节是唯一口径源；`plugin/constants.py::VALID_SECTION_TYPES` 与之逐字对齐。

### 0.1 段类型枚举（4 种）

| 段类型 | KWeaver 四元 | 含义 | 示例 |
|--------|-------------|------|------|
| `entity` | Object | 对象/类定义（含 id/定义/关键属性）+ 实例登记集（含方案类对象：`scenario:` 命名空间） | `objects/*.bkn` 各 Object 段、`objects/scenario-*.bkn`、`objects/dimensions.bkn` 维度注册集 |
| `action` | Action | 可执行动作定义 | `actions/*.bkn` 各 Action 段 |
| `risk` | Risk | 风险/约束/原则/前置定义 | `risks/` 下的约束表段与前置维度段（示例见 examples/example-product/） |
| `relation` | Relation | 关系边定义 | `relations/*.bkn`（含 `process_topology.bkn`）各 Relation 段 |

> **四元终态**：`scenario` 不属段类型白名单（方案类对象 = entity 定义 + `scenario:` 命名空间，
> 边引用不受影响）；历史类型见 `90-history/bkn-changelog.md` 归档表。

> **命名空间约定（目录不再承载语义）——全量清单（唯一全文源）**
>
> 依据：**有哪些 ID，由边或注册集承载**；本表回答「**哪个命名空间归谁hosting**」。
> 机检 `_check_namespace_inventory_consistency`：本体实际在用的命名空间 ⊄ 本表 → **error**。
> 复现（次数列仅供参考、**不机检**）：`python3 plugin/scripts/lint_bkn.py --error-only`。
>
> | 命名空间 | 性质 | 宿主（权威源） | 次数/件 |
> |---------|------|---------------|--------------------|
> | `skill:*` | 值委托/能力路由指针 → Skill | `plugin/skill_manifest.yaml` 的 `skills:`（Tool 层权威，本体只引用 ID） | 166 / 29 |
> | `process:*` | 运行时进程对象 | `objects/<id>.bkn` + 注册集 `plugin/constants.py::PROCESS_IDS` | 80 / 12 |
> | `dimension:*` | 跨切面检查维度（有界常数） | `objects/dimensions.bkn` 注册集 | 54 / 11 |
> | `scenario:*` | 方案类对象（**entity 段**，非段类型） | `objects/scenario-*.bkn` | 52 / 3 |
> | `action:*` | 可执行动作 ID | `actions/*.bkn` 段内 `capability:` 字段（**边与文件同址**） | 39 / 1 |
> | `symptom:*` | 症状 ID 空间 | **边**（`suspected_in` / `has_class`）；别名 `plugin/constants.py::SYMPTOM_ALIASES` | 24 / 6 |
> | `link:*` | 网络链路（有界常数） | `objects/netlink.bkn` | 21 / 3 |
> | `architecture:*` | 架构能力节点 | **仅边**（`implements`，`relations/scenario.bkn`） | 20 / 1 |
> | `risk:*` | 无码风险边界 | `risks/*.bkn` + **边**（`risks_of`） | 15 / 2 |
> | `product:*` | 产品类对象 | `objects/product.bkn` + **边**（`supports` 源） | 15 / 1 |
> | `operation:*` | 运维操作节点 | **仅边**（`prerequisite`，`relations/references.bkn`）+ `actions/*.bkn` | 12 / 1 |
> | `log:*` | 取证日志 | **边**（`observed_in` 目标） | 8 / 1 |
> | `compatibility:*` | 场景兼容性条目 | **仅边**（`constrains`，`relations/scenario.bkn`）；**值数据归属待收口**（见漂移清单） | 8 / 1 |
> | `constraint:*` | 动作级约束 ID | `risks/constraints.bkn` 登记表 + **边**（`constrained_by`，映射用裸名） | 8 / 1 |
> | `rule:*` | 诊断原则（无动作绑定，Risk） | `risks/constraints.bkn`「全局约束与诊断原则」段 | 7 / 1 |
> | `target:*` | 场景目标系统 | **仅边**（`implements`） | 4 / 1 |
> | `topology:*` | 拓扑形态节点 | **仅边**（`implements`） | 4 / 1 |
>
> 上表 **17** 个 = 本体 40 件（objects/relations/actions/risks，**不含 templates**）实测在用全集。
> 另有 3 个**合法但本体零出现**的命名空间，一并在此登记（不计漂移）：
>
> - `error:*` —— **只作入口、不作知识**（§2.6）：码不进本体，含义走 `plugin/error_semantics.yaml` 的有界语义类别，别名 `plugin/constants.py::ERROR_ALIASES`；
> - `store:*` —— 检索源，Tool 层权威（§0.4），本体只写引用 ID，故仅出现在 `templates/`；
> - `tool:*` —— 查询工具，Tool 层权威（`plugin/skill_manifest.yaml`），本体无边目标。
>
> **运行时对象域由命名空间 + 拓扑边表达，不靠目录。**
>
> **值数据分工制**：别名类值数据一律在 Tool 层 `plugin/constants.py`，本体只留「边 + 类定义」——
> `DB_ALIASES`（库名）/ `ERROR_ALIASES`（错误码口语）/ `SYMPTOM_ALIASES`（症状口语）/ `DIMENSION_ALIASES`（维度旧称）；
> 规范 ID 空间（有哪些码/症状/维度）由**边**承载（`relations/process_topology.bkn`），
> 别名常量出现边上没有的 ID → lint error。
> **`index` / `matrix` 已废止**：导航职能下延 Tool 层 / SKILL.md；交叉矩阵下延 Skill references；
> 视图由边派生；机制说明/操作指引下延 Skill。**本体层 = 定义 + 关系 + 实例登记**。
> `lookup`（归一表：现场说法 → 类）**已否决，不登记**：通用说法归 `has_class` / `suspected_in` 边 +
> 段内 `aliases`，检索归向量/BM25 兜底。

### 0.2 载荷规则（定义段内只允许三类）

| 载荷 | 规则 |
|------|------|
| KV 属性列表 | `- 属性名: 值`，或单实体属性表 `\| 属性 \| 值 \|` |
| **实例登记表** | 行首列为带命名空间 ID（`error:*` / `symptom:*` / `constraint:*` / `dimension:*` / `process:*`），段内声明 `> 行 = <注册集名> 实例`；列 ⊆ 该实体已声明字段 |
| 定义性散文 | 限长 ≤3 行 |

**表格硬规则**：定义段内出现表格，**必须是实例登记表**（行首带命名空间 ID）；说明性表格
（方案优势/比对机制/状态机对照/机制说明/操作指引等）一律下延 Skill——lint `_check_no_explanatory_tables` 校验。

两条硬约束（受 lint 校验）：
- **约束 A（行必须有 ID）**：内嵌表每行须对应一个有 ID 的登记项（`error:*` / `constraint:*` …）；无 ID 的自由文本行不是合法载荷。
- **约束 B（列不得自由叙述）**：列须为该实体已声明字段；未声明列 → lint 报 error。

> **论证性散文**（>3 行的推理/背景）不是合法载荷——须收窄为要点或下延 Skill/文档。

### 0.3 常量集分工制（P3 唯一事实源）

同一常量集**禁止两处定义**，按性质分工：

| 常量集性质 | 权威点 | 例 |
|-----------|--------|----|
| 业务本体常量 | **BKN 内注册集**（权威点唯一，即实例登记表） | `symptom:*` / `error:*` / `process:*` / `dimension:*` / `constraint:*` / `link:*` |
| 检索源身份 | **Tool 层**（`plugin/skill_manifest.yaml` 的 `stores:`；BKN 只引用，见 §0.4） | `store:*` |
| 元模型 / 校验枚举 | `plugin/constants.py` | `KNOWN_DBS`、`VALID_SEVERITY`、`VALID_SECTION_TYPES` |

引用带前缀消歧：`dimension:*`（BKN 注册集）/ `constants:NAME`（代码常量）。注册集须机器可枚举；**注册集以外的数据（版本值、检查点明细、机制说明）不下延进 BKN**（原则：能抽象才进本体）。

### 0.4 检索源引用（`store:` 命名空间）

诊断方向层的「查哪」用 `store:` 语义 ID（检索源在 Tool 层：`manifest.resolve_store_id` 解析，`get_evidence_sources` 产出）：

| 写法 | 语义 |
|------|------|
| `store:xxx` 裸 ID | 集合级兜底 |
| `store:xxx#主题维度` | 维度级检索（如 `store:log_patterns_collection#日志模式`） |

- `store:` 注册集 = 知识资产身份（**Tool 层权威**：`plugin/skill_manifest.yaml` 的 `stores:`；BKN 只引用 ID，不登记实例表）；**连接参数（host/port/物理集合名）留 `plugin/config.yaml`**（分工制）。
- 引用示例：`- **检索源**: store:demo-product_collection → store:log_patterns_collection#日志模式`（有序证据源）。


---

### 0.5 零冗余规则（`.bkn` 不得含任何元信息）

> **用户裁定**：`.bkn` 文件必须格式明确、内容整洁干净，**不得出现任何冗余信息**。
> 生效日与执行记录见 `CHANGELOG.md`。

`.bkn` 只承载**本体内容与必要指引**。**以下一律不得出现**（lint `_check_no_meta_info` 机检）：

| 类别 | 说明 |
|------|------|
| 批次/方案号引用 | 以「N 号方案」「批 N-M」等形式指涉内部演进批次 |
| 日期 | `YYYY-MM-DD` 形式的演进日期（**产品版本号不算**，如「9.0 起」） |
| 修改/变更/修订/更新记录 | 任何形式的记录块；文件的变更历史不属本体内容 |
| 迁移/归档/删除说明 | 说明「原在哪个文件、现移到哪、什么被删了」的演进动词 |
| 来源/创建注记 | 标注内容从何而来、何时创建、由何处汇聚 |
| 工作文档指针 | 指向优化方案目录、草稿目录、构建文档等**非本体**路径 |

**迭代记录的唯一去处**：`CHANGELOG.md`。

**允许（不属冗余）**：

- 定义 / 属性 / 关系映射 / 实例登记（§0.2 的三类载荷）；
- **值委托指针**（`skill:*` / `store:*`）——它指向执行层与检索层，是本体的一部分；
- `⚠️ 待核` / `待补` 等**证据状态**标注（它是诚实的元数据，不是演进注记）；
- **机制说明**（lint 规则、白名单、注册集归属）——解释当前如何校验，非历史；
- **产品版本语义**——如「9.0 起装载侧仅 ialoader」；
- **原则锚点**：指向**本体内规范件**（如 `SCHEMA.md`）的引用是合法指引；**不得以文档号**（doc/ 侧的「N 号」）作锚。

**适用范围（三档）**：

| 档 | 文件 | 强度 |
|----|------|------|
| **内容（从严）** | `bkn/{objects,actions,risks,relations}/*.bkn` | 上表全部禁止 |
| **规范件（去装饰）** | 本文件、`bkn/SKILL.md`、`bkn/SYNONYMS.md`、`bkn/relations/RELATION_TYPES.md` | 保留规则陈述与必要的退场结论；去掉批次号/日期装饰，沿革统一指向 changelog |
| **模板（去装饰）** | `bkn/templates/*` | 保留「怎么做」的操作指导；去掉批次号 |

> **过渡期机制**：机检对照 `plugin/scripts/lint_bkn.py::KNOWN_META_INFO` 豁免清单（清单同时就是清理 TODO，
> 可用 `lint_bkn.py --list-meta-info` 重新生成）；**清理落地后清单清空，检查转严**。
> 豁免键含行内容片段——该行一旦被编辑，豁免自动失效并重新报错（刻意如此，防陈旧豁免）。

## 1. Object 属性类型

用于 `objects/*.bkn` 属性表的 `类型` 列。

| 类型 | 说明 | 示例 |
|------|------|------|
| `string` | 字符串 | rule_uuid, rule_name |
| `decimal` | 数值 | delay, amount |
| `integer` | 整数 | port, thread_count |
| `boolean` | 布尔 | full_sync_enabled |
| `datetime` | 日期时间 | create_time, start_time |
| `enum` | 枚举（须列可选值） | status: STOP/RUNNING/ABNORMAL |
| `object` | 嵌套对象 | source, target |
| `array` | 数组 | tables, columns |
| `json` | JSON 对象 | config, params |

使用规则：
1. 枚举类型必须列出可选值：`status | enum | 是 | 规则状态 | STOP/RUNNING/ABNORMAL`
2. 对象类型建议说明结构：`source | object | 是 | 源端配置 | {name, type, ip}`
3. 数组类型建议说明元素：`tables | array | 否 | 同步表列表 | [{schema, name}]`

---

## 2. Relation 关系类型

用于 `bkn/relations/*.bkn` 的 `关系类型` 字段。机器可读白名单以 `plugin/relations.py` 的 `RelationTraverser.RELATION_TYPES` 为准（共 29 种，**全部入 graph**）。

### 2.1 业务域关系类型（14 种，入 graph）

> **定位**：业务本体关系，入本体图，**本体评审制**——新增关系语义须评审并更新本表与 `RELATION_TYPES`。
> 评审前置＝**新增本体准入四关**：① 形式对位（说得出 domain/range、写得出必要判据、进得了推理）② 有界性（随实例/版本/客户无上界 → 下延）
> ③ 证据充分性（独立案例/来源的数量与分布；**样本太小不得称「收敛」**）④ 全范围影响（重叠 / 冲突 / **能否由既有元素推导**——能推导＝冗余层，不加）。
> **先出全范围论证文档，后动 `.bkn`**；新增命名空间 / 轴 / 类集同规。

| 类型 | 中文名 | 粒度 | 说明 |
|------|--------|------|------|
| `runs_on` | 运行于 | 类型级 | 对象运行于节点 |
| `registered_on` | 注册于 | 类型级 | 数据库注册到节点 |
| `supports` | 支持 | 类型级 | 产品/架构支持场景 |
| `requires` | 依赖 | 类型级 | 场景依赖架构/能力 |
| `constrains` | 约束 | 类型级 | 兼容性约束场景 |
| `implements` | 实现 | 类型级 | 主体实现技术/架构 |
| `has_action` | 拥有动作 | 类型级 | 对象拥有动作 |
| `references` | 引用 | 类型级 | 对象引用对象 |
| `prerequisite` | 前置 | 类型级 | 场景前置操作 |
| `implements_skill` | 绑定Skill | 实例级 | action 绑定 Skill |
| `constrained_by` | 受约束于 | 实例级 | 动作受约束条件 |
| `risks_of` | 面临风险 | 实例级 | 动作/场景面临风险 |
| `reads_from` | 读取自 | 实例级 | 规则读取的数据库节点（源端角色由边类型承载） |
| `writes_to` | 写入 | 实例级 | 规则写入的数据库节点（目标端角色由边类型承载） |

### 2.2 运维域关系类型（3 种，入 graph）

> **定位**：诊断路由关系，入路由图，**登记制**——新增边只加行（`relations/process_topology.bkn` 归路边区），
> 不属本体评审范围；仅新增「关系语义」才动本表与 `RELATION_TYPES`。

| 类型 | 中文名 | 粒度 | 说明 |
|------|--------|------|------|
| `has_class` | 归类 | 实例级 | 症状/错误码归入检查维度（`dimension:*`）（**逐步由 `suspected_in` 替代**） |
| `diagnosed_by` | 诊断由 | 类级 | 检查维度由哪个 Skill 负责（`dimension:*` → `skill:*`） |
| `observed_in` | 取证于 | 类级 | 检查维度的取证日志（`dimension:*` → `log:*`），**有序**（= 查看顺序） |

### 2.2b 运行时对象域关系类型（6 种，入 graph）

> **定位**：对象轴——**进程拓扑为主干**，替代「按错误分类」的分类轴。
> 新增实例（新进程、新拓扑边）只加映射规则行；
> 仅新增「关系语义」才动本表与 `RELATION_TYPES`。

| 类型 | 中文名 | 粒度 | 说明 |
|------|--------|------|------|
| `feeds` | 数据流向下游 | 实例级 | `process:*` → `process:*`，数据流下游（有序 = 链路方向） |
| `supervises` | 生命周期管理 | 实例级 | `process:*` → `process:*`，拉起/停止/监控 |
| `consumes` | 读取数据 | 实例级 | `process:*` → `dbnode`，从库读**数据**（源端，数据流） |
| `produces` | 写入数据 | 实例级 | `process:*` → `dbnode`，向库写**数据**（目标端，数据流） |
| `monitors` | 状态监控 | 实例级 | `process:*` → `dbnode`，只读**状态**不读数据（与 `consumes` 区分） |
| `suspected_in` | 嫌疑进程 | 实例级 | `symptom:*` / `error:*` → `process:*`（**替代 has_class**） |

### 2.2c 结构域关系类型（1 种，入 graph）

> **定位**：部署单元与链路——`runs_on` 承载关系（对象/单元/进程 → 底座）+ `connects_to` 链路两端。
> 新增实例（新链路、新承载）只加映射规则行；仅新增「关系语义」才动本表与 `RELATION_TYPES`。

| 类型 | 中文名 | 粒度 | 说明 |
|------|--------|------|------|
| `connects_to` | 连接 | 实例级 | `link:*` → `controlnode` / `worknode` / `dbnode`，链路两端各一条（无向；方向/协议/端口角色是 `link:*` 属性） |

### 2.2d 机制因果域关系类型（4 种，入 graph）

> **定位**：机制层——**故障模式的因果与层次**。本节管「事件如何传播」：直接 / 间接因果、表现、类层次。
> **当前内容留空**（机制集与父类集为空）——本节是**位置**；机制类落 `bkn/objects/`（**裸名 entity 类**）。
> 新增机制只加映射规则行；仅新增「关系语义」才动本表与 `RelationTraverser.RELATION_TYPES`。

| 类型 | 中文名 | 粒度 | 说明 |
|------|--------|------|------|
| `triggers` | 直接触发 | 类型级 | 机制 → 机制，A 的发生**直接导致** B（直接因果） |
| `amplifies` | 放大传导 | 类型级 | 机制 → 机制，A **放大或经传导加剧** B 的后果（间接因果） |
| `manifests_as` | 表现为 | 类型级 | 机制 → `symptom:*` / `dimension:*`，机制在观测面上的表现 |
| `subclass_of` | 是……的子类 | 类型级 | 类 → 类，类层次；**自身传递** |

### 2.2e 机制屏障域关系类型（1 种，入 graph）

> **定位**：机制层——**屏障**。与 2.2d **分开的理由是方向语义**（见下）。
> 当前内容留空；机制类落 `bkn/objects/`。

| 类型 | 中文名 | 粒度 | 说明 |
|------|--------|------|------|
| `mitigated_by` | 受屏障于 | 类型级 | 机制 → 约束（**裸名约束 ID**，如 `cannot_delete_RUNNING`）/ 动作：阻止或削弱该机制的屏障 |

> **两侧为何分开（方向语义）**：子类**继承父类的出边**，两侧都成立（父类会做的，子类都会）；
> 但**入边继承只限 2.2d 因果侧**——「A 触发子机制 ⇒ 也触发了父机制」成立，
> 而屏障挂在**具体机制**上、其目标又是裸名约束 ID（**不是类、无后代**），故不参与反向传播。

> **入口开放性约定**：2.1 / 2.2 / 2.2b / 2.2c / 2.2d / 2.2e 均为**入口**，新增实例（症状、错误码、日志、动作绑定、进程、拓扑边）
> 只需在对应 `.bkn` 的 `映射规则` 区追加一行，**不改关系类型、不改解析器、不需本体评审**。
> 只有在「新增一种关系语义」时才需要动本表与 `RELATION_TYPES`。

### 2.3 废止（原「人类可读关系，不入 graph」）

`diagnosed_by` / `routes_to` / `uses_tool` 原被定义为「仅人类可读、不入 graph」。
复核结论：该决策使 O-域关系**在设计上存在、在解析上被掐断**
（`RelationTraverser` 的 `if rel not in RELATION_TYPES: continue` 静默丢弃）。
本次废除该档：`diagnosed_by` 入 graph；`uses_tool` 曾入 graph、核实无消费者后移除；`routes_to` 取消
（症状→action 路由由 `action_routing.bkn` 与 Skill 的 `{db}.md` 两处持有，不设第三份副本）。

---

## 3. Risk 风险类型

用于 `bkn/risks/*.bkn` 的 `risk_type` 字段（或约束表格的「类型」列）。

| 类型 | 中文名 | 说明 |
|------|--------|------|
| `threshold` | 阈值 | 数值超过/低于阈值触发 |
| `state_prerequisite` | 状态前置 | 对象状态不满足时触发 |
| `param_constraint` | 参数约束 | 参数值不合法时触发 |
| `forbidden_sequence` | 禁止序列 | 操作顺序错误时触发 |
| `resource_limit` | 资源限制 | 资源不足时触发 |
| `compatibility` | 兼容性 | 版本/配置不兼容时触发 |
| `data_loss` | 数据丢失 | 可能导致数据丢失 |
| `performance` | 性能风险 | 可能导致性能下降 |

**边界规则**：BKN 中 risk 的触发条件用自然语言描述；结构化 rule（阈值/枚举/回滚细则）属 Skill 层，不得写入 BKN。

## 3.1 约束ID 命名约定（RiskGuard 自动翻译依赖）

`constraints.bkn` 的「约束ID」列是机器可读键，`plugin/risk_guard.py` 按以下约定把
`state_prerequisite` 类型约束**自动翻译为代码校验**（新增约束只改 BKN 不改代码）：

| 模式 | 含义 | 推导的 forbidden_states | 示例 |
|------|------|------------------------|------|
| `cannot_<verb>_<STATE>` | 某状态下禁止动作 | `{STATE}`（RUNNING 含运行族 FULLSYNC） | `cannot_delete_RUNNING` |
| `cannot_<verb>_not_<STATE>` | 非某状态时禁止 | 对象全部状态 - `{STATE}` | `cannot_modify_not_STOPPED` |
| `<obj>_must_be_<STATE>` | 必须为某状态 | 归属对象全部状态 - `{STATE}` | `worknode_must_be_ONLINE` |
| `<desc>_<STATE>`（尾缀） | 必须为某状态（变体） | 归属对象全部状态 - `{STATE}` | `both_nodes_NORMAL` |

- 状态归属对象：`ONLINE/OFFLINE → worknode`，`NORMAL → dbnode`，`RUNNING/FULLSYNC/ABNORMAL/STOPPED → syncrule`；
- 「关联」列格式 `对象.动作`（如 `SyncRule.delete`），映射表在 `risk_guard.py:_ASSOC_TO_ACTION`；
- 约束文本中的错误码用 `(-XXXX)` 标注，会被提取为 `error_code` 字段；
- 无法按约定推导的约束ID 会被跳过并记 debug 日志，不影响其他规则；
- BKN 解析失败或为空时，RiskGuard 回退到内置兜底规则（护栏不失效）。

---

## 4. Risk 严重程度

用于 `severity` / `风险级别` 字段。

| 级别 | 中文名 | 说明 |
|------|--------|------|
| `info` | 提示 | 仅供参考，不影响操作 |
| `warning` | 警告 | 需要注意，可能影响结果 |
| `critical` | 严重 | 必须处理，否则操作失败/数据丢失 |

> 历史文件中出现的 CRITICAL/HIGH/MEDIUM 逐步归一到三级枚举（critical/warning/info 映射：CRITICAL→critical, HIGH→warning, MEDIUM→info）。

---

## 5. Action 访问类型

用于 `bkn/actions/*.bkn` 的 `access_type` 字段（P1 阶段启用）。

| 类型 | 说明 | 示例 |
|------|------|------|
| `read` | 只读操作 | 查询规则状态 |
| `write` | 写入操作 | create_sync_rule, start_sync_rule |
| `admin` | 管理操作 | activate_node, failover |

## 5.1 Action 绑定类型（binding_type）

用于 `bkn/actions/*.bkn` 的 `binding_type` 字段（P3 预留）。

| 类型 | 说明 | 状态 |
|------|------|------|
| `skill` | 绑定到 Skill（`implements: skill:xxx`） | 当前唯一启用值 |
| `mcp` | 绑定到 MCP 工具 | 预留，未启用 |
| `local` | 绑定到本地函数 | 预留，未启用 |
| `api` | 直连 API | 预留，未启用 |

> 当前所有 Action 均为 `binding_type: skill`。预留其余三值为未来直连执行留扩展口，
> 启用前需评审与「Skill 独占可执行内容」边界的关系。

---

## 6. chunk_mode（search_qdrant）

用于 `search_qdrant` Tool 的 `chunk_mode` 参数。

| 值 | 说明 | 使用场景 |
|----|------|----------|
| `mini_first` | 默认策略，BGE 搜 mini → 回源 standard | 精确查询 |
| `auto` | 全量 BGE+BM25，向后兼容 | 兼容旧行为 |
| `parent_expand` | 附加 large 大块上下文 | 宏观问题 |
| `standard_image` | 搜 standard+image | 涉及图片 |
| `large_only` | 仅搜 large | 高层次总结 |

---

## 7. confidence（Tool 返回）

| 值 | 说明 | Tool 行为 |
|----|------|-----------|
| `full` | BKN 数据充分 | 直接返回 |
| `partial` | 有数据但不充分 | 标记 gaps + Qdrant 补充 |
| `none` | BKN 无数据 | Qdrant 兜底 |

---

## 8. ContextLoader 策略

用于 `plugin/context_loader.py` 的 `STRATEGIES`。

| 策略 | 说明 | 适用 Tool |
|------|------|-----------|
| `raw` | 直接 JSON 输出 | diagnose_error |
| `trim_only` | 只裁剪冗余字段 | design_solution |
| `toon_only` | 紧凑格式化 | query_product, explain_architecture |
| `full` | 先裁剪再格式化 | check_compatibility, list_scenarios 等 |

---

