# 抽取与绑定：与 OpenBKN 数据准备链的逐项对照（references/extraction-and-binding.md）

> **本件回答**：对方（OpenBKN）有完整的**数据准备/预处理**链——源材料见
> <opbkn-repo>/skills/bkn/internal/ 下的 bkn-extract / bkn-domain / bkn-map / bkn-bind / bkn-backfill 五个 SKILL.md。
> 本仓**做哪些、不做哪些、为什么**，逐项对到落点。
> **一句话结论**：**不照搬**——因为两边的「本体绑什么」不同：他们绑**数据表（Vega resource）**，我们绑**权威源**；
> 这是**分工，不是缺口**（doc/comparison/openbkn-engineering/02-ontology-model.md §4.3 与 04-gap-register.md 的 G-04：「已等价」）。

---

## 1. 逐项对照表（主表）

| 对方步骤 | 对方做什么（实证） | 我方等价动作 | 我方落点 | 我们为什么不照搬 |
|---|---|---|---|---|
| **bkn-extract** | 从业务文本提取对象/关系/动作，分四组输出（显式 / 推断 / 待确认 / 排除），每项带来源证据；对象再判存储位置 platform / local | **三问判据 ＋ 准入四关 ＋ 候选三分类**（对象 / 关系 / 动作，一律先记「候选」） | 建模清单在本 Skill `references/input-maturity.md` §4（原 doc/update/70-requirement-intake.md，2026-10-15 清理）；产物交 **skill:bkn** | 我们的出题是**「够不够格进本体」**，不是「值不值得建对象」：四组分类只解决完备性，解决不了「随实例无上界必须下延」；且我们没有 platform/local 的数据源之分（无数据源），存储位置一栏无对应物 |
| **bkn-domain** | 关键词加权评分（high=3 / mid=2 / low=1），在 supply_chain / crm_sales / project_delivery / generic 中选领域 | **不做领域分库**：单域深做 ＋ **别名归一** | 别名同址宿主：plugin/constants.py 的 DB_ALIASES / ERROR_ALIASES / SYMPTOM_ALIASES / DIMENSION_ALIASES；对象/进程别名在 objects/*.bkn 的 frontmatter aliases:；总规范 bkn/SYNONYMS.md | 我们是**单一业务域**（Demo Product），没有分库需求；多域评分会把一个词的分数当领域判据，而我们真正要的是**同一物件多种叫法 → 一个规范 ID**（靠别名侧车 ＋ BM25/向量检索兜底，bkn/SYNONYMS.md「未入表的新口语叫法不入任何表」） |
| **bkn-map** | 属性 → 数据字段映射（mapped / waived / blocked），算覆盖率 coverage=(mapped+waived)/total，出放行结论 mapping_quality | **不适用**（不绑数据表）。等价动作＝**「值数据 vs 本体」判定 ＋ 下沉目标选择** | 值数据分工制：Skill references（skill/<name>/references/*.md）/ Tool 常量（plugin/constants.py）/ plugin/skill_manifest.yaml / Qdrant store:*（bkn/SCHEMA.md §0.1、§0.3） | 属性在我们这里是**业务语义**，不落物理列（02-ontology-model.md §1.3「属性到物理列：无（属性是业务语义，不落列）」）；没有字段就没有覆盖率，硬套会造出假的映射状态 |
| **bkn-bind** | 为对象匹配 **Vega resource**，输出 bound / pending / rejected，绑值必须是 resource_id（不用名称替代） | **语义 ID 绑定**：plugin/skill_manifest.yaml 的 id → entry 映射（skill:* / tool:* / store:*） | plugin/skill_manifest.yaml（skills: / tools: / stores:）；可选字段 **bkn_contract**（objects / actions / risk_policy），由 lint 的 `_check_skill_manifest_bkn_contract` 双向校验 | 我们**没有可绑的数据源**（无源不接线）；我们的「绑定」是**声明每条知识的权威在谁手里**（bkn/SCHEMA.md §0.1 宿主列 ＋ 值数据分工制），见 02-ontology-model.md §4.2；两套标识不可互换（对方自己也有反例：dataview 的 mdl UUID 不能用于 BKN 绑定） |
| **bkn-backfill** | 把绑定/映射结果合并后写回 .bkn，写入前 prepush 预检、失败阻断，写后回读校验＋级联引用修正 | **候选流程 ＋ lint 双向校验 ＋ scripts/gate.sh** | 候选：doc/optimize/pending/C-*/payload/（**apply 须人工记名**）；校验：plugin/scripts/lint_bkn.py 与 scripts/gate.sh | 我们**不许自动写生效树**：先出候选 → 人工记名 apply；且我们的 .bkn 有零冗余规则（bkn/SCHEMA.md §0.5）与 34 项 lint 机检，回写不能「顺手改业务语义」（对方 bkn-backfill 亦有此约束，但我们要的是**可回溯的候选**而非直接落盘） |

## 2. 关键差异的判据（为什么不是缺口）

| 差异 | 判据来源 | 定性 |
|---|---|---|
| 绑数据表 vs 绑权威源 | doc/comparison/openbkn-engineering/04-gap-register.md G-04：对方 Data Source 填 Vega resource / indirect 关系填 Backing Resource；我方等价物＝SCHEMA §0.1 宿主列 ＋ 24 号 §2.5 值数据分工制 | **已等价**（形式不同，是分工不是缺口） |
| 有平台实例 vs TBox-only | doc/comparison/openbkn-engineering/02-ontology-model.md §4.3：对方能回答「这台库上跑着哪些规则」的实例问题；我们按设计去 Tool 查 | 对方更好（有平台）；但**无源不接线**（doc/optimize/56-open-items.md 丙-6 触发条件＝有 Demo Console 实例库可导出） |
| 值数据下延 vs Mapped Field | bkn/SCHEMA.md §0.3 常量集分工制：同一常量集禁止两处定义 | 口径不同；我们靠 lint 机检（34 项）而非格式约束 |

## 3. 本 Skill 在链上的位置

| 阶段 | 责任方 | 本仓落点 |
|---|---|---|
| 材料预处理（docx/xlsx→文本） | skill:bkn-intake | references/preprocessing.md |
| 成熟度定级 ＋ 材料登记 ＋ 待确认 ＋ 候选三分类 | skill:bkn-intake | references/input-maturity.md、references/intake-template.md |
| 值数据 vs 本体判定 ＋ 下沉选择 | skill:bkn-intake（判）→ 对应侧车（落） | 值数据分工制；Skill references / Tool 常量 / manifest / store:* |
| 生成新本体 | skill:bkn | bkn/ 生效树（**本 Skill 不写**） |
| 改已有知识 | skill:bkn-updater | 同上 |
| 候选落盘 | 候选流程 | doc/optimize/pending/C-*/payload/（apply 人工记名） |
| 闸门 | scripts/gate.sh | lint ＋ pytest ＋ 结构量 ＋ 基线 ＋ 回放 |

*对照材料：<opbkn-repo>/skills/bkn/internal/bkn-{extract,domain,map,bind,backfill}/SKILL.md（只读）。*
