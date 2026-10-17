# 信任模型：推理的可靠性 ＝ 声明的正确性

> **指路（纯文本）**：原文见 doc/capability/ontology-inference.md §2（声明 vs 强制）、§4-c（图消耗）、§5（信任模型）；理论侧见 doc/build/demo-product-bkn/24-bkn_ontology.md §3.1／§3.7。
> **基准**：2026-10-13 bkn-20261013-3；2026-10-15 复核。

---

## 1. 声明 ≠ 强制：信任面 ＝ yaml 里**已被求值器消费**的键

plugin/edge_semantics.yaml 是**唯一真值**，但「写在表里」不等于「机器照做」——下表逐键给出实测状态。

| 键 | 声明内容 | 是否被消费 | 消费者（实测） |
|---|---|---|---|
| symmetric | connects_to 无向 | ✅ 已消费 | plugin/relations.py 的反向求值（_targets / _sources；closure 的对称分支） |
| walk_policy | 可穿边 25 种 / 端点 4 前缀 / 深度与条数上限 | ✅ 已消费 | plugin/relations.py 的 walk / reachable |
| domains ＋ inherited_domains / inherited_incoming_domains | 关系类型归域、子类按域继承（出边 / 入边） | ✅ 已消费 | plugin/relations.py 的 _inherited_edges / _inherited_incoming_edges（失败方向：默认不继承） |
| transitive | feeds / runs_on / subclass_of 可传递 | ✅ **已接线承重** | plugin/relations.py 的 closure() 逐跳展开；transitive_targets() 给进程链（feeds）当闸门；_ancestors / _descendants 给类继承（subclass_of）当闸门——**摘掉声明即可观测地关闭对应传递链** |
| compositions | registered_on ∘ runs_on | ✅ **已接线承重** | plugin/relations.py 的 closure() 按 seq 走完，产出 kind=composition；resolve_relation(relation_type=closure) 是它对外**唯一**可见面 |
| reverse_ok | ~~哪些边允许反查~~ | ❌ **已于 2026-10-13 删除** | 声称 gate 反查，而求值器对所有可穿边一律放行 direction=in（承诺与实现矛盾）；方向由 walk_policy.traversable 单独提供。**勿重新引入**——plugin/tests/test_edge_semantics_injection.py 有 tripwire |

**结论**：**信任面 ＝ 全部语义键**（不再是「只在 symmetric / walk_policy」）；「纸上公理」在本层已清零（24 号 §5.4 R-1 消解）。**每一键都是承重项**：摘掉哪一类都会真的改变行为。

---

## 2. 声明错了**不会报错**（这是固有风险）

- 机制：机器只验证了「**链在图上走得通**」（plugin/tests/test_edge_semantics.py），**没有验证语义该不该成立**。
- 后果：一条错误声明会给出**可溯但错误**的路径——每跳依据都是真的，合成结论却是错的。影响面比代码 bug 更大（声明式推理的固有风险）。
- 最小怀疑动作：在 plugin/edge_semantics.yaml **摘除该条** → 该语义的路径**立即消失**（其余不受影响），并同批更新能力件 doc/capability/ontology-inference.md §2 / §5。
- 纪律：**加语义 ＝ 加信任面**。新增仍走 02 号 §0 第七条（先论证、评审、后落）；bkn/** 不得引用该表（值数据下沉）。

---

## 3. partial / closed 语义：空结果的两种含义

**图不是封闭世界**：图查询的空结果只证明「**在这张已声明的图上**没有」，**不能**推出「现实中不存在」。

| 场景 | 空 / 不完整的原因 | 出口必须怎么说 |
|---|---|---|
| impact 返回空 | 起点不在 12 个覆盖节点内（覆盖边界） | 带 impact_note：「返回空是覆盖边界，不是「无影响」」（plugin/tools.py 的 impact 分支） |
| 两单元间未找到路径 | 可能真无路径，**也可能结构边未补密** | diagnose_mechanism 的 two_endpoint.note 明写这两种可能 |
| structural_evidence 的 checkable | 缺 affected_unit 时只能核「起点是否在既有关系上」这半步 → partial | note 说明「缺受影响单元，后半步须人给」；给了 affected_unit 才变 full |
| 机制候选召回不全 | manifests_as 只覆盖部分 symptom（8 个中 4 个） | 收不到就**全量并明说**，不假装收窄过 |

**读法**：把「图上没有」当成「事实不存在」，是本层最容易犯的错——它会把**覆盖缺口**误报成**世界事实**。

---

## 4. 影响面：12/203 与上限 14–16（诚实口径）

| 项 | 实测 / 声明值 |
|---|---|
| 边集 | **硬编码** _STRUCTURAL_EDGES = ("feeds", "reads_from", "runs_on", "registered_on", "supervises")（plugin/tools.py） |
| 方向 / 深度 | both（承载关系正反两向都算牵连）；depth 钳 3（schema 与实现一致，walk 内部上限 5） |
| 覆盖 | **12 / 203（5.9%）**——2026-10-15 复核，12 个节点为：controlnode / dbnode / host / process:iadiff / process:iadumper / process:iahelper / process:ialoader / process:iamonitor / process:iaproxy / process:iatrack / syncrule / worknode |
| 理论上限 | **14–16 个节点**（这 5 类边只连「进程↔进程／进程↔节点／规则·库↔节点」，65 号 §8.2；转引 72 号 §1） |
| 单次代价 | **70 次图查询**（纯内存遍历；开销 +0.1～0.3 ms，输出体积 p90 不变） |
| 补密结论 | 从原理类文档补边**新增为零**（补数据 / 补文档补不了） |
| 路线裁定 | 2026-10-14 **R-6 选 A**：**不扩边集**，先讲清问法（72 号 §4／§5） |

**说不得的三句**：
1. 不许说「影响面全覆盖」；
2. 不许把 impact 的空结果说成「无影响」；
3. 不许为了把 5.9% 做上去而扩边集——唯一能让数字变大的办法是改**边的语义域**，那会把「知识引用」当「运行牵连」，**改变结论的含义**。

---

## 5. 码含义链：44/176 与 status 闸门（盘上实时口径）

**闸门是 status，不是词表**（63／64 号）：「只给码」这条路只有在 status 可信时才据表给维度，否则**一律 unknown 并把冲突写出来**（不选边）。

| 档 | 条数（plugin/error_codes.yaml，实测） | 行为 |
|---|---|---|
| status=统一 | **3 / 176**（4002 / 4016 / 4071） | 据官方含义给维度；可信档 |
| status=单源 | **44 / 176 ＝ 25.0%** | 给维度，但 evidence 前缀「单源（厂商文档，**未经现场验证**）」 |
| 其余 | **129**（无 status 126 ＋ 区分 2 ＋ 待现场复核 1） | 一律 **unknown**；区分 / 待复核另把 conflicts 写出来 |

**两处口径必须一起报，别只报小的那个**：
- 运行期实测（plugin/resolver.py 的 _official_meaning_for）：**47 / 176 ＝ 26.7%** 能给出维度 ＝ 单源 44 ＋ 统一 3；
- 侧车自报（plugin/error_codes.yaml 的 coverage 字段）：**classified=48 / 176 ＝ 27.3%**——那是**表内 dimension≠unknown** 的生成时口径，比运行期 status 闸门宽 1 条；
- **旧记 44/176 ＝ 25.0%（63 号）＝ 单源档**，不是「全部能答」；引用时不得写成「44 条可信」。

**旁证（capability §4-c 实测）**：diagnose_error 的维度可信度——6 个码里只有 **1** 个（-4002）落 dim_known，其余落 dim_unknown ⇒ 「承认不知道」是**设计行为**，不是缺陷。

---

## 6. 现场样本为零：禁止越界的一条

- **真实会话的本体使用事件 0 条**（10-12／13 共 49 条真实轨迹；python3 plugin/scripts/trajectory_report.py --ontology 复核仍为 0）。
- 探针电池的 **111 给 / 40 可比 / 31 进输出（78%）** 来自**构造调用**（plugin/scripts/ontology_probe.py），**不是**真实流量统计。
- **在真实会话攒够 ≥3 个独立任务之前**，「本体在真实流量里的命中率」**不得**写进任何对外结论（样本量纪律）。本 skill 的所有数字都只能标注为**管道级**，不是现场级。

---

## 7. 机制侧的诚实边界（同源）

- 规模：机制类 5（1 根 ＋ 4 子）／manifests_as 8 边／subclass_of 4 边／**triggers · amplifies · mitigated_by 均 0 边**。
- **unknown 是合法答案**：纯软证据只能到 unknown（hard_cap），不许用推测填空；fact_vs_inference 把「判据命中原文」与「推断」分开。
- 沉默端：silence_note 明说「未出现在观测里 ≠ 不存在」，并给 next_actions（取证）——但 next_actions **不是处置**（N6）。
- counter_check 含**否定**语义或**数值比大小**的仍须人判（不做通用机检）。
