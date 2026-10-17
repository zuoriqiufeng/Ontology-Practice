"""relations.py — bkn/relations/*.bkn 图遍历器

解析 bkn/relations/*.bkn (KWeaver 段落格式) 中的实体关系, 提供有向图遍历。
每段 `## Relation:` 内 `关系类型` 字段为 graph 的 rel_type key (snake_case);
`映射规则` 区逐行 `src` → `tgt` 入图 (实例级), 否则取 `源对象`/`目标对象` 单条入图 (类型级)。
支持的关系类型 (29 种, 见 RELATION_TYPES):
  B-域 (14): requires / implements / constrains / constrained_by / prerequisite / risks_of /
             has_action / references / runs_on / registered_on / supports / implements_skill /
             reads_from / writes_to
  O-域 (3):  has_class / diagnosed_by / observed_in
  运行时对象域 (6): feeds / supervises / consumes / produces / monitors / suspected_in
             （对象轴：进程拓扑为主干，见 doc/optimize/20-runtime-object-ontology.md）
  结构域 (1): connects_to（部署单元与链路，25 号新增）
"""

from __future__ import annotations

import re
from collections import defaultdict, deque
from pathlib import Path


def _load_edge_semantics() -> dict:
    """加载边语义字典（38 号批 2）。**失败退化为 {}**（求值器不可用＝只读能力降级，
    不影响既有遍历）；惰性 import yaml——runtime 可能没有 pyyaml，import 期不得依赖（36 号教训）。
    与 `resolver._load_error_semantics` 同法。
    """
    try:
        import yaml
        path = Path(__file__).resolve().parent / "edge_semantics.yaml"
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _track_walk_stop(start, depth, limit, traversable, paths, stop_hit, max_paths) -> None:
    """B3（44 号 §3.3 `walk_stop`）：`walk` 出口的**一次**聚合埋点。

    回答「走了几跳、用了哪些边、在哪儿被截断」——**只读已有局部变量，不新增遍历**；
    `edges` 由已产出的 hops 反推（近似：未产出 hop 的边不算「走过」）；
    截断判定顺序照 44 号：max_paths → stop_at → whitelist → exhausted；
    `stop_hit` 是展开过程中**碰到过** stop_at 前缀（该分支不再下探，同层其它分支仍会展开）。
    任何异常只丢日志——不得影响 walk 的返回结构（44 号 §3.2 硬约束）。
    """
    try:
        edges: list[str] = []
        for p in paths or []:
            for hop in (p.get("hops") if isinstance(p, dict) else None) or []:
                e = hop.get("edge")
                if e and e not in edges:
                    edges.append(e)
        if len(paths or []) >= max_paths:
            stopped = "max_paths"
        elif stop_hit:
            stopped = "stop_at"
        elif not traversable:
            stopped = "whitelist"
        else:
            stopped = "exhausted"
        from .observability import track
        track("walk_stop", start=start, depth=depth, limit=limit, edges=edges,
              paths=len(paths or []), stopped=stopped)
    except Exception:
        pass



def _edge_hook(rel, direction: str, uniq, node: str) -> None:
    """P3：图（边）消费漏斗埋点——由 `_targets_tagged`/`_sources_tagged` 出口调用。

    为什么是这两处就是**全图覆盖**：全仓 27 个图调用点（tools.py 14 + resolver.py 13）
    全部经由这两个方法（`_targets`/`_sources`/`get_targets`/`transitive_targets`/`expand`/
    `walk`/`closure`/`reachable`/`get_*_for_*` 都是它们的包装）——同 P2 把文件读点
    收在 `_SectionDict._ensure` 一处的手法。

    只读已有局部变量、**不新增遍历**；异常只丢日志，不得影响 walk/闭包返回结构
    （44 号 §3.2 硬约束）。
    """
    try:
        from .observability import ontology_edge
        targets = [t for t, _ in uniq or []]
        ontology_edge(rel, direction, len(targets), node, targets)
    except Exception:
        pass


def _track_impact_query(start, covered, units, paths, depth, direction, note_kind) -> None:
    """68 号 E-1：`impact` 出口的**一次**聚合埋点（照 `_track_walk_stop` 范式）。

    回答「**是没人用，还是用不了**」——`covered` 区分「出口没人调」与「调了但起点不在覆盖内」。
    只读已有局部变量、不新增遍历；任何异常只丢日志，不得影响 `resolve_relation` 的返回结构。
    """
    try:
        from .observability import track
        track("impact_query", start=start, covered=bool(covered), units=units,
              paths=paths, depth=depth, direction=direction, note_kind=note_kind)
    except Exception:
        pass


class RelationTraverser:
    """BKN 关系图遍历器"""

    #: 边语义字典缓存（38 号批 2；`edge_semantics()` 惰性加载）
    _SEMANTICS: dict | None = None

    RELATION_TYPES = [
        # ── B 域（14 种）──
        "requires", "implements", "constrains", "constrained_by",
        "prerequisite", "risks_of", "has_action",
        "references", "runs_on", "registered_on", "supports",
        "implements_skill",
        # 源端/目标端角色由边类型承载（2026-09-22 批 0-3，P1-6 复核改判，
        # 替代 dbnode:source / dbnode:target 节点名后缀）
        "reads_from",    # 实例级: syncrule → dbnode（源端）
        "writes_to",     # 实例级: syncrule → dbnode（目标端）
        # ── O 域（3 种，入 graph；见 doc/optimize/14-symptom-ontology-design.md）──
        "has_class",     # 实例级: symptom:/error: → class:   归类
        "diagnosed_by",  # 类级:   class: → skill:           诊断策略
        "observed_in",   # 类级:   class: → log:             取证入口（有序）
        # ── 运行时对象域（6 种，入 graph；见 doc/optimize/20-runtime-object-ontology.md）──
        # 对象轴：进程拓扑为主干，替代「按错误分类」的分类轴
        "feeds",         # 实例级: process:* → process:*     数据流下游（谁消费我的输出，有序）
        "supervises",    # 实例级: process:* → process:*     生命周期管理（拉起/停止/监控）
        "consumes",      # 实例级: process:* → dbnode        从哪个库读数据（源端，数据流）
        "produces",      # 实例级: process:* → dbnode        向哪个库写数据（目标端，数据流）
        "monitors",      # 实例级: process:* → dbnode        状态监控（只读状态，不读数据）
        "suspected_in",  # 实例级: symptom:/error: → process:*  嫌疑进程（替代 has_class）
        # ── 结构域（25 号新增，入 graph）──
        # 部署单元与链路：单元（controlnode/worknode/host）承载关系 + 链路两端（link:* → 单元）
        "connects_to",   # 实例级: link:* → controlnode/worknode/dbnode  链路两端（方向见 link 属性）
        "triggers",
        "amplifies",
        "manifests_as",
        "mitigated_by",
        "subclass_of",
    ]

    def __init__(self, bkn_root: str = None):
        if bkn_root is None:
            bkn_root = str(Path(__file__).resolve().parent.parent / "bkn")
        self.root = Path(bkn_root)
        self.graph: dict[str, dict[str, list[str]]] = defaultdict(
            lambda: defaultdict(list)
        )  # {source_id: {rel_type: [target_id]}}
        self._rev = None  # 反查索引（38 号批 2：walk/reachable 惰性构建）
        rel_dir = self.root / "relations"
        if rel_dir.is_dir():
            # 24 号（目录收拢）：进程拓扑边已并入 relations/process_topology.bkn
            # （原 processes/topology.bkn 的单点白名单加载已删除——整目录 glob 自动入图）
            self._parse_relations_dir(rel_dir)  # KWeaver 段落格式

    # ── KWeaver 段落格式解析 (bkn/relations/*.bkn) ──

    def _parse_relations_dir(self, rel_dir: Path):
        """从 bkn/relations/*.bkn (KWeaver 段落格式) 构建有向图。"""
        for path in sorted(rel_dir.glob("*.bkn")):
            self._parse_relations_file(path)

    def _parse_relations_file(self, path: Path):
        """解析单个 .bkn 文件中的 `## Relation:` 段入图。
        每段 `关系类型` 字段为机器可读 key (snake_case);
        `映射规则` 区逐行 `src` → `tgt` 入图; 缺/非法 `关系类型` 的段跳过不入图。"""
        text = path.read_text(encoding="utf-8", errors="ignore")
        for block in re.split(r"\n(?=## Relation: )", text):
            if "## Relation:" not in block:
                continue
            head, mapping = self._split_mapping_block(block)
            kv = self._parse_kv(head)
            rel = (kv.get("关系类型") or "").strip().lower()
            if rel not in self.RELATION_TYPES:
                continue
            if mapping:
                for src, tgt in self._iter_mapping_lines(mapping):
                    self.graph[src][rel].append(tgt)
            else:
                src = (kv.get("源对象") or "").strip()
                tgt = (kv.get("目标对象") or "").strip()
                if src and tgt and "*" not in src and "*" not in tgt:
                    self.graph[src][rel].append(tgt)

    @staticmethod
    def _parse_kv(head: str) -> dict[str, str]:
        """解析段头部 `- **key**: value` 行 (key 去粗体星号, 支持中文 key)。"""
        kv = {}
        for line in head.split("\n"):
            line = line.strip()
            m = re.match(r"^-?[ \t]*([^:\n>|# \t][^:\n]*?)[ \t]*:[ \t]*(.+)", line)
            if m:
                k = m.group(1).strip().strip("*").strip()
                kv[k] = m.group(2).strip()
        return kv

    @staticmethod
    def _split_mapping_block(block: str) -> tuple[str, str]:
        """把段切成 (头部, 映射规则区); 映射规则区以 `- **映射规则**:` 起始。"""
        m = re.search(r"^[ \t]*-[ \t]*\*\*映射规则\*\*[ \t]*:[ \t]*$", block, re.MULTILINE)
        if not m:
            return block, ""
        return block[: m.start()], block[m.end() :]

    @staticmethod
    def _iter_mapping_lines(mapping: str):
        """从映射规则区逐行抓取 `src` → `tgt` (# 后注释忽略, 仅作文本)。

        v1.5 (P1-7): 目标可带 `(abstract)` 后缀，表示关系层语义抽象、
        无实体定义；入图时剥离后缀保持图键干净。
        """
        pat = re.compile(r"`([^`]+)`[ \t]*→[ \t]*`([^`]+)`")
        for line in mapping.split("\n"):
            line = line.split("#", 1)[0]
            m = pat.search(line)
            if m:
                src = m.group(1).strip()
                tgt = m.group(2).strip()
                if tgt.endswith("(abstract)"):
                    tgt = tgt[:-len("(abstract)")].strip()
                yield src, tgt

    def _edge_domains(self) -> dict:
        """域 → 成员（值数据；取自 edge_semantics.yaml 的 domains）。缺省空 dict。"""
        try:
            return self.edge_semantics().get("domains") or {}
        except Exception:
            return {}

    def _inherited_edges(self) -> set:
        """可继承的边类型集合：由 inherited_domains **按域**展开（42 号 Q2）。
        缺省为空 ⇒ 不继承（失败方向在安全侧）。"""
        try:
            sem = self.edge_semantics()
        except Exception:
            return set()
        doms = self._edge_domains()
        out: set = set()
        for d in sem.get("inherited_domains") or []:
            out.update(doms.get(d) or [])
        return out

    def _inherited_incoming_edges(self) -> set:
        """**入边**方向的可继承边类型集合（C-20261012-16）。
        语义：A 触发**子**机制 ⇒ 也触发了**父**机制，故查「谁指向父机制」时须纳入其子类的入边。
        只限声明在 inherited_incoming_domains 的域（因果侧）；缺省空 ⇒ 不继承。"""
        try:
            sem = self.edge_semantics()
        except Exception:
            return set()
        doms = self._edge_domains()
        out: set = set()
        for d in sem.get("inherited_incoming_domains") or []:
            out.update(doms.get(d) or [])
        return out

    # ── 边语义的求值出口：transitive / compositions 两键的消费者（C-20261013-04 接线批）──

    def _transitive_edges(self) -> set:
        """edge_semantics.yaml 声明的**可传递**边（缺失/加载失败 → 空集）。

        **承重**：subclass_of（类继承）与 feeds（进程链）的传递展开都以本集合为闸门——
        摘掉声明即**关闭**该边的传递链（不再是「只声明、无实现」）。
        失败方向＝关闭传递链（安全侧）；edge_semantics.yaml 的存在与键齐由
        test_edge_semantics.py 的结构断言把关。
        """
        return set(self.edge_semantics().get("transitive") or [])

    def _compositions(self) -> list:
        """edge_semantics.yaml 声明的**复合**两段（缺失 → 空表；无 seq 的条目丢弃）。"""
        return [c for c in (self.edge_semantics().get("compositions") or [])
                if isinstance(c, dict) and c.get("seq")]

    def transitive_targets(self, node: str, rel: str) -> list:
        """rel 的**一跳**目标——**仅当 rel 声明在 transitive 里**才有值（否则 []）。

        transitive 的消费者之一（resolver.get_process_chain 的链式扩展走这里）：
        把 feeds 从 transitive 摘掉 ⇒ 进程链退化为单点。
        """
        if rel not in self._transitive_edges():
            return []
        return self._targets(node, rel)

    def _chain(self, start_id: str, edge: str, direction: str) -> list:
        """沿**单条边**的传递链（防环、BFS 序）→ [(终点, 依据跳)]。"""
        seen = {start_id}
        out: list = []
        frontier: list = [(start_id, [])]
        while frontier:
            cur, hops = frontier.pop(0)
            if direction == "in":
                steps = [(s, "in", via) for s, via in self._sources_tagged(cur, edge)]
            else:
                steps = [(t, "out", via) for t, via in self._targets_tagged(cur, edge)]
            for tgt, way, via in steps:
                if tgt in seen:
                    continue
                seen.add(tgt)
                hop = {"from": cur, "edge": edge, "to": tgt, "way": way}
                if via is not None:
                    hop["via"] = via      # 继承来源（可溯，42 号 Q4）
                nh = hops + [hop]
                out.append((tgt, nh))
                frontier.append((tgt, nh))
        return out

    def closure(self, start_id: str, rel: str = None, direction: str = "out") -> list[dict]:
        """**传递 / 复合 / 对称**的只读闭包（38 号 §3.2 设计的求值入口；本方法即
        transitive / compositions 两键在**生产路径**上的消费者）。

        规则（全部取自 edge_semantics.yaml；未声明 → 该类路径不产出）：
          · **传递**（transitive）：沿声明的边逐跳展开，防环、BFS 序；rel 给出时只走该条，
            direction=in 反查；
          · **复合**（compositions）：按 seq 顺序走完（如 registered_on → runs_on），
            产出 kind=composition 的路径，composition 字段即复合名；rel 给出时只保留 seq 含该边的复合；
          · **对称**（symmetric）：双向走（direction 对它不生效——对称本身即双向）。
        返回 [{end, kind, composition, hops:[{from, edge, to, way}]}]；只读、**不物化**（37 号 Q3）。
        """
        out: list[dict] = []
        # ① 传递
        transitive = self._transitive_edges()
        for edge in ([rel] if rel else sorted(transitive)):
            if edge not in transitive:
                continue
            for end, hops in self._chain(start_id, edge, direction):
                out.append({"end": end, "kind": "transitive",
                            "composition": None, "hops": hops})
        # ② 复合
        for comp in self._compositions():
            seq = list(comp.get("seq") or [])
            if rel and rel not in seq:
                continue
            nodes: list = [(start_id, [])]
            for edge in seq:
                nxt: list = []
                for cur, hops in nodes:
                    for tgt, via in self._targets_tagged(cur, edge):
                        hop = {"from": cur, "edge": edge, "to": tgt, "way": "out"}
                        if via is not None:
                            hop["via"] = via
                        nxt.append((tgt, hops + [hop]))
                nodes = nxt
                if not nodes:
                    break
            for end, hops in nodes:
                if end != start_id:
                    out.append({"end": end, "kind": "composition",
                                "composition": comp.get("id"), "hops": hops})
        # ③ 对称
        for edge in sorted(set(self.edge_semantics().get("symmetric") or [])):
            if rel and rel != edge:
                continue
            seen = {start_id}
            frontier: list = [(start_id, [])]
            while frontier:
                cur, hops = frontier.pop(0)
                steps = [(t, "out") for t in self._targets(cur, edge)]
                steps += [(s, "in") for s in self._sources(cur, edge)]
                for tgt, way in steps:
                    if tgt in seen:
                        continue
                    seen.add(tgt)
                    hop = {"from": cur, "edge": edge, "to": tgt, "way": way}
                    nh = hops + [hop]
                    out.append({"end": tgt, "kind": "symmetric",
                                "composition": None, "hops": nh})
                    frontier.append((tgt, nh))
        return out

    def _descendants(self, node: str) -> list:
        """subclass_of 的**后代**链（传递闭包、防环）——_ancestors 的反向。无子类时为 []。

        **闸门**：subclass_of 须声明在 edge_semantics.yaml 的 transitive 里
        （transitive 的消费者之一）。未声明 ⇒ 返回 []（继承机制随之关闭，失败在安全侧）。
        """
        if "subclass_of" not in self._transitive_edges():
            return []
        rev = self._reverse_index()
        out: list = []
        seen = {node}
        frontier = list(rev.get(node, {}).get("subclass_of", []))
        while frontier:
            cur = frontier.pop(0)
            if cur in seen:
                continue
            seen.add(cur)
            out.append(cur)
            frontier.extend(rev.get(cur, {}).get("subclass_of", []))
        return out

    def _sources_tagged(self, node: str, rel: str) -> list:
        """返回 [(源, 经由后代|None)]：直接入边经由为 None；继承来的入边记录**后代**（可溯）。"""
        rev = self._reverse_index()
        tagged = [(s, None) for s in rev.get(node, {}).get(rel, [])]
        if rel in self._inherited_incoming_edges():
            for d in self._descendants(node):
                for s in rev.get(d, {}).get(rel, []):
                    tagged.append((s, d))
        seen: set = set()
        uniq: list = []
        for s, via in tagged:
            if s in seen:
                continue
            seen.add(s)
            uniq.append((s, via))
        _edge_hook(rel, "in", uniq, node)   # P3：入边消费（含反向继承）
        return uniq

    def _sources(self, node: str, rel: str) -> list:
        """该节点 rel 的入边来源（含反向继承）。"""
        return [s for s, _ in self._sources_tagged(node, rel)]

    def _ancestors(self, node: str) -> list:
        """subclass_of 的祖先链（传递闭包、防环）。无子类时为 []。

        **闸门**：subclass_of 须声明在 edge_semantics.yaml 的 transitive 里
        （transitive 的消费者之一）。未声明 ⇒ 返回 []（继承语义随之关闭）。
        """
        if "subclass_of" not in self._transitive_edges():
            return []
        out: list = []
        seen = {node}
        frontier = list(self.graph.get(node, {}).get("subclass_of", []))
        while frontier:
            cur = frontier.pop(0)
            if cur in seen:
                continue
            seen.add(cur)
            out.append(cur)
            frontier.extend(self.graph.get(cur, {}).get("subclass_of", []))
        return out

    def _targets_tagged(self, node: str, rel: str) -> list:
        """返回 [(目标, 继承来源|None)]：直接边来源为 None；继承边记录**父类**（可溯，42 号 Q4）。
        不物化：只在查询时展开。"""
        own = self.graph.get(node, {}).get(rel, [])
        tagged = [(t, None) for t in own]
        if rel in self._inherited_edges():
            for anc in self._ancestors(node):
                for t in self.graph.get(anc, {}).get(rel, []):
                    tagged.append((t, anc))
        seen: set = set()
        uniq: list = []
        for t, src in tagged:
            if t in seen:
                continue
            seen.add(t)
            uniq.append((t, src))
        _edge_hook(rel, "out", uniq, node)  # P3：出边消费（含继承），全图唯一出口
        return uniq

    def _targets(self, node: str, rel: str) -> list:
        """该节点 rel 的出边目标（含继承）。**所有查询入口的唯一出口**。"""
        return [t for t, _ in self._targets_tagged(node, rel)]

    def get_targets(self, source_id: str, rel_type: str = None) -> list[str]:
        """返回 source 的出边目标"""
        if rel_type:
            return self._targets(source_id, rel_type)
        # 返回所有类型
        result = []
        for rel in self.graph.get(source_id, {}):
            result.extend(self._targets(source_id, rel))
        return result

    def expand(self, entity_id: str, depth: int = 3) -> dict:
        """从实体出发, BFS 展开 N 层"""
        from collections import deque
        visited = set()
        result = {"entity": entity_id, "relations": {}}
        queue = deque([(entity_id, 0)])
        while queue:
            current, d = queue.popleft()
            if d >= depth or current in visited:
                continue
            visited.add(current)
            if current not in result["relations"]:
                result["relations"][current] = {}
            for rel_type in self.graph.get(current, {}):
                targets = self._targets(current, rel_type)
                result["relations"][current].setdefault(rel_type, []).extend(targets)
                for t in targets:
                    if t not in visited and d + 1 < depth:
                        queue.append((t, d + 1))
        return result

    # （21 号 2D）find_path / get_sources / get_skill_for_action / get_actions_for_object /
    # get_risks_for_action 已删：生产代码与测试零消费者（26 号 uses_tool 同款判据）。
    # find_path 若将来做多跳图推理工具化（21 号 P2 观测项），届时按需重写。
    # 保留的技能查询入口是复数版 get_skills_for_action（tools.py 注入 _structured_skills 在用）。

    def get_skills_for_action(self, capability: str) -> list[str]:
        """查 action capability 绑定的所有 Skill，去重后返回。"""
        seen: set[str] = set()
        result: list[str] = []
        node_id = f"action:{capability}"
        for tgt in self._targets(node_id, "implements_skill"):
            name = tgt.replace("skill:", "")
            if name and name not in seen:
                seen.add(name)
                result.append(name)
        return result

    def get_constraints_for_action(self, action_id: str) -> list[str]:
        """查 Action 的操作约束"""
        return self._targets(action_id, "constrained_by")

    # ── O 域（运维诊断）查询：见 doc/optimize/14-symptom-ontology-design.md ──

    def get_classes_for_symptom(self, symptom_id: str) -> list[str]:
        """查症状/错误码归属的诊断类（has_class 出边）"""
        return self._targets(symptom_id, "has_class")

    def get_skills_for_class(self, class_id: str) -> list[str]:
        """查诊断类绑定的 Skill（去 skill: 前缀），去重保序"""
        seen: set[str] = set()
        result: list[str] = []
        for tgt in self._targets(class_id, "diagnosed_by"):
            name = tgt.replace("skill:", "")
            if name and name not in seen:
                seen.add(name)
                result.append(name)
        return result

    def get_logs_for_class(self, class_id: str) -> list[str]:
        """查诊断类的取证日志（去 log: 前缀），按声明顺序 = 查看顺序。
        注意: 必须直查本方法, 不得走 expand()（BFS 会打散有序性）。"""
        return [
            t.replace("log:", "")
            for t in self._targets(class_id, "observed_in")
        ]

    # ── 只读求值器（38 号批 2＝37 号 §3-A；**不物化**：派生路径按需求值，不写回 graph/基线）──

    @classmethod
    def edge_semantics(cls) -> dict:
        """边语义字典（`plugin/edge_semantics.yaml`；进程内缓存，加载失败 → {}）。"""
        if cls._SEMANTICS is None:
            cls._SEMANTICS = _load_edge_semantics()
        return cls._SEMANTICS

    def _reverse_index(self) -> dict:
        """反查索引（惰性构建，进程内缓存）：{target: {rel_type: [sources]}}。"""
        if self._rev is None:
            rev: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
            for src, rels in self.graph.items():
                for rel, targets in rels.items():
                    for t in targets:
                        rev[t][rel].append(src)
            self._rev = rev
        return self._rev

    def walk(self, start_id: str, depth: int = 2, direction: str = "out",
             edge_types: list | None = None) -> list[dict]:
        """沿**边语义**展开 ≤depth 跳的结构路径（只读；返回即"每跳依据"）。

        规则（取自 `edge_semantics.yaml`；未声明 → 返回 []）：
          · 可穿边集 = `edge_types`（调用方按 relation_type 过滤）× `walk_policy.traversable`
          · 对称边（symmetric，如 connects_to）**无论 direction 一律双向走**；
            `direction=in`/`both` 时其余可穿边反查（"谁引用了我"）
          · 到达 `stop_at` 前缀的节点即终止该分支；深度 = min(depth, max_depth)
          · **每个可达节点保留一条最短见证路径**（逐层展开、全局去重、不穷举所有路径），
            条数 ≤ max_paths（防泛走噪音）
        返回 `[{end, hops:[{from, edge, to, way}]}]`，按"先近后远"排列。
        """
        sem = self.edge_semantics()
        policy = sem.get("walk_policy") or {}
        allowed = list(policy.get("traversable") or [])
        traversable = [t for t in (edge_types or allowed) if t in allowed]
        if not traversable:
            # B3：白名单为空也要留痕——「不能再往下走」的原因就是它（paths=0，无 hop 可反推边）
            _track_walk_stop(start_id, depth,
                             min(int(depth or 1), int(policy.get("max_depth") or 3)),
                             traversable, [], False, int(policy.get("max_paths") or 20))
            return []
        symmetric = set(sem.get("symmetric") or [])
        stop_at = tuple(policy.get("stop_at") or ())
        max_paths = int(policy.get("max_paths") or 20)
        limit = min(int(depth or 1), int(policy.get("max_depth") or 3))
        rev = self._reverse_index()

        paths: list[dict] = []
        seen = {start_id}
        stop_hit = False          # B3：展开过程中是否碰到过 stop_at 前缀（近似，见 _track_walk_stop）
        frontier: list[tuple] = [(start_id, [])]
        for _ in range(limit):
            next_frontier: list[tuple] = []
            for cur, hops in frontier:
                steps: list[tuple] = []
                for rel in traversable:
                    if direction in ("out", "both") or rel in symmetric:
                        steps += [(t, rel, "out", src) for t, src in self._targets_tagged(cur, rel)]
                    if direction in ("in", "both") or rel in symmetric:
                        steps += [(s, rel, "in", via) for s, via in self._sources_tagged(cur, rel)]
                for tgt, rel, way, via in steps:
                    if tgt in seen:
                        continue
                    seen.add(tgt)
                    hop = {"from": cur, "edge": rel, "to": tgt, "way": way}
                    if via is not None:
                        hop["via"] = via
                    new_hops = hops + [hop]
                    paths.append({"end": tgt, "hops": new_hops})
                    if len(paths) >= max_paths:
                        _track_walk_stop(start_id, depth, limit, traversable, paths,
                                         stop_hit, max_paths)
                        return paths
                    if not str(tgt).startswith(stop_at):
                        next_frontier.append((tgt, new_hops))
                    else:
                        stop_hit = True   # 碰到 stop_at 前缀：该分支终止，记录截断原因
            frontier = next_frontier
            if not frontier:
                break
        _track_walk_stop(start_id, depth, limit, traversable, paths, stop_hit, max_paths)
        return paths

    def reachable(self, start_id: str, depth: int = 2, direction: str = "out",
                  edge_types: list | None = None) -> list[str]:
        """`walk` 的去重终点集（"影响面"问法的形态；保序）。"""
        out: list[str] = []
        for path in self.walk(start_id, depth=depth, direction=direction,
                              edge_types=edge_types):
            if path["end"] not in out:
                out.append(path["end"])
        return out

