---
name: bkn-intake
description: "材料能不能建模 / 这批文档怎么进 BKN / 哪些该入库 / 先做预处理——按 M0–M3 定位输入成熟度、登记可定位锚点、产出待确认清单与建模清单候选三分类（对象/关系/动作），并把 OpenBKN 的材料→抽取→映射→绑定→回填链逐项对到本仓落点。"
triggers:
  - "建模输入"
  - "材料够不够"
  - "成熟度"
  - "建 collection"
  - "文档预处理"
  - "抽取对象"
  - "对象关系抽取"
  - "属性映射"
  - "资源绑定"
tools_used:
  - search_files
  - read_file
  - write_file
  - terminal
---

# BKN 输入与预处理（Intake）

> **定位**：建模**前置**环节——把业务材料变成「可建模的候选清单」，本 Skill **不产出本体元素、不写 .bkn**。
> **范围澄清（用户 2026-10-15）**：对方所谓的「数据预处理 skill」= OpenBKN 的 bkn-extract / bkn-map / bkn-bind / bkn-backfill
> （材料 → 对象关系抽取 → 属性到字段映射 → 资源绑定 → 回填）。本 Skill **正面覆盖这条数据准备链**，
> 并说清哪些我们做、哪些我们不做、为什么（逐项对照见 references/extraction-and-binding.md）。
> **不是什么**：不是 PRD / 访谈体系；不是 Qdrant 灌库脚本（本仓**没有**灌库脚本，见 doc/optimize/24-ontology-build-sources.md 源清单第 8 条）。

## 速览

| 项 | 内容 |
|---|---|
| 用途 | 定位成熟度（M0–M3）→ 登记材料 → 提问 → 出候选三分类 → 按出口交接 |
| 核心流程 | 定级 → 材料登记 → 待确认清单 → 建模清单候选 → 阶段出口 |
| 必做 | 材料登记只写**可定位锚点**；候选只写「候选」；值数据不进建模清单；过准入四关才落盘 |
| 硬门禁 | 候选指不到出处 ⇒ 降回 M1（references/input-maturity.md） |
| 不做 | 不绑数据表、不做领域分库、不写 .bkn、不灌 Qdrant、不跑 pending_apply |
| 交接 | 建模落盘 → skill:bkn；改已有知识 → skill:bkn-updater |

## 触发条件

用户出现以下任一关键词 / 意图时加载：
`建模输入` `材料够不够` `成熟度` `建 collection` `文档预处理` `抽取对象` `对象关系抽取` `属性映射` `资源绑定`

## 分流边界表

| 用户意图 | 去处 | 本 Skill 的动作 |
|---|---|---|
| 生成新本体 / 设计知识网络 | skill:bkn | 只交「建模清单候选三分类 ＋ 出处」 |
| 改已有 BKN / Skill 知识 | skill:bkn-updater | 只交候选与出处，不落盘 |
| 灌库执行 / 建 collection / chunk | 仓外 chunk 项目 ＋ 外部 skill demo-product-knowledge-ingestion（纯文本指针） | 只做**材料取舍判定与 category 标注**（是否值得入库），不执行灌库、不建 collection |
| 发布 / 版本 / 上线 | skill:bkn-release | 不参与 |
| 诊断 / 排障 / 处置 | 诊断域 Skill（如 skill:demo-product-log-analyzer） | 不适用 |
| 纯材料预处理（docx/xlsx→文本） | 本 Skill | 见 references/preprocessing.md |

> ⚠️ 「建 collection / 入库」是**仓外动作**：本仓无灌库代码路径（doc/optimize/24-ontology-build-sources.md 源清单第 8 条）。
> 本 Skill 只负责**筛选与标注**，执行交外部；本仓侧只登记 store: 语义 ID（plugin/skill_manifest.yaml 的 stores:）。

## 纪律门禁（先读，违反即返工）

**① M0–M3 降级纪律（硬）**

| 级 | 判据 | 允许动作 |
|---|---|---|
| M0 想法 | 只有方向 / 单句诉求，无材料 | **只输出澄清问题** |
| M1 素材 | 有材料，但未区分事实与假设 | 只做材料登记（可定位锚点） |
| M2 可建模 | 能支撑对象/关系/动作至少一类，且每条候选能指到出处 | 进入建模（bkn / bkn-updater） |
| M3 可评审 | 候选齐、确认状态已分层、验收判据可写 | 走评审 → 候选流程 doc/optimize/pending/ |

- **候选指不到出处 ⇒ 降回 M1**（登记为「待取证」），**不得**为凑齐写成「已确认」。
- 待确认清单状态**只允许三值**：已确认 / 待确认 / 待裁定。

**② 值数据不进建模清单**：别名、阈值、码表、公式先判「是不是值数据」——是则直接下沉侧车（Skill references / Tool 常量 / plugin/skill_manifest.yaml / Qdrant store:*），**不列为候选**（值数据分工制见 bkn/SCHEMA.md §0.1）。

**③ 过准入四关才落盘**：有界性 → 证据充分性（样本太小不得称收敛）→ 全范围影响（能推导＝冗余）→ 形式对位（domain/range 与必要判据）。四关全过才出全范围论证文档（判据全文 doc/build/demo-product-bkn/02-bkn_design_philosophy.md §0 第七条；生成侧口径 skill/bkn 的「新增知识三问 ＋ 准入四关」）。

**④ 预处理不改内容、只改形态**：抽取/换行/编码只做形态归一；**不改写原文语义**、不补写、不猜测；标题与来源文件名必须带入 payload（防 UUID 化后无法反查，见 references/preprocessing.md）。

## 模块索引（按需加载）

| 模块 | 文件 | 内容 |
|---|---|---|
| 成熟度与交接单 | references/input-maturity.md | M0–M3、材料登记、待确认清单、候选三分类、出口（全量承接 原 doc/update/70-requirement-intake.md（2026-10-15 清理）） |
| 预处理 | references/preprocessing.md | docx/xlsx→文本、编码与换行、title 保留、category 标注、二进制件、误判 binary 的坑 |
| 抽取与绑定对照 | references/extraction-and-binding.md | 对方五步（extract / domain / map / bind / backfill）逐项对照我方等价动作与落点 |
| 空白模板 | references/intake-template.md | 材料登记 / 待确认清单 / 建模清单候选三分类 / 阶段出口 四张空白表 |

## 验收闸门

| # | 闸门 | 判据 | 不过怎么办 |
|---|---|---|---|
| 1 | 成熟度已定位 | 明确写出 M0–M3 之一及其判据 | 回 §① 重新定级 |
| 2 | 锚点可定位 | 材料登记每行都有章节 / 页码 / 行号 / 时间戳 | 该行降为「待取证」 |
| 3 | 候选有出处 | 建模清单每行「出处」非空 | 该条降回 M1 |
| 4 | 状态合法 | 待确认清单状态 ∈ {已确认, 待确认, 待裁定} | 改写，不得留空或自定义值 |
| 5 | 值数据已分流 | 别名/阈值/码表/公式未出现在建模清单 | 移出并写明下沉目标 |
| 6 | 不放行越界动作 | 未写 .bkn、未灌库、未跑 scripts/pending_apply.py | 撤销并交对应责任方 |

> 输出形态遵循 `skill:bkn/references/output-conventions.md`（**执行期权威件**）：摘要优先、一轮一种主格式、内部枚举转中文、禁 emoji。
> 引用纪律遵循 AGENT.md R-1：**不写跨文档 markdown 链接**，引用一律纯文本路径 / 编号。
