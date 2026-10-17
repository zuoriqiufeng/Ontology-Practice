# 边走法 / 公理层（`plugin/edge_semantics.yaml`）

> **权威文件只有一份**：`plugin/edge_semantics.yaml`。本页是**它的使用说明**，不是第二口径；
> **冲突以 yaml 为准**。本页出现的数值是**快照（实测 2026-10-15）**——改 yaml 必须同批改本页，
> 对账命令见 §6。

## 1. 它管什么

「一条边**能不能走**、走多远、反着走行不行、跨域怎么继承」——**过程语义**（怎么走）。
它**不**管「关系类型是什么」：那是 `plugin/relations.py::RelationTraverser.RELATION_TYPES` 的 **29 种**白名单，
列表与域分组见 `bkn/relations/RELATION_TYPES.md`。

## 2. 声明 vs 强制（**本页最重要的一张表**，2026-10-15 复核实值）

| 键 | 声明内容 | 求值器是否消费 | 消费者位置 |
|---|---|:--:|---|
| `symmetric` | `connects_to` 无向 | ✅ **已消费** | `relations.py` 的 `walk()` 对称分支 |
| `walk_policy` | 可穿边 **25 种** / 停止前缀 **4 个** / `max_depth=5` / `max_paths=12` | ✅ **已消费** | `relations.py` 的 `walk()` |
| `domains` ＋ `inherited_domains` / `inherited_incoming_domains` | 关系归域、子类按**域**继承（出边／入边两侧） | ✅ **已消费** | `relations.py` 的 `_inherited_edges()` |
| `transitive` | `feeds` / `runs_on` / `subclass_of` 可传递 | ✅ **已接线承重** | `relations.py` 的 `closure()`；`transitive_targets()`（进程链闸门）；`_descendants()` / `_ancestors()`（类继承闸门）；`resolver.py` `get_process_chain()` |
| `compositions` | `registered_on ∘ runs_on`（库 → 节点 → 主机） | ✅ **已接线承重** | `relations.py` 的 `closure()`；`tools.py` `resolve_relation(relation_type=closure)` |

> **信任面 ＝ 全部键**：2026-10-15 复核时，上述 5 类键**都**有消费者，没有「纸上公理」。
> **本页 2026-10-13 前的旧口径已作废**——旧版把 `transitive`/`compositions` 记成「⚠️ 无消费者」、
> 把 `reverse_ok` 列为「❌ 未强制」，**与 yaml 实测相反**（缺陷 D-1，见 `doc/optimize/74-skill-system-plan.md` §1.1）。

**已删除的键**：`reverse_ok`（2026-10-13，`C-20261013-04`，「**不能推就删**」）——它既无消费方，
又与实现**矛盾**（声称 gate 反查，而求值器对**所有可穿边**一律放行 `direction=in`）；
反向能力由 `walk_policy.traversable` **单独提供**。**勿重新引入**（有 tripwire）。

## 3. `walk_policy` 的字段（实值）

| 字段 | 现值 | 含义 |
|---|---|---|
| `traversable` | **25 种边** | **白名单**：不在表里的边**不参与**任何行走 |
| `stop_at` | **4 个前缀**：`skill:` `log:` `dimension:` `mechanism:` | 到达这些命名空间**即终止该分支**（`store:` 已于 2026-10-13 删除——全图 0 个 `store:` 节点，死配置） |
| `max_depth` | **5** | 与 API 的 `depth` 取小 |
| `max_paths` | **12** | 结果条数上限（截断有留痕） |

> **不是最短路径算法**：`walk` 是**有界 BFS**，每个可达节点给**一条最短见证路径** ＋ 逐跳
> `from` / `edge` / `to` / `way`（继承边额外带 `via`）；派生路径**按需求值、不物化**（不写回 graph / 基线）。
> **每跳依据是契约**：Skill 与文档**不得另立口径**（见 `skill:bkn-reasoning`）。

## 4. 怎么改（安全流程）

1. 先说清要改变哪个**可见行为**（反查 / 可穿 / 对称 / 域继承 / 传递 / 复合）；
2. **写反向注入测试**：注入一条错误声明 → 断言输出按预期变化；**没变化就说明该键没有消费者**
   （这正是「不能推就删」的检出方式，也是 lint 第 36 项 `_check_edge_semantics_consumers` 的前置）；
3. 走评审 → 待审区候选 → 账本记名；
4. 同批更新三处引用：本页、`doc/capability/ontology-inference.md` §3、
   `doc/build/demo-product-bkn/24-bkn_ontology.md` §3.1/§3.3（**数值单源 ＝ yaml**，其余只引用）。

## 5. 禁止

- 为了「看起来更像本体」而新增**无消费者**的键（那正是「纸上公理」的成因）；
- 在 Skill / 文档里另立一套边走法口径（权威只有 yaml）；
- 在 `.bkn` 里引用本文件的键名（值数据分工制：公理只在侧车）。

## 6. 对账命令（数值漂移的检出）

```bash
cd <repo>
python3 - <<'PY'
import yaml
w = yaml.safe_load(open('plugin/edge_semantics.yaml'))['walk_policy']
print('traversable', len(w['traversable']), '| stop_at', w['stop_at'], '| max_depth', w['max_depth'], '| max_paths', w['max_paths'])
PY
grep -n "25 种\|max_depth=5\|max_paths=12\|mechanism:" \
  doc/capability/ontology-inference.md doc/build/demo-product-bkn/24-bkn_ontology.md
```
