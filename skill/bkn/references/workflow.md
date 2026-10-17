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

# BKN 生成工作流（模块 4/5）

> 文档驱动五步 / 扩展指南 / 实操示例 / 防坑。

---

## 文档驱动五步工作流（骨架先行）

BKN 的知识结构不依赖 Skill 是否存在。**知识先沉淀，技能后绑定，二者独立演进。**

### Step 0: 问题域确认（生成前必做，不默认绑定）

先与用户确认本次生成覆盖哪些问题域（用 clarify 提问，勿默认）：

| 组合 | 适用场景 |
|------|---------|
| 仅业务（B） | 业务问答/方案设计/兼容查询型 BKN，无交付运维诉求 |
| 仅运维（O） | 部署交付/排障知识沉淀，业务语义已有他处承载 |
| 业务+运维（B+O） | 少数场景（Agent 全场景接管），**须用户明示** |

- 确认结果记入该 BKN 的 `SKILL.md` 自描述（覆盖范围声明）。
- 阶段 1-5 的输入源、提问清单、产出层按已确认域裁剪：**未选的域不采集、不产出、不接线**。
- 决策记录写入项目设计文档（谁、何时、选了什么域），后续迭代不重复问但可改域。
- 案例：本项目（首个产品 BKN）经用户确认 = B+O（2026-09-20）；新产品逐次确认，不沿用。

```
输入文档（按 Step 0 选域取材）
  B-域: 产品文档 / 业务文档
  O-域: 部署手册 / 升级手册 / 排障案例 / 运维报告
    ↓ 阅读、提取
结构化知识（对象 / 动作 / 风险 / 关系）
    ↓ 生成骨架
.bkn 文件（skill 映射可为占位符 skill:<待补充>）
    ↓ 后续迭代
回填 implements: skill:<具体名称>，补 relations 中的 action→skill 映射
```

| 阶段 | 输入 | 做什么 | 产出 |
|:--:|------|------|------|
| 1. 文档提取 | B-域: 产品白皮书、技术手册、配置指南、产品页面；O-域(按选域): 部署手册、升级手册、排障案例/运维报告、监控告警规则 | B-域: 有什么对象？能做什么操作？有什么约束？O-域: 怎么部署/环境要求？怎么升级回退？容量/巡检怎么判？症状怎么分层？ | 四要素草稿 |
| 2. 骨架生成 | 提取的知识 | 按 Object/Action/Risk/Relation 组织为 `.bkn` 文件；生成 relations 关系图；skill 映射写 `skill:<待补充>` | 完整 BKN 目录 |
| 3. 场景补充 | 案例文档、方案白皮书 | 提取业务场景（双活/迁移/大数据等），写入 objects/scenario-*.bkn + relations/scenario.bkn | 场景层 |
| 4. 诊断 + 运维补充 | 排障手册、FAQ、错误码文档；O-域(按选域): 部署/升级案例、环境问题实录、巡检项清单 | B: 诊断知识点 → `objects/*.bkn` 进程对象与 `relations/process_topology.bkn` 归路边 + `objects/dimensions.bkn` 类集 + `risks/constraints.bkn` 诊断原则；完整定义 → Qdrant；O: 部署锚点、环境要求骨架、巡检项 → `objects/host.bkn` + 值委托指针 | 本体层（锚点/注册集）+ 值委托 |
| 5. 技能绑定 | Skill 开发完成 | 回填 `implements: skill:<具体名称>`，补 relations 中的 action→skill 映射 | 完整 BKN→Skill 链路 |

### 阶段 1 提问清单

```
Object: 这个业务领域有哪些核心"东西"？每对象关键属性是什么？对应底层哪些数据源？
Action: 围绕每对象能做什么操作？前置条件是什么？结果与影响范围是什么？
Risk:   哪些操作有风险？级别如何？什么条件触发？约束行为是什么（禁止/必须）？
Relation: 对象A与B是什么关系？对象可执行哪些动作？动作绑定什么 Skill（暂不知用占位符）？
O-部署:  这套系统部署在什么环境？有哪些环境硬要求（端口/字符集/时钟/磁盘等基线，只取语义不抄值）？
O-升级:  升级/回退路径与阶梯是什么？前置校验与回退触发条件？
O-容量:  容量/性能的判读方向与告警线语义是什么（给方向与阈值语义，不抄具体值）？
O-排障:  症状如何分层定位？每层责任面归谁（本层/BKN/Skill/平台方）？
```

> **按 Step 0 选域裁剪**：仅选 B 时 O-部署/O-升级/O-容量/O-排障四问跳过；仅选 O 时业务四问跳过；B+O 全问。

### 占位符约定

当 Skill 尚未开发或名称未确定时，使用统一占位符：

```markdown
- implements: skill:<待补充>
```

- `skill:<待补充>` 是合法的 BKN 值——解析器不应视为错误。
- `bkn/relations/action_routing.bkn` 的 `implements_skill` 段映射规则行也用同样占位：`` `action:create_sync_rule` → `skill:<待补充>` ``。
- 阶段 5 时只需把 `<待补充>` 替换为具体 Skill 名称。

> 旧的"识别 Object → 建模 Relation → 定义 Action → 识别 Risk → 组装"线性步骤仍可作为单文件内的写作顺序；但项目级生成应遵循上面的文档驱动五阶段，避免无源资料时凭空编字段。

---


---

## 最佳实践

1. **渐进式设计** — SKILL.md 给入口与加载策略，详细定义分层存放（索引由 Tool/目录派生，不写索引段）
2. **Risk 优先** — 先定义约束再定义操作, 安全第一
3. **BKN 是参考不是必选项** — 常规操作直接执行, 不确定时才查阅
4. **Action 只引用 Skill** — implements: skill:xxx, 不写命令/脚本, BKN 稳定 Skill 可变
5. **四要素根级 + 诊断域归并** — objects/actions/risks/relations 在根目录（KWeaver 规范）；诊断域内容按语义并入 `objects/`（进程对象、维度类集）与 `relations/process_topology.bkn`（归路边）；**无 `diagnostics/` 目录**
6. **BKN + Qdrant 互补** — BKN 给结构推理, Qdrant 给内容细节 (BM25+BGE RRF 混合搜索)
7. **Markdown 可读** — 业务人员能看懂, Agent 能执行
8. **版本管理** — BKN 纳入 Git, 随业务演进而更新
9. **通用优先，案例引用** — BKN 模板使用占位符（如 `{sync_manager_skill}`），避免硬编码具体产品名；举具体产品例时明确标注为示例，保持模板可复用到其他产品。


---

## 防坑

- **禁止将 BKN 注入 Persona SOUL.md**: 每次请求多消耗 2000+ token
- **BKN 是参考不是必选项**: 常规操作不加载, 遇错/写入/不懂时才查
- **优先使用 Plugin Tool 查询 BKN**: 不确定查哪个 BKN、需要解析 capability 或诊断错误码时，直接调用 BKN Plugin Tool（如 `resolve_operation`、`diagnose_error`、`get_prerequisites`）。Plugin 启动时动态扫描 `bkn/` 目录，无需 Agent 手动路由。
- **别名与基点同址维护（无中央表）**: 新增别名时改的是**基点所在文件**——对象/进程 frontmatter `aliases:` / Action 段 `- aliases:` / `plugin/constants.py`（`DB_ALIASES` / `SYMPTOM_ALIASES` / `ERROR_ALIASES` / `DIMENSION_ALIASES`）/ `objects/dimensions.bkn` 注册集「别名」列 / Skill frontmatter `triggers:`；错误码机械变体由代码派生。维护规范见 `bkn/SYNONYMS.md`。


---

## 产品级 BKN 的扩展结构（要素 × 段形态 × 域）

> 知识结构 = **要素 × 段形态 × 域**。要素为四元：objects/actions/risks/relations（`scenario` 段类型已归档，方案类对象 = entity + `scenario:` 命名空间）；
> 段形态 = `entity` / `action` / `risk` / `relation` 四种；域 = B 域（业务对象）、O 域（objects/ 的 host/database/dimensions）、
> **诊断域（检查维度注册集 `objects/dimensions.bkn` + 归路边 `relations/process_topology.bkn`）**、结构域（SKILL/SCHEMA/SYNONYMS/templates）。

KWeaver 规范定义 objects/actions/risks/relations 四要素（业务本体）。对于产品级 BKN（如当前产品示例），可叠加 **上下文层**：

```
bkn/
├── SKILL.md / SCHEMA.md / SYNONYMS.md   自描述与规范入口
├── objects/              ★ 四要素（业务对象 / 进程对象 / 主机 / 维度注册集 / DB 对象 / 场景 / 诊断注册集 / 产品）
├── actions/              ★ 四要素 (implements: skill:xxx)
├── risks/                ★ 四要素（constraints + prerequisites）
├── relations/            ★ 四要素（关系类型见 RELATION_TYPES.md，整目录入图）
└── templates/            新建文件模板
```

上下文层提供叙事和业务视角，四要素提供可执行的语义骨架。两者不冲突。
O-域（部署/环境/巡检）知识落 `objects/`（`host.bkn` 主机、`dimensions.bkn` 维度注册集、`database.bkn` DB 对象）
与值委托指针，一律值委托给 Skill——是否采集由 Step 0 选域决定。


---

## BKN 扩展指南（新增数据库 / 新增能力）

新增一种数据库或一类能力时，按以下顺序扩展，避免漏层：

> ⚠️ **扩展前先过「新增知识三问」关**（见「核心理念」）：能否抽象为类/属性/关系/实例？是否随实例或客户/版本增长？不能抽象的是否已下延到正确层（Skill references / Tool 常量 / Qdrant / doc）？新错误码/症状默认补边（`relations/process_topology.bkn` 的 `suspected_in` / `has_class` 段；入口模板 `bkn/templates/error.bkn`），禁止新增 `index`/`matrix` 段与说明性表格。

1. **对象定义**：在 `objects/` 或 `objects/` 描述新对象的属性（KV 对）与源端要求；具体配置默认值**不**写在 BKN，写"由 `skill:<manager>` 提供"。
2. **Skill 落地**：把具体端口/参数默认值/检查命令放进对应 Skill 的 `defaults.yaml` + `actions.yaml`（单一事实来源）。若尚无 Skill，先用 `skill:<待补充>` 占位。
3. **兼容性**：**不进 BKN**——版本/对象/字符集/按库约束写入 `skill:<负责 skill>/references/compatibility.md`（值数据）；本体侧只在 `objects/database.bkn` 保留 DB 对象定义事实 + 一行值委托指针。
4. **诊断操作**：新库 → `objects/database.bkn` 加对象段（逐库检查点下延 Skill）；新错误码/症状 → `relations/process_topology.bkn` 补 `suspected_in` 边（跨切面者补 `has_class` → `dimension:*`；入口模板 `bkn/templates/error.bkn`，模式 E）（默认登记不建段、不扩维度）。
5. **关系登记**：若是 action capability，Action 自描述写 `actions/*.bkn` 的 `implements: skill:<name>`，路由边登记在 `bkn/relations/action_routing.bkn` 的 `implements_skill` 段 `映射规则` 区：`` `action:<capability>` → `skill:<name>` ``。解析器（`get_skills_for_action`）据此把 capability 路由到 Skill。
6. **值委托型 Skill 接线（与第 5 步并行的另一条路径，即设计文档的 5b）**：Skill 不暴露 action capability、只提供值与知识（端口矩阵、检查命令、部署步骤、环境分层思路）时走值委托——
   ① 语义锚点文件正文写"…由 `skill:<name>` 提供"指针 ② Skill 语义 ID 登记进 `plugin/skill_manifest.yaml`（用户词路由写进该 Skill 自己 SKILL.md 的 `triggers:`）
   ③ 仅其动作确属 action capability 才补第 5 步两处登记 ④ 接线验证 `grep -r "skill:<name>" bkn/` ≥1 命中（0 = 未接线）
   ⑤ `lint_bkn.py` 无 error + `reload.py`。完整流程见 bkn-updater 的「值委托型接线」节。

每步完成都跑一次：BKN 边界自检（grep 命令/SQL/端口/路径）→ `lint_bkn.py` 结构校验（无 error）→ Plugin reload → 抽样调用相关 Tool。

### profile 配套导出（多产品化改造后启用）

> 配合 `optimize/hermes-multi-product-refactor-plan.md`：新产品接入 = bkn/ 目录 + `products/<id>/profile.yaml` 两件套。
> BKN 建好而 profile 缺配时，护栏空转、DB 别名失配且无告警——生成/扩展 BKN 时须同步产出 profile 草稿。

profile 的 A 类 6 组数据中 4 组可直接从 BKN 推导，导出时逐段标注来源：

| profile 段 | BKN 推导源 | 可推导 |
|------|------|:--:|
| `db.known` / `db.aliases` | `plugin/constants.py::KNOWN_DBS`/`DB_ALIASES` + `objects/database.bkn` 对象段 | ✓ |
| `db.error_prefixes` / `noise_variants` | `plugin/constants.py::DB_ERROR_PREFIXES` + `ERROR_ALIASES`（错误码别名，25 号下沉） | ✓ |
| `risk_guard.fallback_rules` / `fallback_state_family` | `risks/constraints.bkn` 约束ID/类型列 + `objects/*.bkn` 状态 KV | ✓ |
| `dimensions.symptom_priority` | `relations/process_topology.bkn` 的 `suspected_in` 边 × `objects/*.bkn`（进程对象）关联 Skill | 部分 |
| `prereq_map` | `risks/prerequisites.bkn` + `relations/action_routing.bkn` 的 capability 清单 | ✓ |
| `risk_guard.command_patterns` / `action_aliases` | 无（运行期命令指纹） | ✗ 人工补充 |

验收：profile.yaml 草稿每段注释标注「BKN 推导」或「人工补充」；Plugin 启动日志中各段来源应为 profile，无大面积 fallback WARN。


---

## 实操示例：产品级 BKN 的目录形态

完整的产品级 BKN 实现（文件数量与对象清单随产品而变；目录 = 4 类别 + templates）: `<repo>/<product>-bkn/bkn/`

```
bkn/
├── SKILL.md                    触发条件 + 渐进式加载策略（含版本与 changelog）
├── SCHEMA.md                   段类型（4 种）/载荷/命名空间规范（本体层写作基准）
├── SYNONYMS.md                 同义词维护规范（别名同址化）
├── objects/                    全部对象：业务对象
│                               + 进程对象 + host/dimensions/database + scenario-* + product（产品名片对象）
├── actions/                    动作（含 access_type/binding_type/dangerous 标记）
├── risks/                      风险登记集 (constraints.bkn，L0 常驻/L2 写操作时加载)
├── relations/                  关系（整目录入图：topology / process_topology / scenario / action_routing / references / mechanism_causality + RELATION_TYPES.md 字典）
└── templates/                  新建 BKN 文件的标准模板（object/action/relation/risk/scenario/error）
```

> 所有 section 带 `<!-- type: ... -->` 块类型标注，取值限 **4 种**白名单
> （`entity`/`action`/`risk`/`relation`；`index`/`matrix`/`symptom`/`class`/`scenario` 均已退场）；
> **26 号零元信息**：不写 `> 来源:` / `source_doc` / 创建与批次注记——迭代记录统一写
> `CHANGELOG.md`；
> 缺口用 `> 待补充:` 显式标记；质量由 `plugin/scripts/lint_bkn.py` 强制校验。


---

## BKN 创建工作流

实际生成 BKN 的推荐流程（本次会话验证）：

1. **收集源资料**: 官网产品页 → 技术白皮书 → 实现原理文档 → 版本使用指引 → 配置手册；O-域(按 Step 0 选域): 部署手册 → 升级手册 → 排障案例与运维报告 → 监控告警规则
2. **分析提取**: 每份文档标注覆盖的**域与要素**（业务 / 运维 / 诊断 / 结构；对象 / 动作 / 风险 / 关系），记录关键信息
3. **设计结构**: 先定义四要素 (objects/actions/risks/relations)，再叠加上下文层
4. **编写文件**: 一次一个文件，先独立（product/compatibility）后关联（relations/scenarios）
5. **审查对齐**: 与 KWeaver 规范对照，与官方规范结构对照，消除冗余和冲突
6. **渐进迭代**: 补 SKILL.md → 补 missing files → 修正路径 → 更新引用

详见 [references/archive/doc-driven-bkn-design.md](archive/doc-driven-bkn-design.md)


---

## 实战教训 (2026-06-23)

- **禁止将 BKN 注入 Persona SOUL.md**: 每次请求多消耗 2000+ token, 10轮浪费 20000
- **BKN 是参考不是必选项**: 常规操作不加载, 遇错/写入/不懂时才查
- **Plugin Tool 优先，read_file 兜底**: 解析 capability / 错误码 / 关系时优先调用 BKN Plugin Tool；BKN 文件较小且加载成本可忽略时直接 `read_file` 全量读取比按关键词 `search_files` 更精确
- **两类 BKN 分工**: 操作型(skill-linked,约束/命令) + 知识型(standalone,诊断/差异) — 互补不合并
- **信号路由**: 错误码→`relations/process_topology.bkn` 的 `suspected_in`/`has_class` 边, DB名→`objects/database.bkn`, 写入→`risks/prerequisites.bkn`
- **Skill BKN 表精简**: 只列本技能专属引用, 通用知识查询统一委托给 BKN Plugin Tool

详见: [references/archive/bkn-loading-principles.md](archive/bkn-loading-principles.md)（已归档，旧路由架构） | [references/archive/bkn-plugin-skill-architecture.md](archive/bkn-plugin-skill-architecture.md)
