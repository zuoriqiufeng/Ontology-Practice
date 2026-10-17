"""observability.py — 过程级可观测（旁路累积器，44 号 §3.2，2026-10-12）

定位：把工具**内部**的决策点（检索走了哪条路、在哪儿被截断、判定为 partial 的依据、
灰度放行……）累积到**一次调用**的缓冲里，由调用出口一次性写进 trajectory 流，靠 `event`
字段区分（44 号 §3.1）：任务内过程事件落 trajectory（它已有 seq/args_hash/task_id，
能按 task 组装 timeline，且**只在 task_id 非空时写**，天然不污染压测/门禁流量）。

**作用域开在哪里（第 2 轮修正，2026-10-12）**：开在**真入口** `tools._timed_handler`
（HANDLERS 的每一项）。上一轮开在出口（`tools._wrap` / `tools._log_exempt_call`），
而那两处都在 handler **末尾**才执行——过程函数在工作途中 `track()` 时缓冲尚未建立，
决策点被静默丢弃（`search_path`/`walk_stop`/`guard_shadow` 真实调用下实测 0 条）。
出口那两层保留 `with call_scope(...)` 以兼容独立调用方，靠**可重入**复用同一缓冲。

为什么是旁路（44 号 §3.2）：过程函数（`walk` / `search_qdrant` /
`assess_confidence` / `check_action_risk`）**不能改返回值**——
`assess_confidence` 的 `gaps` 文本一旦变化，`measure_confidence` 的 45 例基线
全部漂移、门禁 ④ 会红。故埋点只调本模块的 `track()`（进程内 list，无 IO、
无返回值改变），**只增日志，不改主输出**（22 号 §0.4-4）。

先例：`supplement._track_dimension`（进程内累积 + 按 task 汇总）——本模块照它，
只是把累积粒度收到「一次调用」，并在出口刷盘（44 号 §3.2 的两步形态）。

纪律（44 号 §3.4 防噪音）：
- 只记**决策点**，不记「每一步」；
- 单次调用的事件数上限 `MAX_EVENTS`，超出丢弃并在事件里记 `dropped`；
- 开关 `config.OBSERVABILITY`（默认开；压测/门禁 `OBSERVABILITY=0` 关）；
- 不新开第四条流：事件复用 trajectory；
- 全程 try/except：埋点的任何异常都不影响 Tool 主流程。

**本体使用台账（P1 增补，2026-10-14）**：调用级日志此前只能证明「ID 出现在返回体里」
（`trajectory._collect_hits`），回答不了「本体在**哪个阶段**被用、**哪条**知识参与了答案、
这次答案**来自本体还是外部文档**」。故在同一套旁路机制上并列一条 per-call 台账
（`_ONTOLOGY`），由 `tools._timed_handler` 在真入口进出，出口一次性发一条 `ontology_use`。
台账**不参与返回值构造**，`OBSERVABILITY=0` 时退出即丢弃——与 `track()` 同一纪律。
"""

from __future__ import annotations

import contextvars
import re
import time
from contextlib import contextmanager

#: 单次调用的事件数上限（44 号 §3.4-2）：超出丢弃，并在该次调用的每条事件里记 dropped。
MAX_EVENTS = 10

#: 当前调用缓冲（None = 不在任何 call_scope 内）。用 ContextVar 而非模块全局：
#: 同一进程内并发的 Tool 调用（如 diagnose_db_link 内部并发检索）互不串味。
_CALL = contextvars.ContextVar("bkn_obs_call", default=None)

#: 本体台账各列表上限（防噪纪律同 MAX_EVENTS：超出只计数、不刷屏）。
MAX_USED = 8
MAX_DROPPED = 8
MAX_READS = 12

#: P3（图路径消耗）上限：边种类 / 出口分支 / 参与求交的候选实体。
MAX_GRAPH_EDGES = 8
MAX_GRAPH_BRANCHES = 6
MAX_GRAPH_OFFERED = 64

#: 来源分层：一份答案的知识从哪来（回答「本体到底起没起作用」的判别字段）。
SOURCE_LAYERS = ("bkn", "qdrant_doc", "sidecar", "logic")

#: 当前调用的本体使用台账（None = 不在任何 ontology_enter 作用域内）。
#: 与 _CALL 一样用 ContextVar：并发 Tool 调用互不串味；由 tools._timed_handler 在真入口进出。
_ONTOLOGY = contextvars.ContextVar("bkn_obs_ontology", default=None)

#: 冷启动预热台账（模块级，**不属于**任何调用作用域）。
#: 为什么需要它：`BKNResolver._load_all()` 在 plugin 的 _init() 里跑，而 _init() 的时机
#: 可能在**任何 Tool 调用之前**（模块导入期/测试夹具里）——那时没有 ontology 作用域，
#: 逐件 ontology_read 会被静默丢弃，「本进程读过全量 .bkn」这个事实就没了。
#: 故预热期单独记在这里，由**第一个** ontology_enter 收编（只收编一次），
#: 出口聚合成一条 bkn_load，不逐件灌进某次调用的 reads。
_WARM = {"active": False, "files": {}, "root": "", "t0": 0.0}


def note_cold_load(root: str = "", source: str = "") -> None:
    """开始记录冷启动预热读取（`BKNResolver._load_all` 调用）。无作用域也可用，只记内存。"""
    try:
        _WARM["active"] = True
        _WARM["t0"] = time.monotonic()
        if root and not _WARM["root"]:
            _WARM["root"] = str(root)[:80]
        if source:
            _warm_read(source)
    except Exception:
        pass


def _warm_read(source: str) -> None:
    try:
        item = _WARM["files"].get(source)
        if item is None:
            if len(_WARM["files"]) >= 96:   # 全量 .bkn 约 46 件，96 是宽裕上限
                return
            _WARM["files"][source] = 1
        else:
            _WARM["files"][source] = item + 1
    except Exception:
        pass


def ontology_enter():
    """开一次本体使用台账（真入口调用）。已在作用域内 → no-op（返回 None 哨兵）。

    与 call_scope 的可重入语义完全对齐：只有**最外层**（tools._timed_handler）持有 token，
    出口（_wrap / _log_exempt_call）再 enter 一次只是复用，不新建、不重复发事件。
    """
    try:
        if _ONTOLOGY.get() is not None:
            return None
        c = {"reads": {}, "used": [], "dropped": [], "sources": {},
             "stages": [], "cold": False, "cold_files": 0, "dropped_n": 0,
             # P3：图（边）消费台账。`offered` 只用于与返回体求交（paths_used），不直接发事件；
             # `offered_seen` 记全部去重候选（含形状不可比的）、`shape_gap` 记后者条数。
             "edges": {}, "branches": [], "ops": 0, "considered": 0,
             "offered": [], "offered_seen": set(), "shape_gap": 0,
             "t0": time.monotonic()}
        # 预热台账**不在 enter 收编**：_init() 常在本作用域内部才跑（首次调用触发），
        # 那时 _WARM 还是空的。收编与发事件统一放到 exit（那时预热已结束）。
        return _ONTOLOGY.set(c)
    except Exception:
        return None


def ontology_exit(token) -> dict:
    """收尾：复位作用域并返回 summary（无 token / 无活动 → 空 dict，不产生任何输出）。

    只「返回」，不发事件——发事件的动作在 call_scope._flush 里，那里已有 task_id 判空、
    脱敏与 8KB 压缩三件既有能力可复用，不再造第二套写盘路径。
    """
    try:
        c = _ONTOLOGY.get()
    except Exception:
        return {}
    if token is not None:
        try:
            _ONTOLOGY.reset(token)
        except Exception:
            pass
    # 冷启动（_load_all 预热）单独聚合成 bkn_load，不逐件灌进本次调用的 reads。
    if c:
        warm = _pop_warm()
        warm_n = warm.get("files") or 0
        if warm_n or c.get("cold_files"):
            c["cold"] = True
            c["cold_files"] = max(warm_n, c.get("cold_files") or 0)
            if warm.get("root"):
                c["root"] = warm["root"]
            # 可重入：`_wrap`/`_log_exempt_call` 的内层退出会先跑到这里，
            # 外层真入口退出时不得再发一条（一次调用恰好一条 bkn_load）。
            if not c.get("warm_emitted"):
                c["warm_emitted"] = True
                try:
                    _emit_warm_load(c, c["cold_files"])
                except Exception:
                    pass
            c["reads"] = {}   # 预热读取不进本次调用的 reads（那是 per-call 才有意义的量）
    return _summary(c)


def ontology_read(source: str, stage: str = "", alt: str = "", section: str = "") -> None:
    """记一次文件级本体读取（阶段/文件/节）。source 一律仓库相对路径（如 dimensions.bkn）。"""
    try:
        if _WARM["active"] and source:
            # 预热期（_load_all，无论当时有没有调用作用域）统一进 _WARM：
            # 它有独立上限、且出口只聚合成一条 bkn_load，不会把 per-call reads 灌满
            _warm_read(str(source))
            return
        c = _ONTOLOGY.get()
        if c is None or not source:
            return
        key = str(source)
        item = c["reads"].get(key)
        if item is None:
            if len(c["reads"]) >= MAX_READS:
                c["dropped_n"] += 1
                return
            item = {"n": 0}
            c["reads"][key] = item
        item["n"] += 1
        if stage:
            item.setdefault("stage", str(stage)[:40])
        if alt:
            item.setdefault("alt", str(alt)[:60])
        if section:
            item.setdefault("section", str(section)[:40])
    except Exception:
        pass


def ontology_use(entry: str, stage: str = "") -> None:
    """记一条实体级「参与了本次答案」的本体 ID（ID 形态见 trajectory 的命名空间白名单）。"""
    try:
        c = _ONTOLOGY.get()
        if c is None or not entry:
            return
        e = str(entry)[:80]
        if e in c["used"]:
            return
        if len(c["used"]) >= MAX_USED:
            c["dropped_n"] += 1
            return
        c["used"].append(e)
        if stage:
            _stage(c, stage)
    except Exception:
        pass


def ontology_drop(entry: str, reason: str = "") -> None:
    """记一条「本体里有、但这次没接上」的条目（归一失败 / 同义词未命中 / 归类 unknown…）。"""
    try:
        c = _ONTOLOGY.get()
        if c is None:
            return
        if len(c["dropped"]) >= MAX_DROPPED:
            c["dropped_n"] += 1
            return
        c["dropped"].append({"id": _scrub(str(entry))[:80], "reason": str(reason)[:40]})
    except Exception:
        pass


def ontology_source(layer: str, ref: str = "", n: int = 1) -> None:
    """记一次来源分层计数。layer ∈ SOURCE_LAYERS；ref 只收标识（拒绝绝对路径）。"""
    try:
        c = _ONTOLOGY.get()
        if c is None or layer not in SOURCE_LAYERS:
            return
        item = c["sources"].setdefault(layer, {"n": 0})
        item["n"] += int(n)
        if ref:
            refs = item.setdefault("refs", [])
            r = _scrub(str(ref))[:60]
            if r not in refs and len(refs) < 4:
                refs.append(r)
    except Exception:
        pass


def ontology_stage(stage: str) -> None:
    """记本次调用走过的阶段（去重保序，上限 8）——回答「本体在哪个阶段被用」。"""
    try:
        c = _ONTOLOGY.get()
        if c is None or not stage:
            return
        _stage(c, stage)
    except Exception:
        pass


def ontology_cold() -> None:
    """标记「本调用触发了一次性预热（_load_all 读全量 .bkn）」——该次读计数单独聚合。"""
    try:
        c = _ONTOLOGY.get()
        if c is not None:
            c["cold"] = True
    except Exception:
        pass


#: 输出识别器的命名空间白名单缓存。**必须缓存**：ontology_edge 在 walk 的三重循环里
#: 被反复调用，每次目标都做一次 `from .trajectory import ...` 是模块查找开销（实测占热路径大头）。
_ID_PREFIXES_CACHE: "frozenset | None" = None


def _id_prefixes() -> frozenset:
    """输出识别器的命名空间白名单（与 trajectory._collect_hits 同一份，只有一处定义）。"""
    global _ID_PREFIXES_CACHE
    if _ID_PREFIXES_CACHE is None:
        from .trajectory import _ID_PREFIXES
        _ID_PREFIXES_CACHE = _ID_PREFIXES
    return _ID_PREFIXES_CACHE


#: 是否**可能**被 _scrub 改写：只有「含数字」（IP 形态）或「含凭据关键字」两种。
#: 前提：调用点已先过 _is_ident（字符集排除空格/@/=），故 URL 口令与 `k=v` 凭据形态进不来，
#: 只剩 IP 与 `key:value`。用一次 search 换掉三次 sub——热路径上这是主要的可省成本。
_NEEDS_SCRUB_RE = re.compile(r"[0-9]|(?i:password|passwd|pwd|token|secret|apikey|api_key)")


def _clean(text: str) -> "str | None":
    """幽灵化+脱敏一步到位：形态不合规（或脱敏后不合规）→ None。热路径唯一入口。"""
    s = str(text)
    if not _is_ident(s):
        return None
    if _NEEDS_SCRUB_RE.search(s):
        s = _scrub(s)
        if not _is_ident(s):   # 脱敏产物（[IP已移除]）含方括号 → 不合规，丢弃
            return None
    return s


def ontology_edge(edge: str, direction: str = "out", n: int = 1,
                  node: str = "", targets=None) -> None:
    """记一次**图（边）消费**（P3）：走了哪条边、哪个方向、产出几个目标。

    埋点位置是 RelationTraverser._targets_tagged / _sources_tagged **两个漏斗**——
    全仓 27 个图调用点都经由它们，故两处即全覆盖（同 P2 把读点收在 _SectionDict._ensure）。
    只聚合计数、**不逐条 append**：漏斗在 walk 的三重循环里被反复调用。

    I9 注意：graph_edges 是 _flush 里**显式命名**的 kwarg，不经 log_event 的 _scrub_tree
    （P1 踩过同款坑：dropped[].id 曾把用户原文直达磁盘），故边名/目标 ID 在这里就先过
    _is_ident + _scrub。
    """
    try:
        c = _ONTOLOGY.get()
        if c is None or not edge:
            return
        # 这里**不能**加 `_WARM["active"]` 守卫（ontology_read 有，边台账没有）：
        # 预热期（_load_all）从不查边，而 `_WARM["active"]` 会一直保持到本次调用结束，
        # 加了就会把**进程内第一次调用**的全部图数据静默吞掉（实测踩过：首调无 graph_edges）。
        c["ops"] += 1
        # 候选总数用**运行总量**而不是事后对 edges 求和：edges 有 MAX_GRAPH_EDGES 上限，
        # 超出上限的边会被丢掉，若靠求和会把总量算少（实测：13 条边只报 8）。
        c["considered"] += int(n)
        e = _clean(edge)
        if not e:
            return
        e = e[:40]
        row = c["edges"].get(e)
        if row is None:
            if len(c["edges"]) >= MAX_GRAPH_EDGES:
                c["dropped_n"] += 1
                return
            row = {"out": 0, "in": 0, "t": 0}
            c["edges"][e] = row
        row["in" if str(direction) == "in" else "out"] += 1
        row["t"] += int(n)
        if targets:
            prefixes = _id_prefixes()
            _seen = c["offered_seen"]
            for t in targets:
                s = _clean(t)
                if not s or s in _seen:
                    continue
                if len(c["offered_seen"]) < MAX_GRAPH_OFFERED:
                    c["offered_seen"].add(s)
                # 只把**输出识别器认得的命名空间**放进 offered：paths_used 靠与返回体命中求交，
                # 若把 `compatibility:Oracle` 这类白名单外的目标也算进去，
                # 会凭空得出「本体给了路但一条没进输出」的假缺口（实测 design_solution 就是这样）。
                # 形状不可比的部分单独计数（paths_shape_gap），如实报，不混进命中率。
                ns = s.split(":", 1)[0] if ":" in s else ""
                if ns and ns in prefixes:
                    if len(c["offered"]) < MAX_GRAPH_OFFERED:
                        c["offered"].append(s)
                else:
                    c["shape_gap"] += 1
    except Exception:
        pass


def ontology_graph_branch(name: str) -> None:
    """记走了哪条**图出口**（P3）。用列表而非单值：同一次调用可先后走多条
    （与同事件的 stages 同构，避免后写覆盖前写）。"""
    try:
        c = _ONTOLOGY.get()
        if c is None or not name:
            return
        b = _scrub(str(name))[:40]
        if b not in c["branches"] and len(c["branches"]) < MAX_GRAPH_BRANCHES:
            c["branches"].append(b)
    except Exception:
        pass


def ontology_graph_used(hits) -> None:
    """求交（P3）：图给出的候选里**有多少真进了返回体** → paths_used。

    0 也要写：`本体给了路、一条都没进输出` 正是最需要看见的信号（与"没给路"不同）。
    """
    try:
        c = _ONTOLOGY.get()
        if c is None or not c.get("offered"):
            return
        hs = set()
        for h in hits or []:
            hs.add(str(h))
        c["paths_used"] = sum(1 for o in c["offered"] if o in hs)
    except Exception:
        pass

#: 「像标识」判定：只由 word 字符 + . - : / _ 组成（覆盖 process:iatrack / actions/x.bkn /
#: 4050 / ORA-01555）。带空格或中文的**自然语言**不做同步/同义词记账——那些要么命中、
#: 要么就是本来就不在索引里的任意用户输入，记下来只有噪音（实测被 20 万字符输出灌满）。
_IDENT_RE = re.compile(r"^[A-Za-z0-9_.:/-]{1,80}$")


def _is_ident(text: str) -> bool:
    try:
        return bool(_IDENT_RE.match(text))
    except Exception:
        return False


def _scrub(text: str) -> str:
    """写入前脱敏（I9）：复用 trajectory._scrub，不在本模块另写一套规则。

    为什么必须在这里做：ledger 的 `dropped`/`sources.refs` 属于 `_flush` 里**显式命名**的
    关键字参数，不经过 `log_event(**fields)` 的 `_scrub_tree`（那个只覆盖 extra fields）。
    实测（test_trajectory.test_scrub_masks_ip_and_credentials）就栽在这里：用户原文
    「连接 192.0.2.30.40 失败」进了 dropped[].id，原文直达磁盘。
    """
    try:
        from .trajectory import _scrub as _traj_scrub
        return _traj_scrub(text)
    except Exception:
        return text


def _stage(c: dict, stage: str) -> None:
    s = str(stage)[:40]
    if s and s not in c["stages"] and len(c["stages"]) < 8:
        c["stages"].append(s)


def _pop_warm() -> dict:
    """取出并清空预热台账（只被第一个收尾的调用收编一次）。"""
    try:
        out = {"files": len(_WARM["files"]), "sample": sorted(_WARM["files"].keys())[:8],
               "root": _WARM["root"], "t0": _WARM.get("t0")}
        _WARM["files"] = {}
        _WARM["active"] = False
        return out
    except Exception:
        return {}


def _emit_warm_load(c: dict, warm_n: int = 0) -> None:
    """冷启动预热：全量 .bkn 一次性读入内存 → 聚合成**一条** bkn_load，不逐件刷屏。"""
    from .trajectory import log_event
    ctx = _CALL.get() or {}
    task_id = ctx.get("task_id") or ""
    if not task_id or not enabled():
        return
    log_event(tool=c.get("tool") or "bkn_resolver", task_id=task_id, event="bkn_load",
              files=int(warm_n or c.get("cold_files") or 0), root=c.get("root") or None,
              ms=int((time.monotonic() - c.get("t0", 0)) * 1000))


def _summary(c: dict | None) -> dict:
    """把台账收敛成事件字段：空台账 / 开关关闭 → {}（调用方据此决定「一条都不发」）。"""
    try:
        if not c:
            return {}
        # P3：只有图交互（边被消费）而没有任何 ID 命中的调用同样要留痕，
        # 故把 edges/branches 纳入"非空"判据——否则「本体给了路但输出没体现」会一条不发。
        if not (c.get("reads") or c.get("used") or c.get("dropped")
                or c.get("sources") or c.get("edges") or c.get("branches")):
            return {}
        if not enabled():
            return {}
        reads = [dict(file=k, **v) for k, v in list(c["reads"].items())[:MAX_READS]]
        sources = {k: dict(v) for k, v in c["sources"].items()}
        out = {
            "stage": c["stages"][0] if c["stages"] else None,
            "stages": list(c["stages"]),
            "origin": (max(sources, key=lambda k: sources[k]["n"]) if sources else "logic"),
            "sources": sources,
            "bkn_read": len(c["reads"]),
            "bkn_used": len(c["used"]),
            "bkn_dropped": len(c["dropped"]),
            "used": list(c["used"])[:MAX_USED],
            "dropped": list(c["dropped"])[:MAX_DROPPED],
        }
        # ── P3：图（边）消费 ──
        if c.get("edges"):
            # 按**产出目标数**降序、再看查询次数：保证高产出边不会被 MAX_GRAPH_EDGES 截掉
            # （walk 会查很多"查到但为空"的边，不排序时它们会把有产出的边挤出上限）。
            _top = sorted(c["edges"].items(),
                          key=lambda kv: (-int(kv[1].get("t") or 0),
                                          -int(kv[1].get("out") or 0)))
            out["graph_edges"] = {k: dict(v) for k, v in _top[:MAX_GRAPH_EDGES]}
            # 本体图给出的候选路径总数（各边目标数之和；含同一目标经多条边重复出现）。
            # 取**运行总量**：不因 graph_edges 的展示上限（MAX_GRAPH_EDGES）而少算。
            out["paths_considered"] = int(c.get("considered") or 0)
            # 其中「形状可比」的去重候选数——它才是 paths_used 的分母（见 §口径）。
            out["paths_id_considered"] = len(c["offered"])
        if c.get("branches"):
            out["graph_branches"] = list(c["branches"])[:MAX_GRAPH_BRANCHES]
        if c.get("ops"):
            out["graph_ops"] = int(c["ops"])
        if c.get("paths_used") is not None:
            out["paths_used"] = int(c["paths_used"])
        if c.get("shape_gap"):
            # 目标是 `compatibility:Oracle` 这类**输出识别器白名单外**的命名空间（`risk:` 自 2026-10-14 起已入白名单，见 24 号 §5.4 R-11）——
            # 结构性不可比，单独计数，绝不混进命中率（否则会造出「本体给了没用」的假缺口）。
            out["paths_shape_gap"] = int(c["shape_gap"])
        if reads:
            out["reads"] = reads
        if c.get("cold"):
            out["cold"] = True
            out["cold_files"] = int(c.get("cold_files") or 0)
        if c.get("dropped_n"):
            out["overflow"] = int(c["dropped_n"])
        return out
    except Exception:
        return {}


def enabled() -> bool:
    """埋点总开关（config.OBSERVABILITY，默认开）。任何异常返回 False——宁可不记，不闹事。"""
    try:
        from .config import OBSERVABILITY
        return bool(OBSERVABILITY)
    except Exception:
        return False


def track(event: str, **fields) -> None:
    """旁路记一个决策点。无作用域 / 开关关闭 / 超上限 时静默丢弃。"""
    try:
        c = _CALL.get()
        if not c or not enabled():
            return
        buf = c.get("buf")
        if buf is None:
            return
        if len(buf) >= MAX_EVENTS:
            c["dropped"] = (c.get("dropped") or 0) + 1
            return
        buf.append({"event": event, **fields})
    except Exception:
        pass


#: 每次调用最多记多少条 mention 解析事件（防事件洪水；43 号 §7 D11）
MAX_MENTIONS = 8


def track_mention(mention: str, path: str = "", canonical: str = "") -> None:
    """记一次「提到的东西是怎么被解析的」（别名机制 v2：L0–L2）。

    `path ∈ {canonical, pattern, alias, unknown}`；每次调用最多 `MAX_MENTIONS` 条；
    无调用作用域 / 开关关闭时静默丢弃（与 `track` 同纪律）。
    """
    try:
        c = _CALL.get()
        if not c or not enabled():
            return
        n = int(c.get("mentions") or 0)
        if n >= MAX_MENTIONS:
            return
        c["mentions"] = n + 1
        track("mention_resolve", mention=str(mention or "")[:64], path=str(path or ""),
              canonical=(str(canonical or "")[:64] or None))
    except Exception:
        pass


@contextmanager
def call_scope(tool: str, ctx: dict | None = None):
    """一次工具调用的观测作用域：进入时建缓冲，退出时 flush 到 trajectory。

    ctx = Hermes **kwargs（取 task_id，与 trajectory.log_call 同一纪律与同一截断）。

    **可重入**：已在作用域内 → 复用最外层缓冲，不新建、不 flush。于是
    入口（tools._timed_handler）与出口（_wrap / _log_exempt_call）可以各套一层，
    一次调用仍然只 flush 一次；工作途中的 track() 落进最外层缓冲，不再丢。
    """
    cur = _CALL.get()
    if cur is not None:
        yield cur          # 嵌套：复用外层缓冲（tool/task_id 以外层入口为准）
        return
    ctx = ctx or {}
    c = {"tool": tool, "task_id": str(ctx.get("task_id") or "").strip()[:48],
         "buf": [], "dropped": 0}
    token = _CALL.set(c)
    try:
        yield c
    finally:
        try:
            _CALL.reset(token)
        except Exception:
            pass
        _flush(c)


def _flush(c: dict) -> None:
    """把缓冲一次性写进 trajectory（每条一行事件）。task_id 为空时不写（与 log_call 同纪律：
    压测/门禁/裸调用不落盘）。任何异常静默。

    P1：本体台账的 ontology_use 事件也在这里发——同一出口、同一 task_id 判空、同一脱敏与
    压缩，不再造第二套写盘路径。台账为空则一条不发（无本体交互的调用不产生噪音）。
    """
    if not c.get("task_id") or not enabled():
        return
    try:
        from .trajectory import log_event
        payload = c.get("ontology") or {}
        if payload:
            fields = dict(payload)
            fields.setdefault("tool", c.get("tool"))
            log_event(**fields, task_id=c["task_id"], event="ontology_use")
        for e in c.get("buf") or []:
            fields = dict(e)
            event = str(fields.pop("event", ""))
            # 事件字段自带 tool 时以它为准（B2 的 tool 是**裁剪点**：
            # tools._apply_output_budget 传被裁的 Tool、ContextLoader 传 "context_loader"）；
            # 没带才回落到作用域里的调用 Tool。**不能**直接 **e 去撞 log_event 的
            # 位置参数 tool——那会 TypeError 并被下面的 except 静默吞掉（实测踩过）。
            fields.setdefault("tool", c.get("tool"))
            for key in ("task_id", "seq", "ts", "kind", "dropped"):  # 条目身份键不可被事件覆盖
                fields.pop(key, None)
            log_event(**fields, task_id=c["task_id"], event=event,
                      dropped=c.get("dropped") or 0)
    except Exception:
        pass
