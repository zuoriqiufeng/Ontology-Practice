# 推理问法目录：四类推理 × 标准问法 × 参数 × 样例输出

> **基准**：2026-10-13 bkn-20261013-3（203 节点 / 223 边 / 29 关系类型）；输出为当日真实运行结果的渲染形态，2026-10-15 复核一致。
> **读法**：工具返回体是**文本渲染**（root: / source: / by_relation / paths[N]{end,hops}:），下文样例保留了渲染后的关键行。
> **指路（纯文本）**：能力件 doc/capability/ontology-inference.md §2／§3；边语义 plugin/edge_semantics.yaml；求值器 plugin/relations.py；出口 plugin/tools.py。

---

## 0. 通用读法与参数

| 参数 | 语义（以 plugin/schemas.py 的 resolve_relation 定义为准） |
|---|---|
| source_entity | 源实体；无「:」时先过 resolve_synonym（口语 → 规范 ID） |
| relation_type | 默认 all（按关系类型分组返回 by_relation）；可给具体边类型；另有 4 个虚拟出口 diagnosis_path / process_chain / closure / impact |
| direction | out（默认）/ in（反查）/ both；**仅 depth>1 生效**；对称边（connects_to）无论 direction 一律双向走 |
| depth | 默认 1＝直查（输出与改造前逐字节一致）；>1 才追加 paths 段；schema 上限 3 |
| target_hint | 目标实体类型（skill / action / object / risk），过滤用 |

**三条读法纪律**：

1. depth>1 时 relation_type 是**可穿边过滤**；不在 walk_policy.traversable 内的类型会得到 paths_note（明说「depth>1 无展开」），不是静默空。
2. 每个可达节点给**一条最短见证路径**（hops[]），每跳 {from, edge, to, way}；way ∈ {out, in}；继承边额外带 via。
3. 「有路径」只证明「在这张已声明的图上可达」；「没路径」不证明「现实中无关」（见 references/trust-model.md 的 partial 语义）。

---

## 1. 反查：谁依赖 / 引用 X

**标准问法**：「谁依赖谁」「谁引用了我」「这个单元出问题，谁受影响」（反查口径）

**参数**：source_entity=X，relation_type=all，direction=in，depth≥2

**样例（实测）**：

```
resolve_relation(source_entity=worknode, relation_type=all, direction=in, depth=2)
→ paths[12]（12 个终点，逐条实测）：
   1 跳：syncrule        runs_on(in)        ← 跑在这个节点上的规则
   1 跳：dbnode          registered_on(in)  ← 注册在这个节点上的库
   1 跳：link:console_node / link:node_source_db / link:node_target_db   connects_to(in)
   2 跳：controlnode     via link:console_node（connects_to → connects_to）
   2 跳：link:console_db via dbnode（registered_on → connects_to）
   2 跳：process:iatrack / iadumper / iadiff    via dbnode（registered_on → consumes(in)）
   2 跳：process:ialoader                        via dbnode（registered_on → produces(in)）
   2 跳：process:iamonitor                       via dbnode（registered_on → monitors(in)）
```

**读法**：这 12 条路径跨了 6 种边（runs_on / registered_on / connects_to / consumes / produces / monitors）、3 类命名空间（裸名 / link: / process:）；其中 7 条是两跳。

**边界**：反查口径**不受 5 类承载边限制**，分母是「全图可达节点」——要「谁引用过我」就用它，不要用 impact 代替（见 §6）。

---

## 2. 跨类型复合：承载链（库 → 节点 → 主机）

**标准问法**：「这个库的承载底座是什么」「库 → 节点 → 主机」

**参数（两种，结论不同形态）**：

| 玩法 | 参数 | 结论形态 |
|---|---|---|
| 普通多跳 | source_entity=dbnode，relation_type=all，depth=3 | **无名的两跳路径** |
| 带名复合 | source_entity=dbnode，relation_type=closure | kind=composition，composition=registered_on_then_runs_on |

**样例（实测）**：

```
resolve_relation(source_entity=dbnode, relation_type=all, depth=3)
→ paths[7]：
   worknode   registered_on →
   host       registered_on → worknode -runs_on→ host     ← 两段复合，文件里没写过的结论

resolve_relation(source_entity=dbnode, relation_type=closure)
→ closure[7]：
   host,composition,[{dbnode -registered_on-> worknode, out}, {worknode -runs_on-> host, out}]
   ...（另有 symmetric 腿：link:console_db / link:node_source_db / link:node_target_db / link:console_node / controlnode / worknode —— 共 7 条）
```

**语义来源**：plugin/edge_semantics.yaml 的 compositions 声明 registered_on_then_runs_on（seq=[registered_on, runs_on]，已接线承重）；普通多跳与带名复合不冲突——多跳给「无名的两跳」，本键给「有名字的复合」。
**指路**：实现是 plugin/relations.py 的 closure()（按 seq 走完两段）。

---

## 3. 传递闭包：下游全链

**标准问法**：「这个进程出问题，下游还有谁」「传递链」「闭包」

**参数**：source_entity=process:iatrack，relation_type=all，depth=3（或 relation_type=process_chain，后者忽略 depth）

**样例（实测）**：

```
resolve_relation(source_entity=process:iatrack, relation_type=all, depth=3)
→ paths[9]：
   process:ialoader   feeds →
   dbnode             consumes →
   worknode           consumes → dbnode -registered_on→ worknode
   host / link:*      …
```

**语义来源**：plugin/edge_semantics.yaml 的 transitive=[feeds, runs_on, subclass_of]，已接线承重——plugin/relations.py 的 closure() 逐跳展开；transitive_targets() 给进程链（feeds）当闸门；类继承（subclass_of）同闸门。**摘掉声明即可观测地关闭对应传递链。**

**边界**：process_chain 出口沿 feeds 正向遍历，段上附频度 / 自证性；它是**固定形状路由**（L1），不是通用闭包，别把两者的差异算作矛盾。

---

## 4. 对称：单元 ↔ 链路

**标准问法**：「这台机器连着哪些链路」

**参数**：source_entity=worknode，relation_type=connects_to（direction 对它不生效）

**样例（实测）**：

```
resolve_relation(source_entity=worknode, relation_type=connects_to, depth=2)
→ link:console_node / link:node_source_db / link:node_target_db   （connects_to 反向）
```

**语义来源**：plugin/edge_semantics.yaml 的 symmetric=[connects_to]，已消费（plugin/relations.py 的反向求值）。

---

## 5. 机制侧问法：候选机制 ＋ 证据缺口（L4 半）

**标准问法**：「这次报错是哪个环节导致的」「候选机制是什么」「还差哪块证据」

**出口**：diagnose_mechanism(entry, observations, max_candidates)——入口归一（症状 / 错误码 / process: / 命名空间节点）→ 候选召回（manifests_as 收窄，收不到就全量并明说）→ 逐条读判据 → 收敛 → 分段输出。

**样例（实测）**：entry=dimension:resource，observations=["Killed process 58998 (java)"]

```
candidates[1]{id,state,hits,why,tier}:
  resource_exhaustion_cascade,unknown,[{type: log_text+sequence, tier: sampling, strength: hard, matched: [Killed process <pid> (java)]}],命中含 hard 但来源不独立（同源多命中只算 1）⇒ 停在 unknown
chain_note: 因果层暂不可用：机制间边 triggers/amplifies 留空 ⇒ 候选平铺
root_note: 根类 fault_mechanism 不独立出证
structural_evidence[1]{...}: dimension:resource,...,False,partial,本体侧已核：起点在上述边类型上均无参与既有关系；缺「受影响单元」，后半步须人给
treatment_hint[1]: dimension:resource → skill:demo-product-log-analyzer → references/error-code-treatment-catalog.md §五（只给「去哪一节看」，不给命令）
next_actions[1]: resource_exhaustion_cascade,sampling,jstack / 内存指标 / 内核 OOM 日志（dmesg）...
fact_vs_inference: facts[1]=判据命中原文；inference[1]=unknown（unknown 是合法答案）
silence_note: 已提供 1 条观测；未出现在观测里 ≠ 不存在
```

**规模（实测）**：机制类 5（1 根 fault_mechanism ＋ 4 子：control_plane_desync / resource_exhaustion_cascade / single_point_fail_stop / position_regression）／manifests_as 8 边／subclass_of 4 边／triggers · amplifies · mitigated_by 均 **0 边**；8 个 symptom:* 中只有 4 个被机制覆盖 ⇒ 其余只能全量平铺。

**推不出（四条）**：① 因果链与根因定论；② 「受影响单元」自动推导（structural 只核起点那半步；给了 affected_unit 才把 checkable 从 partial 变 full）；③ 处置动作推导（next_actions 是**取证**不是处置）；④ counter_check 的通用机检（含否定语义或数值比大小的仍须人判）。

---

## 6. 两个最容易混的问法（分流，裁定＝选 A）

> 背景：影响面出口覆盖 12/203（5.9%）、上限 14–16；2026-10-14 裁定**不扩边集**，先把**问法**讲清——两者**分母不同**，混用会得出「本体覆盖太差」的错误结论（依据 doc/optimize/72-impact-route-argument.md §4／§5）。

| 问法 | 入口 | 答什么 | 分母 | 覆盖 |
|---|---|---|---|---|
| **谁依赖 X**（反查） | resolve_relation(source_entity=…, direction="in") | 谁引用 / 依赖我 | 全图可达节点 | 广 |
| **X 牵连谁**（影响面） | resolve_relation(relation_type="impact") | 我这条承载链上还有谁 | 只有 5 类承载边：supervises / feeds / runs_on / reads_from / registered_on | 12/203（5.9%），上限 14–16 |

**同一起点的对照（实测）**：

```
worknode, direction=in, depth=2   → 12 条路径（syncrule / dbnode / link:* / process:*）
worknode, relation_type=impact    → by_unit 仅 3 个单元：host / syncrule / dbnode
symptom:crash_loop, impact        → by_unit 空 ＋ impact_note（覆盖边界，不是「无影响」）
```

**三条读法**：
1. 要「谁引用过我」用 direction=in——**不受 5 类边限制**。
2. impact 的口径是**运行承载**（进程↔进程 / 进程↔节点 / 规则·库↔节点），**不含知识引用**（O-域边）；当「广义影响面」用会掺噪。
3. 出口**不静默**：空结果带 impact_note（plugin/tools.py 的 impact 分支）。

**为什么不扩边集**：数据 / 文档补不成（补密新增为零）；唯一能做大数字的办法是改边的语义域——那会把「知识引用」当「运行牵连」，改变结论的含义（65 号 §8.2；72 号 §4）。

---

## 7. 出口速查（relation_type 全枚举 → 走法）

| relation_type | 走法 | 备注 |
|---|---|---|
| all | 按关系类型分组返回 by_relation；depth>1 时用 walk_policy 可穿边集展开 | 默认 |
| 任一边类型（29 种之一） | 直查该边；depth>1 时作为可穿边过滤 | 不可穿类型 → paths_note |
| diagnosis_path | O-域单跳：症状 / 错误码 → 类 / 进程 → Skill → 取证日志，一次拿全 | 忽略 depth |
| process_chain | 进程 → 上下游全链 ＋ 日志 ＋ 工具类别 | 忽略 depth |
| closure | 传递 / 复合 / 对称的只读闭包，每跳带依据；复合腿带 composition 名 | 不物化 |
| impact | 5 类承载边双向展开，按受牵连单元分组给见证路径 | 默认 depth=3、上限 3 |

**共同点**：都只读、按需求值、不写回 graph / 基线；paths 段是**追加**而非替换（depth=1 时逐字节不变）。
