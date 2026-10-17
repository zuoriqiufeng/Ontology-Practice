---
name: demo-product-bkn
description: Demo Product 产品业务知识网络（本体层）。当用户询问 Demo Product 产品相关问题（产品介绍、架构原理、方案设计、兼容性、运维诊断、操作执行）时加载。
---

# Demo Product BKN · 业务知识网络（本体层）

> Demo Product 数据流复制管理软件的业务知识网络（Business Knowledge Network）
> 作为 Agent 数据层面的 Source of Truth
>
> **分层**：本体层（本目录 .bkn）= 定义（类/属性）+ 关系（边）+ 实例登记（带 ID 的有限表）；
> 不可抽象的内容**下延**延展层——值数据 → Skill references；路由 → Tool/`plugin/skill_manifest.yaml`；
> 全量知识 → Qdrant 检索（`store:*`）；叙述 → `doc/`。本体只保留**值委托指针**。

## 触发条件

以下任一信号命中时加载本 BKN：

| 信号 | 加载范围 |
|------|---------|
| "Demo Product" / "数据流复制" / "CDC同步" | `product.bkn` → 按需展开 |
| 数据库同步场景 (Oracle→MySQL/OB/PG...) | `objects/scenario-*.bkn`（方案骨架；逐方案优势/拓扑选择 → `skill:demo-product-migration-designer`） |
| 产品选型 / 竞品对比 (vs OGG/DSG/Kettle) | `product.bkn` 定位段 + `skill:demo-product-product-knowledge/references/product.md`（值委托） |
| 架构原理 / 全量增量 / 事务一致性 | `objects/*.bkn`（进程对象）+ `relations/process_topology.bkn`（拓扑边）+ `skill:demo-product-product-knowledge/references/architecture.md`（值委托） |
| 兼容性 / 版本 / 对象支持 | `objects/database.bkn`（DB 对象段）+ `skill:demo-product-migration-designer/references/compatibility.md`（值委托） |
| 错误码 (-4073/-4016/-4071...) | **码只作入口**：含义规则在 `plugin/error_semantics.yaml`（有界语义类别，按日志消息文本命中）→ 维度 → 经 `diagnosed_by`/`observed_in` 推 Skill 与日志；模式与处置在 `store:log_patterns_collection`（别名归一在 `plugin/constants.py`） |
| 操作执行 (创建规则/启停/节点/比对) | `actions/` → `relations/action_routing.bkn` (Object→Action→Skill 映射) |
| 方案设计 (迁移/双活/容灾/大数据) | `objects/scenario-*.bkn` → `relations/` 跨层展开 |
| 部署/安装/升级 (控制机/工作节点/etcd/数据库) | `skill:demo-product-product-deploy` / `skill:db-deploy` / `skill:demo-product-addons-deploy`（值委托） |
| 环境问题 (端口不通/磁盘满/时钟漂移/形态未知) | `objects/dimensions.bkn`（维度注册集）→ `skill:demo-product-product-deploy/references/env-issues.md`（值委托） |
| 容量/巡检/运维排障 | `objects/host.bkn` + `objects/dimensions.bkn` + `risks/` → 对应 skill 值委托指针 |
| 网络/链路（端口不通、控制台不可达、节点离线） | `objects/netlink.bkn`（链路注册集）+ `relations/topology.bkn`（connects_to）→ `skill:demo-product-product-deploy`（端口/防火墙值委托） |
| 控制机/许可/控制台认证 | `objects/controlnode.bkn` → `skill:demo-product-list-lic` / `skill:demo-product-proxytest`（值委托） |
| 链路诊断 (连接不通/增量没同步/全量慢/LOB/DDL报错) | `suspected_in` 边 → `relations/process_topology.bkn` 进程链（诊断指引在排查 Skill） |
| 按库运维 (Oracle归档/PG WAL/崖山锁) | `objects/database.bkn` → `skill:oracle-db-ops` 等（值委托） |
| License/控制台MCP/etcd规则状态 | 各 Skill frontmatter `triggers:` → `skill:demo-product-list-lic` 等（值委托，同址化） |
| **推理类问法**（谁依赖谁 / 影响面 / 传递链 / 关联查询 / 图里能推出什么 / 为什么推不出根因） | 出口 `resolve_relation`（`direction` / `relation_type` / `depth`）＋ 每跳依据 `from`/`edge`/`to`/`way`；**使用方式与能力边界一律 → `skill:bkn-reasoning`**（值委托：口径与上限由该 skill 及其 references 给出，**本体层不复制任何数值**） |

## 加载策略

渐进式披露，不一次性加载全部：

```
Step 1: 加载 bkn/SKILL.md（本文件）
Step 2: 按信号匹配加载对应 .bkn 文件（objects/ actions/ risks/ relations/）
Step 3: 需要跨层关联 → 加载 relations/ 目录（KWeaver 段落，关系类型见 RELATION_TYPES.md）
Step 4: 需要「怎么做」的值数据 → 按段内 `skill:` / `store:` 指针 下延到 Skill references / Qdrant
Step 5: 若 BKN 数据不充分 → 回退 Qdrant（`store:demo-product_collection`，逐维度补查）
```

## 目录结构

```
bkn/
├── SKILL.md                 ← 本文件: 触发条件 + 加载策略
├── SCHEMA.md                段类型/载荷/命名空间规范（本体层写作基准；**命名空间全量清单 = §0.1 唯一全文源**）
├── SYNONYMS.md              同义词维护规范（别名同址化）
│
├── objects/                 ← 对象: 有什么（★ 全部对象定义收拢于此）
│   ├── — 业务对象 —
│   ├── syncrule.bkn         同步规则 (状态机/属性/生命周期)
│   ├── dbnode.bkn           数据库节点
│   ├── worknode.bkn         工作节点
│   ├── compare.bkn          表比较任务
│   ├── — 运行时进程对象（9.0 规范 7 进程，`process:*` 命名空间 + 拓扑边承载）—
│   ├── iatrack.bkn / iadumper.bkn / ialoader.bkn / iahelper.bkn / iamonitor.bkn / iadiff.bkn / iaproxy.bkn
│   ├── — 环境·结构·网络 —
│   ├── host.bkn             主机对象（进程运行底座）
│   ├── controlnode.bkn      控制机部署单元（webconsole/iaproxy/etcd/postgres 构成）
│   ├── netlink.bkn          网络链路注册集 (`link:*` 常数；端口值委托 Skill)
│   ├── dimensions.bkn       检查维度类集 (`dimension:*` 8 个, WHAT 轴)
│   ├── — 数据库对象 —
│   ├── database.bkn         9 种 DB 对象段（源端/全量/增量方式 + 指针）
│   ├── — 场景（`scenario:*`）—
│   ├── scenario-dual-active.bkn      数据库双活 (含两地三中心/跨平台迁移子场景)
│   ├── scenario-bigdata-pipeline.bkn 大数据采集分析
│   ├── scenario-topology-patterns.bkn 拓扑模式速查
│   ├── — 注册集与产品（实例登记/类定义）—
│   └── product.bkn          产品本体 (定位/核心能力/适用场景; 对比/指标下延 Skill)
│
├── actions/                 ← 可执行动作: 能做什么
│   ├── rule_lifecycle.bkn   规则生命周期 (7个Action)
│   ├── node_lifecycle.bkn   节点生命周期 + 数据库注册 (4个Action)
│   ├── db_lifecycle.bkn     数据库节点管理 (4个Action)
│   ├── compare_lifecycle.bkn 表比较 (4个Action)
│   ├── failover.bkn         灾备切换 (1个Action)
│   ├── iadebug.bkn          iadebug 调试诊断 (9个Action)
│   └── proxytest.bkn        控制机 RPC 验证
│
├── risks/                   ← 风险约束: 什么不能做
│   ├── constraints.bkn      操作约束登记 (L0 常驻 / L2 写操作时加载)
│   └── 操作前置（risk 段；示例见 examples/example-product/）
│
├── relations/               ← 跨类型关系: 怎么关联 (KWeaver 段落, 整目录入图)
│   ├── RELATION_TYPES.md    关系类型字典
│   ├── topology.bkn         runs_on / registered_on / connects_to（结构链）
│   ├── process_topology.bkn 进程拓扑 + 归路边 (feeds/supervises/consumes/produces/monitors/suspected_in/has_class)
│   ├── scenario.bkn         supports / requires / constrains / implements / risks_of
│   ├── action_routing.bkn   implements_skill / constrained_by / risks_of
│   └── references.bkn       has_action / references / prerequisite
│
└── templates/               ← 新增内容的模板 (object/action/relation/risk/scenario/error)
```

> **诊断/网络/结构职责**：诊断清单（错误码/症状锚点表）不建——**规范 ID 空间归边**
> （`suspected_in`/`has_class`），别名下沉 `plugin/constants.py`（与 `DB_ALIASES` 同层），
> `objects/dimensions.bkn` 精简为维度类集；诊断原则并入 `risks/constraints.bkn`；
> **新增网络（`objects/netlink.bkn` + `connects_to` 边）与控制机（`objects/controlnode.bkn`）**，
> 补齐「单元 + 链路 + 承载」结构链。
>
> **四元终态**：段类型 = entity/action/risk/relation（与 KWeaver 四元一一对应），
> `scenario` 等历史类型不属本体（沿革见 90-history 迭代记录）。
>
> **目录 = 4 个核心类别 + templates**：原 `processes/` `environment/` `operations/` `scenarios/`
> 已按其语义类别并入（进程/主机/维度/DB 对象/场景/注册集 → `objects/`；进程拓扑边 → `relations/`；
> 操作前置 → `risks/`）。**运行时对象域不再靠目录承载**——由 `process:*` 命名空间 + 拓扑边
> （`relations/process_topology.bkn`）表达；进程注册集见 `plugin/constants.py::PROCESS_IDS`。

---

## 依赖

- Qdrant 连接与集合配置：`plugin/config.yaml` + `plugin/skill_manifest.yaml`（Tool 层权威，BKN 不登记）
- 控制台地址与凭据：现场交付文档（不入库）
- 脚本：`<repo>/stream-agent/skills/demo-product-skills/`

## 迭代记录

> BKN 只含本体信息；批次演进见
> [`CHANGELOG.md`](../CHANGELOG.md)（唯一权威）。

