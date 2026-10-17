---
name: bkn-reasoning
description: |
  谁依赖谁 / 影响面 / 传递链 / 关联查询 / 图里能推出什么——Demo Product BKN 本体的结构推理问法与边界。
  结构侧用 resolve_relation 的四类展开（反查 / 跨类型复合 / 传递闭包 / 对称）回答「文件里没写过的结构结论」，
  每跳带 from / edge / to / way 依据；机制侧用 diagnose_mechanism 给「候选机制 ＋ 还差哪块证据」。
  能推：可溯的结构结论；推不出：因果链与根因定论、现场实例事实、数值阈值、处置动作推导、条件归类。
  问「谁依赖谁」＝ direction=in；问「X 牵连谁」＝ relation_type=impact（只覆盖 5 类承载边、12/203）。
  公理只在 plugin/edge_semantics.yaml，skill 与 .bkn 都不得另立。
triggers:
  - "谁依赖谁"
  - "影响面"
  - "牵连"
  - "传递链"
  - "闭包"
  - "反查"
  - "关联查询"
  - "图里能推出什么"
  - "为什么推不出根因"
  - "A到B有没有路径"
  - "库承载在哪台主机"
  - "这台机器连着哪些链路"
  - "排障路径"
  - "取证日志"
  - "嫌疑进程"
  - "码对应的 skill"
  - "下一步查什么"
tools_used:
  - resolve_relation
  - diagnose_mechanism
  - diagnose_error
  - diagnose_db_link
  - read_file
  - terminal
---

# Demo Product BKN 本体推理（结构侧 L2 ＋ 机制侧 L4 半）

> **定位**：回答「**本体怎么问、结论怎么读、边界在哪、新推理怎么建**」——把能力件 doc/capability/ontology-inference.md 的实测结论转成可执行的问法与门禁。
> **唯一真值**：边怎么走在 plugin/edge_semantics.yaml；求值器在 plugin/relations.py，出口在 plugin/tools.py。
> **本 skill 不发明公理**：一处也不写死边语义。

## 速览

- **用途**：把「谁依赖谁 / 影响面 / 传递链 / 关联」翻成 resolve_relation 的标准调用，并如实标注边界
- **结构出口**：resolve_relation(source_entity, relation_type, direction, depth)（唯一结构出口）
- **机制出口**：diagnose_mechanism(entry, observations, max_candidates)——候选 ＋ 判据命中 ＋ 证据缺口
- **排障接力出口**：resolve_relation(relation_type="diagnosis_path")——症状/码 → suspected_in → 进程 → Skill → 取证日志（单跳一次拿全）
- **能力坐标**：L2（闭包 / 复合 / 反查 / 对称 ＋ 每跳依据）✅ 到位；L4（因果 / 机制）🟡 半落地（候选平铺，无因果排序）
- **结构量（实测）**：203 节点 / 223 边 / 29 关系类型（python3 plugin/scripts/graph_metrics.py）
- **硬上限（walk_policy 实值）**：可穿边 **25 种**、max_depth=5、max_paths=12、stop_at 4 前缀（skill: / log: / dimension: / mechanism:，**不含 store:**）；工具 schema 的 depth 上限为 **3**
- **不物化**：派生路径按需求值，不写回 graph / 基线（结构量因此不变）

## 排障接力（诊断之后必须再推理一次）

`diagnose_error` / `diagnose_db_link` 返回里出现 `dimensions` 或 `suspected_process` 非空时，**必须**再走一次推理出口，
否则只拿到「码的表层含义」，没拿到「谁该看、看哪份日志、归哪个 Skill」：

1. `resolve_relation(relation_type="diagnosis_path", source_entity="<码或症状 ID>")` —— 一次取回「命中进程 → 关联 Skill → 取证日志 → 检索源」；
2. 若问「哪个环节导致的」，走 `diagnose_mechanism(entry="<码或症状>", observations=[...])` —— 候选机制 ＋ 还差哪块证据；
3. 两条出口都只给**结构/候选**：根因定论仍走人（见下方分流边界表）。

**纪律**：`mention_resolve` 与 `reasoning_path` 只在**有 `task_id` 的真实会话**里计——探针/门禁/跑分流量不落生产轨迹（43 号 §4 铁律）。

## 触发条件

用户说「谁依赖谁」「影响面」「牵连」「传递链」「闭包」「反查」「关联查询」「图里能推出什么」「为什么推不出根因」「A 到 B 有没有路径」「库承载在哪台主机」「这台机器连着哪些链路」时加载。

## 分流边界表

| 问法 | 走哪 | 为什么 |
|---|---|---|
| 「谁和谁连着」「谁引用了我」「库 → 节点 → 主机」 | ✅ 本 skill：resolve_relation(direction=in / depth>1) | 类级 / 产品级的**结构结论**在图里，每跳可溯 |
| 「X 牵连谁」「影响面」 | ✅ 本 skill：relation_type=impact | 只沿 5 类承载边；覆盖 12/203（5.9%） |
| 「这次报错是哪个环节导致的」 | 🟡 候选机制 ＋ 取证动作走 diagnose_mechanism；**根因定论走人** | triggers / amplifies 均 0 边 ⇒ 候选平铺，无因果排序 |
| 「这个报错该看哪些日志、归哪个 Skill」 | ✅ 本 skill：resolve_relation(relation_type=diagnosis_path, source_entity=码/症状) | 对象轴（suspected_in → 进程 → Skill → 取证日志）一次拿全；未命中才退类轴 |
| 「现场这台库上有哪些规则、现在什么状态」 | ❌ 走 Skill / API（现场实例事实） | 本仓是 TBox（类级 / 产品级），ABox 无导出源 |
| 「延迟 500ms 算不算高」 | ❌ 走监控 / Skill 阈值表 | 数值阈值按设计不进本体 |
| 「这两条约束互斥吗」 | ❌ 只有 3 条编译期形状检查（D1 / D3 / D4） | 无 DL 推理机；D2 实测 0 例、按「无案例不建」不建 |
| 「某个码是什么含义」 | ❌ 走 plugin/error_semantics.yaml ＋ plugin/error_codes.yaml 的 status 闸门 | 码不进本体（Q27） |
| 「这条边怎么走、能不能传递」 | ❌ 查 plugin/edge_semantics.yaml（唯一真值） | 本 skill 与 .bkn 都不另立口径 |
| 「A → B 有没有一条具体路径」 | ⚠️ 现在**没有** find_path 出口 | 该函数已按零消费者删除；只能靠 depth>1 的 paths 段间接判「可达 / 不可达」 |

## 四类标准问法（细节与样例输出见 references/reasoning-catalog.md）

| 类 | 问法 | 参数要点 | 语义来源 |
|---|---|---|---|
| 反查 | 谁依赖 / 引用 X | direction=in，relation_type=all，depth≥2 | 方向由 walk_policy.traversable 单独提供 |
| 跨类型复合 | 「库 → 节点 → 主机」承载链 | depth=3；带名复合走 relation_type=closure | compositions 已接线承重 |
| 传递闭包 | 进程下游全链 | depth≥2（feeds 可传递）；或 relation_type=process_chain | transitive=[feeds, runs_on, subclass_of] |
| 对称 | 这台机器连着哪些链路 | relation_type=connects_to（无向，direction 不生效） | symmetric=[connects_to] |

## 纪律门禁（硬约束，违反即返工）

1. **每跳依据是契约**：读「结论」必须连 from / edge / to / way 一起读；本 skill 与任何文档**不得另立**一套走法口径——边语义只在 plugin/edge_semantics.yaml。
2. **推不出就落 unknown ＋ 检索指引，不许猜**：机制侧 unknown 是合法答案（纯软证据只能到 unknown）；码含义查不到 → dimension:unknown；图查询空结果只说明「在这张已声明的图上没有」。
3. **影响面不许说「全覆盖」**：relation_type=impact 只沿 5 类承载边（supervises / feeds / runs_on / reads_from / registered_on），实测覆盖 **12/203（5.9%）**、理论上限 **14–16** 节点；空结果必须把 impact_note（覆盖边界）一起给出，**不得**说成「无影响」。
4. **公理只在 plugin/edge_semantics.yaml**：skill/ 与 .bkn 都不得新增边语义 / 公理；bkn/** 不得引用该表（值数据下沉）。

## 模块索引

| 模块 | 文件 | 内容 |
|---|---|---|
| 1 · 问法目录 | references/reasoning-catalog.md | 四类推理 × 标准问法 × 参数 × 样例输出；两个易混问法的分流 |
| 2 · 边界清单 | references/boundaries.md | N1–N7（capability §4）＋ B1–B4 编号澄清 ＋ 分流去向 |
| 3 · 信任模型 | references/trust-model.md | 声明 ≠ 强制（信任面＝yaml 已消费键）、partial 语义、影响面与码含义的诚实口径 |
| 4 · 复现命令 | references/verify-commands.md | 可跑命令 ＋ 期望输出（结构量 / 三条现场问法 / 探针 / 轨迹汇总） |

## 验收闸门（可跑的检查，不跑完不得收尾）

1. python3 plugin/scripts/graph_metrics.py → nodes=203 edges=223 relation_types=29（结构量未漂移）
2. 三条现场问法（resolve_relation）→ worknode 反查 paths[12]、dbnode 复合 paths[7]、process:iatrack paths[9]
3. 影响面：relation_type=impact 起点不在覆盖内时，输出必须带 impact_note（不许静默空）
4. python3 plugin/scripts/ontology_probe.py → exit=0，汇总含「本体给出 111 条候选（可比 40 条），31 条进输出（78%）」
5. python3 plugin/scripts/trajectory_report.py --ontology → 真实会话本体事件 0 条（现场样本为零，不得据此宣称现场命中率）
6. 收尾前：python3 plugin/scripts/lint_bkn.py --error-only → errors=0；python3 -m pytest plugin/tests/test_edge_semantics.py -q → 14 passed

## 纯文本指路（本仓 R-1：不写跨文档链接）

| 主题 | 权威位置 |
|---|---|
| 能力现状（能推 / 不能推 / 出口） | doc/capability/ontology-inference.md |
| 边语义（唯一真值 / 公理） | plugin/edge_semantics.yaml |
| 求值器（walk / closure / 继承） | plugin/relations.py |
| 出口与影响面分支 | plugin/tools.py |
| 影响面路线论证（裁定＝选 A：先换问法） | doc/optimize/72-impact-route-argument.md |
| 本体理论侧（公理 / 坐标 / 治理） | doc/build/demo-product-bkn/24-bkn_ontology.md §3 |
