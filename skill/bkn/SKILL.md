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

# BKN Creator v2.4 — 业务+运维双问题域知识网络生成器（模块化）

> **26 号四元终态**：段类型白名单 **4 种**（`entity`/`action`/`risk`/`relation`，= KWeaver 四元）；
> `index`/`matrix`/`symptom`/`class`/`scenario` 均已退场（历史类型与迭代记录 → `CHANGELOG.md` 归档表）。
> **零元信息**：生成的文件不写 `source_doc`/`> 来源:`/创建与批次注记——迭代记录单独成文。
> 本体**形式**基准：`bkn/SCHEMA.md`（段类型/载荷/命名空间/零冗余的唯一口径源）；理论背景件：`doc/build/demo-product-bkn/24-bkn_ontology.md`。

## 速览

- **用途**：把自然语言需求编排为结构化 BKN 业务本体（本体层 = 定义/关系/实例登记，四元）
- **核心流程**：Step 0 问题域确认 → 三问判据 → 按模块生成 → lint 闸门
- **关键约束**：生成前先过「新增知识三问」；表格只能建实例登记；不能抽象的一律下延并留指针
- **依赖**：`plugin/scripts/lint_bkn.py`（质量闸门）、`plugin/skill_manifest.yaml`（Skill/Tool/Store 语义 ID）、`plugin/error_semantics.yaml`（码含义）、`plugin/edge_semantics.yaml`（边语义）

## 触发条件

BKN 生成 / 新建本体 / 设计知识网络 / 把文档变成 BKN / 生成 bkn / 新产品的 BKN / 把业务知识结构化

## ⚠️ 新增知识三问（最高优先级，先于一切生成）

> BKN 本体层只留本体（四元）。生成/扩展时逐条问，任一为「否」即下延：

1. **能否抽象为（类 / 属性 / 关系 / 实例）？** 能 → 上升进本体（定义段 KV / 关系边 / 实例登记表）
2. **是否随现场实例 / 客户 / 版本无上界增长？** 随实例 → 只进实例登记；无上界 → **不是本体，必须下延**
3. **不能抽象 → 下延到哪一层？** 值/命令/机制 → Skill references；路由/规则 → Tool 常量或 manifest；
   全量知识 → Qdrant（`store:*`）；叙述/历史 → `doc/`（迭代记录 → 90-history）

**硬约束（lint 有牙齿）**：段类型 4 种；定义段内只允许 KV + 实例登记表；说明性表格 → 下延；
禁止「为每个现场表现新建独立段」；分类按「怎么查」不按「什么表现」。
（完整论证见 `references/ontology-basics.md`「核心理念」；本体形式见 `bkn/SCHEMA.md`，理论背景见 `doc/build/demo-product-bkn/24-bkn_ontology.md`）

## ⚠ 新增本体准入四关（三问之后、动 `.bkn` 之前）

> 三问判「**能不能抽象**」；四关判「**够不够格进本体**」。逐关过，任一关不过 → 下延，或先攒证据：

0. **形式对位**：说得出 domain/range 吗？写得出**必要判据**吗？进得了推理吗？——不能 → 下延，不进本体
1. **有界性**：是**类**还是**实例**？随实例 / 版本 / 客户无上界 → 下延
2. **证据充分性**：独立案例 / 来源的**数量与分布**摆出来（**样本太小不得称「收敛」**）——不够 → 先攒证据
3. **全范围影响**：与既有元素**全体**对位（重叠 / 冲突 / **能否由既有元素推导**——能推导＝冗余层，不加）；并回答「带来什么**新的推理**」

**四关全过 → 出全范围论证文档 → 本体评审 → 才动 `.bkn`。**
（判据全文：`doc/build/demo-product-bkn/02-bkn_design_philosophy.md` §0 第七条；先例（反面）：机制层凭 2 案反推 6 机制自称「收敛」、
结构先行落地 → 整层撤回。）

## 模块索引（生成逻辑按需加载）

| 模块 | 文件 | 内容 |
|------|------|------|
| 1 · 基础与理论 | [references/ontology-basics.md](references/ontology-basics.md) | 什么是 BKN / 核心理念（三问全论）/ 四元核心体系 / 文件组织结构 / 与官方 KWeaver 对齐 |
| 2 · 语法规范 | [references/syntax.md](references/syntax.md) | 段类型（四元）定义语法 / Object·Relation·Action·Risk / BKN-Skill 边界硬约束 / 兜底安全网 |
| 3 · 生成模板 | [references/templates.md](references/templates.md) | 7 个业务模板（database/sync_task/topology/task_lifecycle/performance/data_safety/operational）+ 补充模式 D/E/G/H/I/Ops（**Net 已于 23 号废止**） |
| 4 · 工作流 | [references/workflow.md](references/workflow.md) | 文档驱动五步工作流 / 扩展指南（新增数据库/能力）/ profile 配套导出 / 实操示例 / 防坑与实战教训 |
| 5 · 推理接线 | references/inference-wiring.md | **「进得了推理吗」的可执行标准**：domain/range 与必要判据 / 「带来什么新的推理」/ **公理必须接线承重**（无消费者不得声明）/ **反向注入负例** / 值数据分工（公理只在 `plugin/edge_semantics.yaml`）；消费契约 ＝ 每跳 `from` / `edge` / `to` / `way`（本行按 R-1 用纯文本路径，**不新增链接**） |
| 6 · 回执与显示规范 | references/output-conventions.md | **面向人的输出形态（执行期权威件）**：摘要优先 / 一轮一种主格式 / 内部码转中文（复用 `plugin/constants.py` 别名侧车）/ 禁 emoji / 详情按需 ＋ 自检清单；**全仓规则层落点 ＝ `AGENT.md` R-3**（本行按 R-1 用纯文本路径，**不新增链接**） |

## 生成后必过审计闸门（不跑完不得交付）

1. `python3 plugin/scripts/lint_bkn.py --error-only` → `errors=0`；全量 lint 每条 warning 逐条判定（本体 or 下延）
2. 三问已过；表格已核（全为实例登记）；别名已写同址字段/常量（不写中央表）
3. 新增关系/段类型/命名空间 → 已登记 `RELATION_TYPES`/`VALID_SECTION_TYPES`/`RELATION_TARGET_NAMESPACES`，**且新命名空间已进 `bkn/SCHEMA.md` §0.1 全量清单**（漏列 → `_check_namespace_inventory_consistency` error）
4. BKN 结构变化 → Plugin Tool / `schemas.py` 同批调整（P-A：Tool 是投影）
5. **零冗余（`bkn/SCHEMA.md` §0.5）**：文件内**不得**出现批次号、日期、修改/变更记录、来源或创建注记、迁移/归档/删除说明、工作文档路径——迭代记录一律写 `CHANGELOG.md`。机检 `_check_no_meta_info`；写新文本前先自问：这句是在描述**本体现在是什么样**，还是在讲**它是怎么变成这样的**？后者一律不入 `.bkn`
6. `python3 -m pytest plugin/tests -q` → 无新增失败
7. **缺口回填**：本次是否解决了某个 `gap_log` 缺口？是 → `python3 plugin/scripts/mark_gaps_resolved.py --dry-run <码>` 确认后标记（22 号 I6；否则缺口计数永远不降）
8. **新增本体元素**（命名空间 / 轴 / 类集 / 关系类型 / 公理）→ **准入四关**全过且全范围论证文档在位（见下「新增本体准入四关」）——未过 → 下延或先攒证据，**不得边设计边落**

## 相关 Skill / 文档（值委托与去重指针）

| 主题 | 权威位置 |
|------|---------|
| 本体形式（段类型 / 载荷 / 命名空间 / 零冗余） | `bkn/SCHEMA.md` |
| 关系类型白名单 | `plugin/relations.py::RelationTraverser.RELATION_TYPES` + `bkn/relations/RELATION_TYPES.md` |
| 边语义（怎么走 / 公理） | `plugin/edge_semantics.yaml` |
| 码含义（按日志消息文本命中 8 个 `dimension:*` 语义类别） | `plugin/error_semantics.yaml` |
| Skill/Tool/Store 实现映射（`skill:` / `tool:` / `store:`） | `plugin/skill_manifest.yaml` |
| 本体理论背景（四元终态 / 解析约定 / 治理，由浅入深） | `doc/build/demo-product-bkn/24-bkn_ontology.md` |
| Plugin 内部机制 / 15 Tool / 检索与部署环境 | `skill:bkn-plugin`（开发者向） |
| 产品与原理知识 | `{product_knowledge_skill}`（对照见下「产品事实委托」段） |
| BKN 改动逻辑 | `skill:bkn-updater` |
| 迭代记录（含类型/概念归档表） | `CHANGELOG.md` |

## 产品事实委托（本 skill 只承载通用方法）

> 本 skill 只承载**通用 BKN 方法**（段类型 / 载荷 / 命名空间 / 生成流程 / 审计闸门 / 推理接线 / 输出形态）。
> **库与端口、命令与脚本路径、默认值与阈值、真实案例**等**产品事实一律不进本件**——它们由**产品 skill** 提供；
> 本件只以**占位符**引用，同一占位符在本 skill 内**含义唯一、全文件一致**（对照见下表）。

| 占位符 | 指向（当前产品示例） | 语义 |
|--------|----------------------|------|
| `{product_knowledge_skill}` | `skill:demo-product-product-knowledge` | 产品与原理知识（产品事实的落户处） |
| `{db_manager_skill}` | `skill:demo-product-db-manager` | 数据库实例管理（端口 / 字符集 / 日志配置等取值与校验） |
| `{sync_manager_skill}` | `skill:demo-product-rule-manager` | 同步任务 / 规则管理（创建、启停、删除） |
| `{node_manager_skill}` | `skill:demo-product-node-manager` | 节点安装与端口分配 |
| `{deploy_skill}` | `skill:demo-product-product-deploy` | 部署与环境问题（env-issues 等） |
| `{log_analyzer_skill}` | `skill:demo-product-log-analyzer` | 日志排障指引（四步诊断） |
| `{db_diagnostics_skill}` | `skill:demo-product-db-diagnostics` | 数据库侧诊断取值（工具与命令） |
| `{migration_designer_skill}` | `skill:demo-product-migration-designer` | 兼容性与方案取值 |

> **新产品接入**：上表只是**当前产品示例**的对照——新产品的 BKN **不沿用** Demo Product 的事实
> （库 / 端口 / 命令 / 阈值 / 案例全部作废），须为该产品**重新登记**一张占位符对照表，并给它建自己的产品 skill。
> 产品专属实例（真实案例、具体命令、产品取值）落在产品 skill 的正文里，不在本件。

## 工具速查（2026-10-18）

| 场景 | 用什么 |
|---|---|
| 一句话问答（先摘要） | `bkn_ask`（≤600 字，detail=ref 取全文） |
| 结构关系/影响面 | `resolve_relation` |
| 执行前核对前置 | `check_plan`（只读） |
| 其它 12 个工具 | 见 `doc/build/demo-product-bkn/31-tools.md` |

## References

- [ontology-basics.md](references/ontology-basics.md) — 基础与理论
- [syntax.md](references/syntax.md) — 语法规范
- [templates.md](references/templates.md) — 生成模板
- [workflow.md](references/workflow.md) — 工作流
- （另有 **31 个**历史文档已物理归档至 [references/archive/](references/archive/)（2026-10-15 实测：本目录共 36 个 `.md`（含 README 索引），已迁出 5 件产品主题件至产品 skill 的 `references/archive/`，余 31）；含档 C 的「已废止」标注件；**接线仅上列 4 个**）
- （历史版本 v2.1-v2.3 更新记录 → `90-history/bkn-changelog.md`）
