---
name: bkn-updater
description: |
  根据用户提供的更新描述或文档，自动更新 Demo Product BKN 业务知识网络及对应 Skill 的 actions.yaml。
  支持新增 Skill、操作、错误码、场景、对象、约束、原则、兼容、运维知识（部署/环境/巡检）；信息不足时向用户询问。
triggers:
  - "更新 BKN"
  - "添加操作"
  - "新增错误码"
  - "补充兼容性"
  - "把这个加到 BKN"
  - "BKN 里没有这个"
  - "BKN 缺少"
  - "新增 Skill"
  - "把 skill 加到 BKN"
  - "新增运维知识"
  - "部署/环境问题加到 BKN"
tools_used:
  - search_files
  - read_file
  - write_file
  - terminal
---

# BKN / Skill 更新器

> 通用 BKN 业务知识网络自动更新，遵循「BKN 给思路，Skill 给具体设计」的分层原则。
> **26 号四元终态 + 零元信息**：BKN 文件除本体外不写来源/演进注记；迭代记录 → `CHANGELOG.md`。
> 本体论基准：`bkn/SCHEMA.md`（本体形式口径）；本体理论背景件：`doc/build/demo-product-bkn/24-bkn_ontology.md`。

## 速览

- **用途**：把用户描述或文档中的新知识同步写入 BKN 和对应 Skill
- **核心流程**：识别类型 → 提取信息 → 查重 → 备份 → diff 预览确认 → 写入 BKN + Skill → 验证 → 重启生效
- **关键约束**：写入前必须备份 + 展示 diff；新增追加不覆盖；写入后验证格式；**不写来源/演进注记**
- **依赖**：`BKN_ROOT` 路径（默认 `<repo>/demo-product-bkn/bkn/`，首次不确定时询问用户）
- **插件架构**：`skill:bkn-plugin`（开发者向权威：13 Tool + RiskGuard hook）

---

## 生效方式与发布（三种变动、三种生效）

| 变动类型 | 改哪层 | 生效方式 |
|---|---|---|
| **BKN 数据**（`.bkn`：对象 / 动作 / 风险 / 关系 / 实例登记） | `bkn/**` | 重载进程内图 ＋ **重启常驻服务进程**（见下「作用域更正」） |
| **Skill 文本**（`SKILL.md` / `references/**`） | `skill/<name>/**` | Agent **下次加载自动生效**（无需重载 BKN） |
| **Plugin 代码**（`plugin/*.py`、`constants.py`、`schemas.py`） | `plugin/**` | 需要**重启 Hermes 服务**加载新代码 |

> ⚠️ **热重载作用域更正（2026-10-14 实测，务必按此执行）**：`plugin/scripts/reload.py`
> **只重建执行它的那个进程**的内存图；**常驻服务进程不会被它刷新**。
> 所以「BKN 改完只要 reload 一下」是**早已被实测否定的旧口径**——
> **权威动作 ＝ 重启常驻服务进程**。
> 发布前置校验、三层自检（磁盘 / 身份 / 进程）、失败三分类与回滚决策树，
> 一律见 `skill:bkn-release`（references/release-flow.md 与 references/rollback.md）。

> 📌 **路径纪律**：`bkn/**`、`plugin/**`、`skill/**`、`doc/update/**`（已于 2026-10-15 整体清理、不再是改动面）都**不是直改件**——
> 必须先落候选（`doc/optimize/pending/C-YYYYMMDD-NN/`）再 `scripts/pending_apply.py` 记名落盘。

---

## 触发条件

用户说以下任一关键词时加载：`更新 BKN` `添加操作` `新增错误码` `补充兼容性` `把这个加到 BKN` `BKN 里没有这个` `新增 Skill` `把 skill 加到 BKN` `新增运维知识` `部署/环境问题加到 BKN`

---

## ⚠️ 写之前先判：新增知识三问（最高优先级，先于决策树）

> **BKN 本体层只留本体。** 每次更新动手前，必须先过这一关——23 号方案：本体层（`.bkn`）=
> 定义（类/属性）+ 关系（边）+ **实例登记**（带命名空间 ID 的有限表）；不可抽象的一律**下延**。

**三问（逐条问，任一为「否」即下延）：**

1. **能否抽象为（类 / 属性 / 关系 / 实例）？**
   能 → 上升进本体：类/属性写定义段，关系写 `relations/` 或 `relations/process_topology.bkn` 的边，
   实例写**实例登记表**（行首带 `error:*` / `dimension:*` / `constraint:*` / `rule:*` / `symptom:*` 等命名空间 ID，
   或段内声明 `> 行 = <注册集> 实例`）。
2. **是否随现场实例/客户/版本增长？**（增长律）
   随实例增长 → 只能进「实例登记」（有限注册集 + 行）；**随客户/版本无上界增长 → 不是本体，必须下延**。
3. **不能抽象 → 下延到哪一层？**
   - 值数据（版本表/对照矩阵/命令/参数/阈值/方案优势）→ **Skill references**（`skill/<name>/references/*.md`）
   - 路由/规则表（场景匹配等）→ **Tool 层常量**（`plugin/*.py`）或 `plugin/skill_manifest.yaml`
   - 全量知识/长尾案例 → **Qdrant 检索**（`store:*` 注册集）
   - 叙述/原理/历史 → **`doc/`**
   下延后，本体只保留**值委托指针**（一行 `skill:xxx` 引用），不复制内容。

**硬约束（lint 有牙齿，违反即 error）：**

- 段类型白名单 **4 种**：`entity` / `action` / `risk` / `relation`（= KWeaver 四元；以 `plugin/constants.py::VALID_SECTION_TYPES` 与 `bkn/SCHEMA.md` §0 为准）——
  **`index` / `matrix` / `symptom` / `class` / `scenario` 均已退场**（lint `_check_retired_terms` 报 error 并提示去向）。
- 定义段（entity/action/risk/relation）内**只允许** KV 属性列表 + 实例登记表；
  说明性/对照性表格（「方案优势」「比对机制」「关键属性」式小表）→ 下延 Skill。
- 禁止「为每个现场表现新建独立段」（如 `## 错误码 xxx`）——实例走登记表加行。

**判断顺序：**

1. 属于**业务域**（对象/动作/约束/场景）还是**诊断域**（症状/错误码/进程/维度）？
2. 业务域 → 三问 ①；是本体语义 → 按决策树正常写入。
3. 诊断域 → **不建表**：在 `relations/process_topology.bkn` 补 `suspected_in` 边（跨切面补 `has_class` → `dimension:*` 边）；`plugin/constants.py` 补 `ERROR_ALIASES` / `SYMPTOM_ALIASES` 别名；码含义规则进 `plugin/error_semantics.yaml`，**不需升级人工确认**；
   归不进任何维度 → `dimension:unknown` + `gap_log`（兜底是一等公民）。
4. 分类时按「**怎么查**」分类，**不按「什么表现」**分类。

> 完整论证见 `doc/optimize/14-symptom-ontology-design.md` §1.1 / §1.4 / §2.1–2.4；双层定位见 `doc/_archived/optimize-plans/19-ontology-routing-separation.md`（已归档）；细则见 `doc/build/demo-product-bkn/11-design_rules_checklist.md` 规则 1。

> 🔒 **更新后必过审计闸门（不跑完不得收尾）**
>
> 先跑 error 闸门，必须 `errors=0`：`python3 plugin/scripts/lint_bkn.py --error-only`
> 再跑全量 `python3 plugin/scripts/lint_bkn.py`，**每条 warning 都要逐条判定**「业务域：索引列举还是本体；诊断域：登记还是扩类」——warning 视为未决，不得默认放过。
>
> **「本次更新漏了知识结构纪律」的 4 种典型形态与检出项：**
>
> | 漏项形态（更新时最易漏） | 检出项 | 改法 |
> |---|---|---|
> | 为接住新现象，新增了 `index` / `matrix` 段或说明性表格 | `_check_section_types`（废止类型，**error**）/ `_check_no_explanatory_tables`（定义段内非实例登记表，**error**） | 实例 → **登记表加行**（`error:*` / `symptom:*` / `dimension:*` 等命名空间 ID）；说明性内容 → **下延 Skill references**（值数据）/ Tool 常量（路由）/ Qdrant（全量知识）。**本体只留值委托指针** |
> | 新错误码/新症状写成新段或**重建清单表** | `_check_alias_constants`（别名常量里出现边上没有的 ID → error）+ 人工核对 `relations/process_topology.bkn` 的 `suspected_in`/`has_class` 边 | 两步：① `process_topology.bkn` 补边（**边 = 规范 ID 空间权威**）；② `plugin/constants.py` 的 `ERROR_ALIASES`/`SYMPTOM_ALIASES` 加「口语 → 规范 ID」一行；完整 6 属性**查库**（`store:log_patterns_collection#错误码`），**不写进 BKN**（25 号） |
> | 关系目标写裸名/中文实例名（`-4073`、`risk:脏数据`） | `_check_relation_target_namespace` | `error:<码>` / `risk:<snake_case>`。**B-域对象类用裸名合法**（如 `dbnode`）；**不要用节点名编码角色**（如 `dbnode:source`），角色应表达为边类型 |
> | 新增了段类型 / 关系类型 / 命名空间前缀但没登记常量（**静默丢弃，不报错**） | 段类型/关系类型未登记 → `_check_section_types` / `_check_relation_file`（**error**）；命名空间注册表幽灵键 → `_check_namespace_registry_consistency`（**error**，批 4-1）；命名空间**清单漏列** → `_check_namespace_inventory_consistency`（**error**，2026-10-14） | 同步登记 `plugin/constants.py`（`VALID_SECTION_TYPES` / `RELATION_TYPES` / `RELATION_TARGET_NAMESPACES`）**并**把新命名空间补进 `bkn/SCHEMA.md` §0.1 的**全量清单**（唯一全文源；漏列 → `_check_namespace_inventory_consistency` **error**）。若结构变了，对应的 Plugin Tool 与 `plugin/schemas.py` **同批**调整（**P-A：Tool 是 BKN 的投影，不是适配器**） |
> | 为接住新叫法，把同义词/别名追加到**中央表**或新建分表 | 人工核对 `bkn/SYNONYMS.md` 宿主表 | 别名写进**同址字段**：对象/进程→`objects/*.bkn` frontmatter `aliases:`（进程对象注册集 `PROCESS_IDS`）；动作→`actions/*.bkn` 段内 `- aliases:`；DB→`plugin/constants.py::DB_ALIASES`；症状/错误码/维度→`plugin/constants.py`（`SYMPTOM_ALIASES` / `ERROR_ALIASES` / `DIMENSION_ALIASES`，值数据层，25 号下沉）；场景→`objects/scenario-*.bkn` 关键词行；运维→各 `skill/*/SKILL.md` frontmatter `triggers:`（**不进 BKN**）。**禁止给 lint 加豁免**，也不要换存储格式 |
> | 凭记忆/文档猜错误码含义或边走法 | `plugin/error_semantics.yaml`（码含义：按日志**消息文本**命中 `dimension:*` 有界语义类别）/ `plugin/edge_semantics.yaml`（边走法/公理：可传递、复合、无向、反查、展开策略） | 含义只在 `error_semantics.yaml` 的**有界语义类别**里定（查不到 → `dimension:unknown`，不许猜）；边怎么走只在 `edge_semantics.yaml` 声明——**不在 Skill/文档里另立一套** |
>
> **决策树每条路径的收尾动作都是「跑闸门」**：`新增 Skill` / `新增错误码` / `新增操作` / `新增运维知识` 等均按上表自查后再收尾。
> 特别注意（25 号方案）：**`class:*` 命名空间已退场**——诊断目标为 `process:*`（进程对象，`suspected_in` 边）或 `dimension:*`（检查维度类集，`objects/dimensions.bkn`）；**错误码/症状不进 BKN 清单**——规范 ID 空间由边承载，别名在 `plugin/constants.py`（值数据层），BKN 只有诊断指引；跨库检查点下延 `skill:demo-product-db-diagnostics/references/db-checkpoints.md`。扩维度须 gap 证据 + 评审。
>
> 理论基准见 `bkn/SCHEMA.md`（本体形式口径）与 `doc/build/demo-product-bkn/24-bkn_ontology.md`（本体理论背景件）；执行记录见 `doc/optimize/16-ontology-remediation-plan.md`。

---

---

## 更新类型决策树

```
用户输入含...
  ├── "新增 Skill" / "新 skill"          → 新增 Skill    → skill/<name>/ + bkn/actions/ + bkn/relations/action_routing.bkn
  ├── 错误码 (-4xxx)                    → 新增错误码    → relations/process_topology.bkn 补 suspected_in 边 + constants.ERROR_ALIASES 加别名（25 号：不建清单）；完整 6 属性查库
  ├── 新症状 / "出现...现象" / "报...错"   → 新增症状      → relations/process_topology.bkn 补 suspected_in 边 + constants.SYMPTOM_ALIASES 加别名；归不进维度 → dimension:unknown + gap_log
  ├── 新维度 / "应该归个新类"             → 新增维度      → **默认拒绝**：扩维度是评审制，须 dimension:unknown + gap_log 反复证明才评审；日常新问题一律落实例登记（锚点行 + 补边）
  ├── "某进程问题" / "某个进程" / 进程名（iatrack/ialoader/iadumper/iahelper/iamonitor/iadiff/iaproxy） → 进程诊断 → 不写 BKN（进程是常数集），用 `diagnose_db_link(process=进程名)` 走进程推导链（20 号方案：进程 → 上下游 + 日志 + 工具类别）
  ├── "场景" / "方案"                    → 新增场景      → objects/scenario-<id>.bkn（**entity 段** + `scenario:` 命名空间，26 号归档） + relations/scenario.bkn
  ├── "操作" / "能执行..."               → 新增操作      → actions/ + relations/{references,action_routing}.bkn + Skill actions.yaml
  ├── "对象" / "实体"                    → 新增对象      → objects/ + relations/references.bkn
  ├── "约束" / "禁止" / "不能"           → 新增约束      → risks/constraints.bkn 登记表加行（动作级）+ relations/action_routing.bkn 补 constrained_by 边（25 号：表 = 边绑定的 ID 属性登记；全局/对象级约束进「全局约束」KV 段）
  ├── "兼容" / "版本支持"                → 补充兼容      → **下延**：`skill:demo-product-migration-designer/references/compatibility.md`（值数据）；本体侧只在 `objects/database.bkn` 保留 DB 对象定义事实
  ├── "部署/安装/升级/巡检/环境问题/容量" → 新增运维知识  → 语义锚点文件正文**指针**（值委托型，见「值委托型接线」节）；环境分层知识在 `skill:demo-product-product-deploy/references/env-issues.md`，不进 BKN
  └── 混合                              → 按类型逐个处理
```

---

## 模块索引（改动逻辑按需加载）

| 模块 | 文件 | 内容 |
|------|------|------|
| 1 · 工作流 | [references/workflow-steps.md](references/workflow-steps.md) | 工作流程 Steps 1-8 + 更新类型详解（新增 Skill / 操作 / 值委托型接线） |
| 2 · 格式规范 | [references/formats.md](references/formats.md) | BKN 格式规范（Action / actions.yaml / 诊断域登记（边与别名，非条目）/ 关系条目）+ 完整示例 2 个 |
| 3 · 登记 checklist | [references/checklist.md](references/checklist.md) | 应拒绝场景 / 登记完整性 checklist / 接线判据 / 注意事项 |
| 4 · 码含义语义 | `plugin/error_semantics.yaml` | 错误码含义规则（按日志**消息文本**命中 8 个 `dimension:*`，有界；查不到 → `dimension:unknown`，不许猜） |
| 5 · 边走法/公理 | `plugin/edge_semantics.yaml` | 边语义字典（可传递 / 复合 / 无向 / 展开策略）——只读求值器怎么走；**声明必须接线承重、无消费者不得声明**（标准见 `skill/bkn/references/inference-wiring.md`） |
| 6 · 速查 | references/quick-reference.md | 「我想… → 改什么文件 → 是否需生效」21 行场景表 ＋ 文件改动范围树 ＋ 热重载命令（含**作用域更正**） |
| 7 · 案例回填模板 | references/case-registration-template.md | 案例登记 9 栏表 ＋ 三条硬规则（观测原文逐字 / 独立性三判据 / 反证）——现场唯一手工回填入口 |

> **新增诊断原则（`rule:*`）**：进 `risks/constraints.bkn`「全局约束与诊断原则」段（与约束同段，`rule:` 前缀，不补边）。
> **迭代记录**：批次变更写 `90-history/bkn-changelog.md`，不写进 BKN 文件。

## References

- [workflow-steps.md](references/workflow-steps.md) — 更新工作流
- [formats.md](references/formats.md) — 格式规范与示例
- references/checklist.md — 登记完整性 checklist
- references/quick-reference.md — 速查表（改什么文件 / 是否需生效）
- references/case-registration-template.md — 案例登记模板（9 栏 ＋ 三硬规则）

## 相关 Skill

| Skill | 用途 |
|-------|------|
| `bkn-plugin` | 查询 BKN 架构与 Tool 体系（开发者向） |
| `demo-product-migration-designer` | 方案设计 |
| `demo-product-log-analyzer` | 日志分析（诊断指引执行层） |
| `demo-product-iadebug` | 进程级调试（新增 Skill 示例） |

> 理论基准：`bkn/SCHEMA.md`（本体形式口径）；本体理论背景件：`doc/build/demo-product-bkn/24-bkn_ontology.md`（本体层/延展层分层与抽象律）。
