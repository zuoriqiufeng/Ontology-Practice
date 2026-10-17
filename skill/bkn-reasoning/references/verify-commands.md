# 复现命令与期望输出（本 skill 所有数字的出处）

> **执行位置**：仓库根（<repo>）。
> **基准**：2026-10-13 bkn-20261013-3（203 节点 / 223 边 / 29 关系类型）；下列输出为 2026-10-15 实测原文。
> **环境**：python3（含 PyYAML）；不联网（Qdrant 不可达时相应行会降级，属预期）。

---

## 1. 结构量（一切数字的基准线）

```bash
python3 plugin/scripts/graph_metrics.py
```

**期望（单行 stdout）**：

```
nodes=203 edges=223 relation_types=29 ingraph_sections=30 constrained_by=28
```

**不满足时**：结构量漂移——先查 bkn/relations/ 的最近改动；本 skill 的 203/223/29 全部按此基准，漂移则同批更新 doc/capability/ontology-inference.md 与本目录数字。

---

## 2. 上限事实（walk_policy / transitive / compositions / symmetric）

```bash
python3 - <<'PY'
import yaml
sem = yaml.safe_load(open('plugin/edge_semantics.yaml', encoding='utf-8'))
wp = sem['walk_policy']
print('traversable=%d max_depth=%d max_paths=%d' % (len(wp['traversable']), wp['max_depth'], wp['max_paths']))
print('stop_at=%s' % wp['stop_at'])
print('transitive=%s compositions=%s symmetric=%s' % (sem['transitive'], [c['id'] for c in sem['compositions']], sem['symmetric']))
print('reverse_ok present=%s' % ('reverse_ok' in sem))
PY
```

**期望**：

```
traversable=25 max_depth=5 max_paths=12
stop_at=['skill:', 'log:', 'dimension:', 'mechanism:']
transitive=['feeds', 'runs_on', 'subclass_of'] compositions=['registered_on_then_runs_on'] symmetric=['connects_to']
reverse_ok present=False
```

**附录 A 原命令（文本核对）**：

```bash
grep -nE "transitive|compositions|symmetric|max_depth|max_paths" -A 3 plugin/edge_semantics.yaml
```

**读法**：stop_at **不含 store:**；reverse_ok 已删除（出现即回归）。

---

## 3. 三条现场问法（capability 附录 A 原样）

```bash
python3 - <<'PY'
import sys; sys.path.insert(0, '.')
import plugin.tools as T
for args in ({"source_entity": "worknode", "relation_type": "all", "direction": "in", "depth": 2},
             {"source_entity": "dbnode", "relation_type": "all", "depth": 3},
             {"source_entity": "process:iatrack", "relation_type": "all", "depth": 3}):
    print(T.resolve_relation(dict(args)))
PY
```

**期望（三个 paths 段的规模）**：

| 起点与参数 | 期望输出 |
|---|---|
| worknode，direction=in，depth=2 | paths[12]（syncrule / dbnode / link:* / controlnode / process:*） |
| dbnode，depth=3 | paths[7]（worknode、host 等） |
| process:iatrack，depth=3 | paths[9]（process:ialoader feeds → dbnode consumes → worknode …） |

**计数版（只看规模，省输出）**：

```bash
python3 - <<'PY'
import sys; sys.path.insert(0, '.')
import plugin.tools as T
for a in ({"source_entity":"worknode","relation_type":"all","direction":"in","depth":2},
          {"source_entity":"dbnode","relation_type":"all","depth":3},
          {"source_entity":"process:iatrack","relation_type":"all","depth":3}):
    out = T.resolve_relation(dict(a))
    print(a['source_entity'], [l.strip() for l in out.splitlines() if 'paths[' in l])
PY
```

**期望**：worknode ['paths[12]{end,hops}:']、dbnode ['paths[7]{end,hops}:']、process:iatrack ['paths[9]{end,hops}:']。

---

## 4. 两个易混问法的对照（反查 vs 影响面）

```bash
python3 - <<'PY'
import sys; sys.path.insert(0, '.')
import plugin.tools as T
print('--- who-depends (direction=in) ---')
print(T.resolve_relation({"source_entity":"worknode","relation_type":"all","direction":"in","depth":2})[:400])
print('--- impact ---')
print(T.resolve_relation({"source_entity":"worknode","relation_type":"impact"}))
print('--- impact, out of scope ---')
print(T.resolve_relation({"source_entity":"symptom:crash_loop","relation_type":"impact"}))
PY
```

**期望**：
- worknode 反查：paths[12]；
- worknode 影响面：edge_types[5]（feeds / reads_from / runs_on / registered_on / supervises），by_unit 仅 3 个单元（host / syncrule / dbnode）；
- symptom:crash_loop 影响面：by_unit 空，**必带** impact_note「返回空是覆盖边界，不是「无影响」」。

**覆盖节点全集（12 个）核对**：

```bash
python3 - <<'PY'
import sys; sys.path.insert(0, '.')
from plugin.relations import RelationTraverser
tr = RelationTraverser()
SE = ("feeds", "reads_from", "runs_on", "registered_on", "supervises")
cov = set()
for s, rels in tr.graph.items():
    for rel, tgts in rels.items():
        if rel in SE:
            cov.add(s); cov.update(tgts)
print(len(cov), sorted(cov))
PY
```

**期望**：12 个：controlnode / dbnode / host / process:iadiff / process:iadumper / process:iahelper / process:ialoader / process:iamonitor / process:iaproxy / process:iatrack / syncrule / worknode。

---

## 5. 闭包出口（传递 / 复合 / 对称）

```bash
python3 - <<'PY'
import sys; sys.path.insert(0, '.')
import plugin.tools as T
print(T.resolve_relation({"source_entity":"dbnode","relation_type":"closure"}))
PY
```

**期望**：closure[7]，首条为 host,composition（两跳：dbnode -registered_on-> worknode -runs_on-> host），另有 symmetric 腿（link:console_db / link:node_source_db / link:node_target_db / controlnode / worknode）。

---

## 6. 语义成立性与 lint

```bash
python3 -m pytest plugin/tests/test_edge_semantics.py -q
python3 plugin/scripts/lint_bkn.py --error-only
```

**期望**：14 passed（前者）；Summary: errors=0 warnings=0 infos=0（后者）。

---

## 7. 探针电池（图消耗：给了多少 → 真进输出）

```bash
python3 plugin/scripts/ontology_probe.py
```

**期望（末段摘要）**：

```
图路径：本体给出 111 条候选（去重后可比 40 条），31 条进输出（78%）
图出口分布：{..., 'rel:impact': 1, ...}
exit=0
```

**说明**：脚本把日志指向临时目录（**绝不写生产 logs/**）；输出是**构造调用**，不是真实流量统计。

---

## 8. 真实轨迹汇总（现场样本）

```bash
python3 plugin/scripts/trajectory_report.py --ontology
```

**期望（当前）**：

```
本体使用台账（ontology_use）：0 次有交互的 Tool 调用
```

**读法**：0 表示**现场样本为零**——在真实会话攒够 ≥3 个独立任务之前，不得据此宣称（或否认）现场命中率；exit=0。

---

## 9. 机制侧（候选 ＋ 证据缺口）

```bash
python3 - <<'PY'
import sys; sys.path.insert(0, '.')
import plugin.tools as T
print(T.diagnose_mechanism({"entry": "dimension:resource",
                            "observations": ["Killed process 58998 (java)"]}))
PY
```

**期望（段名齐备）**：candidates / chain_note / root_note / structural_evidence / treatment_hint / next_actions / fact_vs_inference / silence_note；本样例的 candidates[1] 为 resource_exhaustion_cascade 且 state=unknown（「命中含 hard 但来源不独立 ⇒ 停在 unknown」）；structural_evidence 的 checkable=partial（缺 affected_unit）；chain_note 明说因果层暂不可用。

---

## 10. 一条不存在的命令（别去找）

**没有** find_path / 「A 到 B 的路径查询」出口——该函数已按零消费者删除（21 号）。要判可达，用 depth>1 的 paths 段（§3）。
