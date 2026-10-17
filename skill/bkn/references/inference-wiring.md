# 推理接线标准（声明 → 消费）

> 本件是 `skill:bkn` 准入四关里**第 0 关「进得了推理吗」的可执行展开**，
> 也是`doc/build/demo-product-bkn/11-design_rules_checklist.md` **规则 17** 的详解。
> **唯一真值 ＝ `plugin/edge_semantics.yaml`**；本件不另立数值。

## 0. 一句话

**声明不是能力**。一条写进侧车的「公理」，只有被求值器**读并承重**，才配叫公理；
没有消费者的声明是**纸上公理**（R-1），只会误导后来者，一律**接线或删键**。

## 1. 什么时候用本件

| 场景 | 用本件吗 |
|---|---|
| 新增/修改关系类型（`RELATION_TYPES`） | ✅ 走本件 §2 五条 |
| 新增/修改 `plugin/edge_semantics.yaml` 里的键（传递/复合/对称/域继承/可穿边） | ✅ 走本件 §2 五条 |
| 只改 `.bkn` 内容（加段、加边、加实例登记） | ❌ 走准入四关（本 skill 速览）与 lint |
| 只改 Skill 文本 | ❌ 走 `skill:bkn-updater` |

## 2. 五条硬标准（缺一即视为未完成）

### ① 说得出 domain / range 与**必要判据**

「A 与 B 之间何时该有这条边、何时**不该**有」必须能写成判据；
只有举例、说不出判据 ⇒ 不是本体元素，是散文。

### ② 回答「带来什么**新的推理**」

**能由既有元素推导出的结论 ⇒ 冗余层，不加**（准入四关第 3 关）。
反例（本仓先例）：机制层曾凭 2 个案例反推 6 个机制并自称「收敛」，整层撤回。

### ③ **必须有消费者**——无消费者不得声明

声明写进 `edge_semantics.yaml` 后，`plugin/relations.py`（或等价求值路径）**必须读它**。

| 键 | 消费者（实证） |
|---|---|
| `transitive` | `relations.py` 的 `closure()`；`transitive_targets()`；`_descendants()` / `_ancestors()` 类继承；`resolver.py` `get_process_chain()` |
| `compositions` | `relations.py` 的 `closure()`；`tools.py` `resolve_relation(relation_type=closure)` |
| `symmetric` | `relations.py` 的 `walk()` 对称分支 |
| `domains` ＋ `inherited_domains` / `inherited_incoming_domains` | `relations.py` 的 `_inherited_edges()` |
| `walk_policy`（`traversable` / `stop_at` / `max_depth` / `max_paths`） | `relations.py` 的 `walk()` |

**机检前置拦截**：lint 第 36 项 `_check_edge_semantics_consumers`（2026-10-15，`C-20261015-04`）——
声明的键在 `plugin/**/*.py`（**不含 tests**）零引用 ⇒ **error**，门禁① 直接拦下。

### ④ **必须同批带反向注入负例**

**做法**：注入一条错误声明 → 断言输出**按预期变化**；**输出无变化 ⇒ 该键无消费者**。

- 现成检测器：`plugin/tests/test_edge_semantics_injection.py`
  （LoadBearing 承重实证 / DeadDeclarationsTripwire 零消费 tripwire / ConsumerMatrixDriftGuard）；
- 纪律：**没带负例的机检视为未完成**（11 号规则 9；对照驱动 G-22）。

### ⑤ **值数据分工**：公理只在 `edge_semantics.yaml`

- Skill 与 `.bkn` **不得另立**同义键（`.bkn` 里连键名都不许引用）；
- 文档侧只允许「**引用 ＋ 快照标注**」，且必须同批更新：
  `skill/bkn-plugin/references/edge-semantics.md`、
  `doc/capability/ontology-inference.md` §3、
  `doc/build/demo-product-bkn/24-bkn_ontology.md` §3.1/§3.3。

## 3. 消费契约（对外不可改）

`resolve_relation` 返回的每跳依据 `from` / `edge` / `to` / `way` 是**契约**：
Skill、文档、报表**都不得另立口径**（继承边额外带 `via`）。

**诚实兜底**：推不出时落 `unknown` ＋ 检索指引，**不许猜**；
覆盖度不许说「全覆盖」（影响面实测 12/203，上限 14–16——见 `skill:bkn-reasoning`）。

## 4. 落地步骤

1. 过 §2 五条（写成一段论证，进候选的 `review.md`）；
2. 改 `plugin/edge_semantics.yaml` ＋ 接线消费者；
3. 加负例（§2④）＋ 跑 `python3 plugin/scripts/lint_bkn.py --error-only`（第 36 项会拦无消费者键）；
4. 同批改 §2⑤ 的三处引用；
5. 走候选 → 人工记名 apply → `bash scripts/gate.sh` 7/7。

## 5. 禁止

- **无消费者就声明**（「先写上，以后会接」——这就是 R-1）；
- 删键了却在文档/skill 里留旧键名与旧数值（2026-10-15 前的 `reverse_ok` 就是这么留了两代）；
- 在 `.bkn` 里引用公理键名。
