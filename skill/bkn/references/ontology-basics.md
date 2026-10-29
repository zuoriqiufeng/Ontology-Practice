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

# BKN 基础与理论（模块 1/5）

> 概念/四元体系/文件组织/与官方对齐。本体**形式**的唯一口径源 = `bkn/SCHEMA.md`；`doc/build/demo-product-bkn/24-bkn_ontology.md` 为**本体理论背景件**（由浅入深）。

---

## 什么是 BKN

BKN 是 KWeaver 定义的**面向 Agent 上下文的 Markdown 业务本体描述语言**。它不关注底层数据结构，而是关注业务领域如何被建模、组织和表达，作为 Agent 的 **Source of Truth（唯一事实来源）**。


---

## 核心理念

**问题**: 纯文本 Prompt 存在 Token 浪费、语义模糊、规则散落；且若生成理念只覆盖业务问题，
运维问题（部署/环境/升级/容量/排障）将无处安放——实际使用中大量运维问题绕过 BKN 直接打到
Skill，知识网络失去路由价值。
**方案**: 按场景选域、生成前与用户确认（Step 0：仅业务 / 仅运维 / 业务+运维，**不默认绑定**）；
对已确认的域，用 Object/Relation/Action/Risk 四元组组织知识，支持渐进式披露。
B-域答"产品是什么、怎么用"，O-域答"怎么交付、怎么运行、出问题怎么定位"——
两域共用四要素与 BKN-Skill 边界：**只给骨架/思路/指针，值与命令一律委托 Skill**。

> ⚠️ **新增知识三问（新增/扩展 BKN 的第一判据，最高优先级；23 号方案）**
>
> BKN 本体层**只留本体**。生成/扩展时逐条问这三问，任一为「否」即下延：
>
> **① 能否抽象为（类 / 属性 / 关系 / 实例）？**
> 能 → 上升进本体：类/属性 → 定义段（KV）；关系 → `relations/` 或 `relations/process_topology.bkn` 的边；
> 实例 → **实例登记表**（行首带 `error:*` / `symptom:*` / `dimension:*` / `constraint:*` / `rule:*` 命名空间 ID，
> 或段内声明 `> 行 = <注册集> 实例`；`store:*` 是 Tool 层权威 `plugin/skill_manifest.yaml`，BKN 只引用、不登记）。
>
> **② 是否随现场实例 / 客户 / 版本增长？（增长律）**
> 随实例增长 → 只能进**实例登记**（有限注册集 + 行，如维度类集、链路注册集；错误码/症状**不进清单**——25 号：边承载 ID 空间、别名进常量）；
> 随客户/版本**无上界**增长（版本对照、竞品矩阵、行业清单、逐库检查点）→ **不是本体，必须下延**。
>
> **③ 不能抽象 → 下延到哪一层？**
> | 内容形态 | 下延层 | 例 |
> |---|---|---|
> | 值数据（版本表/对照矩阵/命令/参数/阈值/方案优势） | **Skill references** | `{migration_designer_skill}/references/compatibility.md` |
> | 路由/规则表（场景匹配、Skill 归属） | **Tool 常量 / manifest** | `plugin/resolver.py::_SCENARIO_ROUTING_RULES`、`plugin/skill_manifest.yaml` |
> | 全量知识/长尾案例/完整定义 | **Qdrant 检索** | `store:demo-product_collection#错误码 → store:log_patterns_collection#错误码` |
> | 叙述/原理/历史记录 | **`doc/`** | `doc/build/demo-product-bkn/23-*.md` |
> 下延后**本体只留一行值委托指针**，绝不复制内容。
>
> **硬约束（lint 有牙齿，违反即 error）：**
> - 段类型白名单 **4 种**（`entity`/`action`/`risk`/`relation`）；`index`/`matrix`/`symptom`/`class`/`scenario` 均已退场（归档表见 90-history）；
> - 定义段内**只允许** KV 属性列表 + 实例登记表；说明性表格 → 下延；
> - 禁止「为每个现场表现新建独立段」（如 `## 错误码 xxx`）——实例走登记表加行；
> - 表象无限、语义有限：分类按「**怎么查**」不按「**什么表现**」。
>
> 形式基准 `bkn/SCHEMA.md`（本体形式的唯一口径源；`doc/build/demo-product-bkn/24-bkn_ontology.md` 为本体理论背景件）；设计规则细则见 `doc/build/demo-product-bkn/11-design_rules_checklist.md` 规则 1。

> 🔒 **生成后必过审计闸门（不跑完不得交付）**
>
> 先跑 error 闸门，必须 `errors=0`：`python3 plugin/scripts/lint_bkn.py --error-only`
> 再跑全量 `python3 plugin/scripts/lint_bkn.py`，**每条 warning 都要逐条判定**「业务域：索引列举还是本体；诊断域：登记还是扩类」——warning 视为未决，不得默认放过。
>
> **「漏了知识结构纪律」的 4 种典型形态与检出项：**
>
> | 漏项形态（生成时最易漏） | 检出项 | 改法 |
> |---|---|---|
> | 生成/保留 `index`、`matrix` 段（段类型已废止） | `_check_section_types`（**error**，含废止类型专属提示） | 导航 → Tool/`SKILL.md`；表格 → Skill references；视图 → 由边派生（如日志导航由 `suspected_in`+进程属性派生） |
> | 定义段内写说明性表格（方案优势/比对机制/关键属性/性能指标…） | `_check_no_explanatory_tables`（**error**） | 实例 → **登记表加行**（带命名空间 ID）；说明性内容 → **下延 Skill references**（值数据）/ Tool 常量（路由）/ Qdrant（全量知识） |
> | 关系目标写裸名或中文实例名（`<错误码>`、`risk:脏数据`） | `_check_relation_target_namespace` | `error:<码>` / `risk:<snake_case>`。注意 **B-域对象类用裸名是合法的**（如 `dbnode`），不要加前缀；也**不要用节点名编码角色**（如 `dbnode:source`），角色应表达为边类型 |
> | 关系段放错目录或缺 `**关系类型**:` 字段（**不会入图，且不报错**） | `_check_relation_file` / `_check_relation_sections_outside_dir` | 移入 `bkn/relations/` 并补字段，或显式声明「不入图」 |
> | 把同义词/别名写进**中央表**或新建分表 | 人工核对 `bkn/SYNONYMS.md` 宿主表 | 别名一律写进**同址字段**（见下），与它映射的基点同文件/同段：对象/进程→frontmatter `aliases:`；动作→段内 `- aliases:`；症状/错误码/维度→`plugin/constants.py`（`SYMPTOM_ALIASES`/`ERROR_ALIASES`/`DIMENSION_ALIASES`，26 号下沉）；数据库→`plugin/constants.py::DB_ALIASES`。**禁止给 lint 加豁免**，**也不要换存储格式** |
>
> **别名的同址字段（写这里，不写中央表）：** 对象/进程 → `objects/*.bkn`、`objects/*.bkn（进程对象）` frontmatter `aliases:`；动作 → `actions/*.bkn` 段内 `- aliases:`；数据库 → `plugin/constants.py::DB_ALIASES`（Python 侧，大小写由 `normalize_db()` 归一）；症状/错误码 → `plugin/constants.py`（`SYMPTOM_ALIASES`/`ERROR_ALIASES`）；维度 → `objects/dimensions.bkn` 类集 + `DIMENSION_ALIASES`；运维/部署类 → 各 `skill/*/SKILL.md` frontmatter `triggers:`。错误码的机械变体（`<数字码>`→`-<数字码>`、`ORA1555`→`ORA-01555`）由代码派生，**不登记**。未归表的新口语叫法靠检索兜住，高频未命中的从 `gap_log.jsonl` 反哺回上述同址字段。
>
> **工具跟随（P-A）**：BKN 结构变了（新增关系类型 / 改关系语义），对应的 Plugin Tool 与 `plugin/schemas.py` 必须**同批**调整——**Tool 是 BKN 的投影，不是 BKN 的适配器**；不得以「工具现状会坏」为由否决 BKN 规范化。
>
> **新增了段类型 / 关系类型 / 命名空间前缀？** 必须同步登记 `plugin/constants.py`（`VALID_SECTION_TYPES` / `plugin/relations.py::RELATION_TYPES` / `RELATION_TARGET_NAMESPACES`）——未登记由 lint 报 error（`_check_section_types` / `_check_relation_file` / `_check_namespace_registry_consistency`，批 4-1）。命名空间还须补进 `bkn/SCHEMA.md` §0.1 **全量清单**（漏列 → `_check_namespace_inventory_consistency` error）。
>

> 完整修复方案与各批次验收标准见 `doc/optimize/16-ontology-remediation-plan.md`；审计基线见 `doc/optimize/15-ontology-conformance-audit.md`。

> ✅ **交付前知识结构自检清单（不逐条过 = 不交付，批 4-2 / 19 号方案）**
>
> 1. `lint_bkn.py --error-only` → `errors=0`；全量 lint 的每条 warning 已逐条判定（本体语义 or 下延），无默认放过；
> 2. **三问已过**：新增内容能否抽象为类/属性/关系/实例？是否随实例或客户/版本无上界增长（增长 → 下延）？不能抽象的是否已落到正确层（Skill references / Tool 常量 / Qdrant / doc）？是否误建 `index`·`matrix` 段或说明性表格？；
> 3. **表格已核**：定义段内表格全部为实例登记（行首带命名空间 ID 或段内 `> 行 = … 实例` 声明），无说明性小表；
> 4. 新增关系类型/段类型/命名空间前缀 → 已登记 `RELATION_TYPES` / `VALID_SECTION_TYPES` / `RELATION_TARGET_NAMESPACES`（4-1 幽灵键检查会拦住），**且新命名空间已进 `bkn/SCHEMA.md` §0.1 全量清单**（`_check_namespace_inventory_consistency`）；
> 5. 别名 → 已写同址字段（不是中央表）；错误码机械变体由代码派生；
> 6. 步骤细节/命令 → 已下沉 Skill，BKN 只留语义 + `implements: skill:` 指针；
> 7. BKN 结构变化 → Plugin Tool / schemas.py 同批调整（P-A 投影原则）；
> 8. `python3 -m pytest plugin/tests -q` → 无新增失败。

```
传统 System Prompt                 BKN 知识网络
─────────────────────              ─────────────────
"你是一个数据库同步助手..."         SKILL.md (Agent入口)
"规则1: 延迟超<阈值>告警..."          SKILL.md (本体入口/加载策略)
"规则2: 大表要分片..."              ├── objects/ (业务对象)
"规则3: 脱敏规则..."               ├── relations/ (对象关系)
"..."长文本...                     ├── actions/ (可执行操作)
                                    └── risks/ (风险边界)
```

> **23 号方案：本体层只留本体** —— 定义（类/属性）+ 关系（边）+ 实例登记（带 ID 的有限表）；
> 其余一律下延（值→Skill references；路由→Tool/manifest；全量知识→Qdrant；叙述→doc），本体只留指针。


---

## 四元核心体系 (v2 对齐官方) + 扩展要素（双层定位）

**业务本体**（B 域）沿用 KWeaver 四要素——声明式、封闭、评审制：

| 元素 | 含义 | 在数据库同步场景中的映射 | 运维域（O-域）映射例 |
|------|------|------------------------|-------------------|
| **Object** | 业务对象 — "业务里有什么" | 数据库实例、同步任务、表映射、列映射 | 部署单元（控制机/工作节点）、环境基线、巡检项 |
| **Relation** | 对象关系 — "如何彼此连接" | 源端/目标端、表归属任务、列归属表 | 组件依赖（etcd→控制机）、锚点→值委托指针 |
| **Action** | 可执行操作 — "能做什么" | 创建任务、启动同步、暂停、校验、告警 | 部署、升级、初始化、巡检检查 |
| **Risk** | 风险边界 — "什么条件下可以/不可以做" | 延迟超限、直连不可用、未经校验不可切换 | 环境坑判定链（按域分层，非 L 层）、升级回退边界 |

**诊断域**扩展要素（**登记制**，本体层只留锚点与注册集）——
症状/错误码**不建表**：`symptom` / `class` 段类型已退役，其 ID 空间由 `relations/process_topology.bkn` 的
`suspected_in` / `has_class` 边承载，别名进 `plugin/constants.py`：

| 扩展要素 | 命名空间 | 宿主 | 治理 |
|---------|---------|------|------|
| **Symptom** 症状 | `symptom:` | **边**（`relations/process_topology.bkn` suspected_in/has_class） | 加边即登记；别名进 `plugin/constants.py::SYMPTOM_ALIASES`（25 号：不建表） |
| **ErrorCode** 错误码 | `error:` | **边**（同上） | 加边即登记；别名进 `plugin/constants.py::ERROR_ALIASES`；完整 6 属性**查库** |
| **CheckDimension** 检查维度 | `dimension:` | `objects/dimensions.bkn` 注册集 | 扩维度评审制：gap 反复证明才扩，默认 `dimension:unknown` 兜底 |
| **Process** 进程对象 | `process:` | `objects/<id>.bkn`（注册集 `plugin/constants.py::PROCESS_IDS`）+ `relations/process_topology.bkn` 边 | 常数集（由该产品规范定义的进程集，清单见产品 skill）；目录不承载语义，新增/改属性 → 改对象段 |
| **Scenario** 场景（26 号归档） | `scenario:` | `objects/scenario-*.bkn`（`scenario-` 前缀；**entity 段**定义，`scenario:` 命名空间供边引用） | 方案类对象（评审制，同 Object） |

> **本表只覆盖诊断域**（symptom / error / dimension / process / scenario）。**全量命名空间清单（17 个）的唯一全文源**
> 是 `bkn/SCHEMA.md` §0.1 —— B/E 域的 `skill:` / `action:` / `risk:` / `product:` / `operation:` /
> `architecture:` / `target:` / `topology:` / `compatibility:` 都在那里。
> 新增命名空间时**清单与 `RELATION_TARGET_NAMESPACES` 两处都要动**，漏一处由
> `_check_namespace_inventory_consistency` / `_check_namespace_registry_consistency` 报 error。


---

## BKN 文件组织结构

BKN 遵循 KWeaver 规范的核心结构。以下为通用模板:

```
bkn/
├── SKILL.md                    # Agent 入口: 触发条件 + 加载策略
├── SCHEMA.md                   # 类型枚举标准（v1.5 起，与 plugin/constants.py 同步）
├── SYNONYMS.md                 # 同义词字典维护规范
├── objects/                    # ★ KWeaver 四要素 — 对象（带 YAML frontmatter；★ 全部对象收拢于此）
│   ├── {domain_object}.bkn     # 按领域命名 (如 syncrule, order, pod)
│   ├── <runtime_process>.bkn   # [可选] 运行时进程对象（命名空间 process:，注册集 PROCESS_IDS）
│   ├── host.bkn / dimensions.bkn  # [可选] 主机对象 / 检查维度注册集
│   ├── {db}.bkn                # [可选] 逐库对象差异段
│   ├── scenario-<id>.bkn       # [可选] 场景（scenario- 前缀，命名空间 scenario:）
│   （26 号：无诊断入口文件——清单在边、别名在 constants、指引在排查 Skill）
├── actions/                    # ★ KWeaver 四要素 — 可执行动作（含 access_type/binding_type）
│   └── {domain}_lifecycle.bkn  # 按领域分组 (implements: skill:xxx)
├── risks/                      # ★ KWeaver 四要素 — 风险约束 + 操作前置
│   ├── constraints.bkn         # 操作约束（含约束ID/类型机器可读列）
│   └── prerequisites.bkn       # [可选] 操作前置（按约束维度的 risk 段）
├── relations/                  # ★ KWeaver 四要素 — 跨类型关系（整目录入图）
│   ├── topology.bkn / process_topology.bkn   # 对象边 / 进程拓扑边
│   ├── scenario.bkn / action_routing.bkn / references.bkn
│   └── RELATION_TYPES.md       # 关系类型字典
└── templates/                  # [可选] 新建 BKN 文件的标准模板
```

> **24 号（目录收拢）**：目录 = 4 核心类别 + `templates/`；`processes/` `environment/` `operations/`
> `scenarios/` 已并入对应类别（详见 `bkn/SKILL.md` 目录树）。**运行时对象域由 `process:*` 命名空间 +
> 拓扑边表达，不靠目录**；进程注册集 = `plugin/constants.py::PROCESS_IDS`。段类型白名单 **4 种**
> （`entity`/`action`/`risk`/`relation`，四元终态）。
> 其对象与动作是该产品的同步域清单（对象类 / 动作集见产品 skill；本件只规定命名空间与写法）
>
> ⚠️ **案例 ≠ 模板**：以上文件数量与清单仅是**当前产品示例**一例的现状，不是新产品 BKN 的规范要求。
> 新产品只保证三层不变量，具体内容按该产品自身文档决定：
> - **结构契约不变**：目录骨架（objects/actions/risks/relations + templates；对象类文件全部在 `objects/`）、frontmatter 必填项、`<!-- type -->` 标注（**4 种**，四元终态）；
> - **逻辑约定不变**：29 关系类型、4 段类型、8 risk_type、约束ID 命名 `cannot_<verb>_<STATE>`、BKN-Skill 边界（禁命令/路径/端口）、`skill:<待补充>` 占位；
> - **质量门不变**：`lint_bkn.py` 无 error。
> 文件数量、对象/动作/场景/诊断内容随产品而变——某产品没有灾备切换就没有 failover.bkn，没有多 DB 支持就没有 `objects/database.bkn` 的对应对象段；Plugin 对缺失文件按"缺省放行/返回空框架"降级（见改造方案步 7 的 products/demo 最小 BKN 演练）。


---

## 与官方 KWeaver 的对齐

本 Skill v2 遵循 KWeaver 官方 BKN 规范：
- Object / Relation / Action / Risk 四元体系
- Markdown 为载体格式
- 渐进式披露模式
