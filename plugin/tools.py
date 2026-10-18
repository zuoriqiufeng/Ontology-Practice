"""tools.py — 13 个 Tool Handler 实现

每个 Handler 接收 args → resolver 查询 → supplement → context_loader → 返回字符串
"""

from __future__ import annotations

import functools
import json
import re
import threading
import time
from contextlib import contextmanager
from typing import Optional
from .ask import ask as bkn_ask_handler
from .plan_check import check_plan as check_plan_handler
from .resolver import BKNResolver, synthesize_operation_knowledge
from .relations import RelationTraverser
from .context_loader import ContextLoader
from .observability import (  # 44 号 §3.2：过程级事件的旁路累积器
    call_scope, ontology_enter, ontology_exit, ontology_use, ontology_drop,
    ontology_source, ontology_stage, ontology_cold,
    ontology_graph_branch, ontology_graph_used, ontology_edge,   # P3：图路径消耗
)
from .supplement import assess_confidence, log_gap, fallback_to_qdrant, search_qdrant
from .supplement import (
    get_dimension_coverage, reset_dimension_coverage, _track_dimension,
    _is_valid_content, _payload_content,
)
from .supplement import (
    synthesize_diagnosis_knowledge, _get_known_dimensions,
    _build_dimension_hints, _get_dimension_priority,
)
# v3.6 chunk-aware search
from .supplement import _search_chunk_level, _search_mini_first, _expand_parents
from .constants import DB_ERROR_PREFIXES, SCENARIO_HINTS
from .config import BKN_ROOT, SEARCH_CHUNK_MODE


# 全局实例 (Plugin 启动时初始化)
_resolver = None
_traverser = None
_loader = None


# 兜底过滤：避免 BKN 中残留的命令字段被返回给上层
_COMMAND_FIELD_DENYLIST = {
    "检查命令", "执行命令", "执行步骤", "命令", "命令模板",
    "command", "commands", "script", "scripts", "cmd",
    "out_dir", "bin_dir", "default_value",
    "log_dir", "cache_dir", "alert_log_path", "core_dump_dir",
}

# 值级扫描：BKN free-text 中仍可能嵌入的 SQL/路径/端口/工具名/命令字符串
_COMMAND_VALUE_PATTERNS = [
    (
        re.compile(
            r'(?<![0-9])'
            r'(?:1521|3306|5432|1433|50000|5236|2881|2882|2883|8080|8000|8001|1688|'
            r'9030|8030|8040|22001|6379|27017|2181|'
            r'58086|58084|26803|26804|26837|40000)'
            r'(?![0-9])'
        ),
        "具体端口号",
    ),
    (re.compile(r'~/\.demo_product/|~/idata/'), "绝对路径"),
    (
        re.compile(
            r'ALTER[ \t\n\r\f\v]+DATABASE|ALTER[ \t\n\r\f\v]+TABLE|ALTER[ \t\n\r\f\v]+SYSTEM|'
            r'CREATE[ \t\n\r\f\v]+USER|GRANT[ \t\n\r\f\v]+|SET[ \t\n\r\f\v]+GLOBAL|'
            r'ADD[ \t\n\r\f\v]+SUPPLEMENTAL[ \t\n\r\f\v]+LOG|'
            r'SELECT[ \t\n\r\f\v]+.*[ \t\n\r\f\v]+FROM',
            re.IGNORECASE,
        ),
        "SQL片段",
    ),
    (re.compile(r'dumpredo|dumptxn|dumpdict|dumpasm|dumptab'), "具体诊断工具名"),
    (re.compile(r'--force'), "命令标志--force"),
    (re.compile(r'cd[ \t\n\r\f\v]+~/.demo_product|python[ \t\n\r\f\v]+.*check|uv[ \t\n\r\f\v]+run'), "可执行命令字符串"),
]


def _filter_command_fields(obj, leaked=None):
    """递归删除键名在命令黑名单中的字段，并对字符串值做命令/端口/路径/SQL 扫描。

    返回 sanitized 对象；发现的越界内容会记录到 `leaked` 列表（若传入）。
    """
    if leaked is None:
        leaked = []
    if isinstance(obj, dict):
        result = {}
        for k, v in obj.items():
            if str(k).lower() in _COMMAND_FIELD_DENYLIST:
                leaked.append(str(k))
                continue
            filtered_v = _filter_command_fields(v, leaked)
            if isinstance(filtered_v, str):
                for pat, label in _COMMAND_VALUE_PATTERNS:
                    if pat.search(filtered_v):
                        filtered_v = f"[{label}已移除 — 请加载对应 Skill 获取具体命令/参数]"
                        leaked.append(f"{k}: {label}")
                        break
            result[k] = filtered_v
        return result
    if isinstance(obj, list):
        return [_filter_command_fields(x, leaked) for x in obj]
    return obj


def _init():
    global _resolver, _traverser, _loader
    if _resolver is None:
        _resolver = BKNResolver(bkn_root=BKN_ROOT)
        _traverser = RelationTraverser(bkn_root=BKN_ROOT)
        _loader = ContextLoader()


def _json_len(obj):
    """json.dumps 后的字符长度（B2 埋点用）。取不到返回 None → 调用方省略该字段。

    **只量不改**：不参与任何返回值的构造（44 号 §3.2 的硬约束）。
    """
    try:
        return len(json.dumps(obj, ensure_ascii=False))
    except Exception:
        return None


def _apply_output_budget(result, tool_name):
    """给豁免 `_wrap()` 的 Tool 挂统一输出上限 (v3.9)。

    `search_qdrant` / `diagnose_db_link` / `check_action_risk` 的返回契约（原始
    JSON 串、多维知识合成、护栏自查）决定了它们不能进 `_wrap()`，这是显式豁免
    而非漏接。但它们也因此完全不经过 ContextLoader，没有任何总量兜底。

    这里复用 `ContextLoader._enforce_budget()` —— 已有实现、已有测试覆盖 ——
    不新写截断算法。由 `tools.output_max_chars` 控制，**默认 0 = 直接原样返回**，
    所以本函数的默认行为是 no-op。
    """
    from .config import TOOLS_OUTPUT_MAX_CHARS
    if TOOLS_OUTPUT_MAX_CHARS <= 0 or not isinstance(result, dict):
        return result
    _init()
    # B2（44 号 §3.3`budget_trim`）：裁剪前后各量一次体积，只进 trajectory 流，不改返回体。
    before_chars = _json_len(result)
    result, truncated = _loader._enforce_budget(result, TOOLS_OUTPUT_MAX_CHARS)
    if truncated:
        after_chars = _json_len(result)  # 紧跟裁剪后量取（此时尚未加 `_budget_note`）
        result["_budget_note"] = (
            f"输出超预算 {TOOLS_OUTPUT_MAX_CHARS} 字符，已按优先级截断"
        )
        from .observability import track
        _fields = {"tool": tool_name, "max_chars": TOOLS_OUTPUT_MAX_CHARS}
        if before_chars is not None:
            _fields["before_chars"] = before_chars
        if after_chars is not None:
            _fields["after_chars"] = after_chars
        track("budget_trim", **_fields)
    return result


# ========== O-域诊断类闭环（gap 反哺） ==========

# 哪些 Tool 的调用属于「诊断归类」语境——只有这些 Tool 的 gap 才挂 classes 字段。
_DIAG_CLASS_TOOLS = {"diagnose_error", "diagnose_db_link", "resolve_relation"}


def _resolve_diag_node(tool_name, args) -> str:
    """从 Tool 入参推出 O-域图节点 id（error:xxx / symptom:xxx / class:xxx）。

    推不出时返回 "" —— 表示该次调用不进入归类语境，gap 不挂 classes。
    """
    if tool_name == "diagnose_error":
        ec = (args.get("error_code") or "").strip()
        return f"error:{ec}" if ec else ""
    if tool_name == "diagnose_db_link":
        ec = (args.get("error_code") or "").strip()
        if ec:
            return f"error:{ec}"
        sy = (args.get("symptom") or "").strip()
        return f"symptom:{sy}" if sy else ""
    if tool_name == "resolve_relation":
        src = (args.get("source_entity") or "").strip()
        if src.startswith(("class:", "dimension:", "process:", "symptom:", "error:")):
            return src
    return ""


def _diag_class_extra(tool_name, args) -> "dict | None":
    """诊断目标闭环的附加字段 {"classes": [...]} —— 让 gap 可按诊断目标聚合。

    归类失败（图里查不到 has_class / suspected_in）时落 `dimension:unknown`：兜底一等公民，
    保证缺口可度量、可告警，而不是静默丢失（21/23 号：class:* 退场，目标为 process:*/dimension:*）。
    """
    if tool_name not in _DIAG_CLASS_TOOLS:
        return None
    node = _resolve_diag_node(tool_name, args)
    if not node:
        return None
    if node.startswith(("class:", "dimension:", "process:")):
        return {"classes": [node]}
    if _traverser is None:  # 防御：正常路径下 handler 已 _init()
        return None
    classes = _traverser.get_classes_for_symptom(node)
    return {"classes": classes or ["dimension:unknown"]}

# ── 盲区 3「想错了却有结果」的数据源（批 3-7） ──
# 标识符解析失败（resolve_synonym 未命中）时，把检索 top-1 候选连同分数写进 gap 的
# extra（{"synonym_candidates": [["incremental_stuck", 0.83], ...]}），与上面
# _diag_class_extra 挂 classes 完全同构。没有它，"LLM 猜错但查到了别的"就无从统计：
# assess_confidence 只记「没查到」，不记「拿不准」。scan_gaps.py 读它做「按未命中原文聚合」。
_SYNONYM_TOOLS = {"diagnose_error", "get_prerequisites", "resolve_operation", "resolve_relation"}


def _resolve_identifier_arg(tool_name, args) -> str:
    """取该 Tool 的标识符入参原文（resolve_synonym 的输入）。"""
    if tool_name == "diagnose_error":
        return (args.get("error_code") or "").strip()
    if tool_name in ("get_prerequisites", "resolve_operation"):
        return (args.get("operation") or "").strip()
    if tool_name == "resolve_relation":
        src = (args.get("source_entity") or "").strip()
        # O-域命名空间节点（class:/error:/symptom:/log:/tool:）是规范写法，无别名问题
        return "" if ":" in src else src
    return ""


def _synonym_candidates_extra(tool_name, args) -> "dict | None":
    """标识符未命中时的检索候选 {"synonym_candidates": [[id, score], ...]}。

    与 _diag_class_extra 同构：命中解析（resolve_synonym 改变原文）→ 不记；
    未命中 → BM25 top-1 候选 + 分数，供「按未命中原文聚合」判定该词是否值得固化
    （判据：≥3 次且检索命中分散/低分，见 16 号批 3-1）。
    """
    if tool_name not in _SYNONYM_TOOLS:
        return None
    text = _resolve_identifier_arg(tool_name, args)
    if not text:
        return None
    resolved = _resolver.resolve_synonym(text)
    if resolved != text:  # 精确键通道命中 → 不需要候选
        return None
    try:
        from .bm25 import bm25_search
        # collection=None 显式声明「别名候选只查主集合」——本路径服务于 BKN 实体 ID 归一，
        # 与用户指定的检索集合无关（21 号 2E 审计确认，非漏传）
        hits = bm25_search(text, top_k=1, collection=None)
        if not hits:
            return None
        top = hits[0]
        return {"synonym_candidates": [[top.get("id", ""), round(top.get("bm25_score", 0.0), 4)]]}
    except Exception:  # 检索失败不阻断主流程（与 log_gap 的静默哲学一致）
        return None


# ========== 2A 统计埋点：耗时 / 输出体积 ==========

_call_ctx = threading.local()  # 每次 Tool 调用的起点（HANDLERS 不存在嵌套调用，安全）

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3000-\u303f\uff01-\uff5e]")  # 汉字 + CJK 标点/全角


def _estimate_tokens(text: str) -> int:
    """粗估 token 数（非精确分词，仅供趋势分析）：CJK ≈1 token/字，其余 ≈4 字符/token。"""
    if not text:
        return 0
    cjk = len(_CJK_RE.findall(text))
    return cjk + (len(text) - cjk) // 4


def _usage_metrics(final) -> dict:
    """从最终返回计算 usage 埋点字段：out_chars / out_tokens_est / duration_ms。

    final 为 handler 最终返回（str 或 dict）；duration 取 _call_ctx.t0（首次调用含懒初始化冷启动，
    属预期行为——冷启动成本本来就该被观测）。
    """
    text = final if isinstance(final, str) else json.dumps(final, ensure_ascii=False, default=str)
    metrics = {"out_chars": len(text), "out_tokens_est": _estimate_tokens(text)}
    t0 = getattr(_call_ctx, "t0", None)
    if t0 is not None:
        metrics["duration_ms"] = int((time.monotonic() - t0) * 1000)
    return metrics


def _timed_handler(fn, tool_name=None):
    """Handler **真入口**包装：① duration 起点；② 过程级观测作用域；③ 进程级版本观测。

    44 号 §3.2 第 2 轮修正（2026-10-12）：`call_scope` 必须套在**真入口**（HANDLERS 的
    每一项）上。上一轮把它套在出口（`_wrap` / `_log_exempt_call`，都在 handler 末尾才
    执行），于是**工作途中**发的决策点全丢：`search_qdrant` 的检索路径（B1）、
    `RelationTraverser.walk` 的截断判定（B3）、`check_action_risk` 的灰度放行（B4）
    在真实调用下实测 0 条。`call_scope` 可重入：出口那层再套一次只是复用本缓冲，
    一次调用仍然只 flush 一次。

    B6（`bkn_reload`）：`scripts/bkn_version.py --write` 是独立进程、不 import 插件，
    故插件侧在**本进程首次真入口调用**时观测一次版本（`loaded_version.observe_loaded_version`，
    每进程一次；事件按 (from→to) 去重）。
    """
    name = tool_name or getattr(fn, "__name__", "unknown")

    @functools.wraps(fn)
    def wrapper(args, **kwargs):
        _call_ctx.t0 = time.monotonic()
        try:
            from .loaded_version import observe_loaded_version
            observe_loaded_version("tool_entry")
        except Exception:      # 自证/观测不得影响主流程（loaded_version 内部已静默，此为双保险）
            pass
        with _call_scope(name, kwargs):
            return fn(args, **kwargs)
    return wrapper


@contextmanager
def _call_scope(tool: str, ctx: dict | None = None):
    """调用作用域：本体台账收尾必须早于事件刷盘，故在此固定次序。

    call_scope 的 finally 里做的是 _CALL.reset + _flush；若把 ontology_exit 放在
    with 块之后，_flush 早已跑完，summary 根本赶不上发事件（with 是「退出即 flush」，
    与外层 finally 的先后正好相反）。故这里显式按 (1) 复位本体作用域 → (2) 退出
    call_scope 触发刷盘 的次序收尾——一次调用恰好一条 ontology_use。
    """
    with call_scope(tool, ctx) as c:
        tok = ontology_enter()
        try:
            yield c
        finally:
            try:
                _sum = ontology_exit(tok)
                if _sum:
                    c["ontology"] = _sum
            except Exception:   # 埋点不得影响主流程
                pass


#: Tool → 本体使用主阶段（P1 台账的 stage 字段来源；回答「本体在哪个阶段被用」）。
#: 只标**主阶段**，不追求穷举内部子步骤——子步骤由各过程埋点（search_path/walk_stop/…）承载。
_ONTOLOGY_STAGE = {
    "query_product": "product",
    "explain_architecture": "architecture",
    "design_solution": "solution",
    "check_compatibility": "compatibility",
    "list_scenarios": "scenario",
    "diagnose_error": "diagnose_code",
    "diagnose_db_link": "diagnose_db",
    "get_prerequisites": "prerequisite",
    "resolve_relation": "relation",
    "resolve_operation": "operation",
    "search_qdrant": "retrieval",
    "check_action_risk": "risk_guard",
    "diagnose_mechanism": "mechanism",
}

#: Tool → 答案主来源层（P1）。除显式检索出口外，13 个 Tool 的**内容**都来自 bkn/ 的
#: 解析结果或本体边的拼装；search_qdrant 是唯一的「外部文档」出口。侧车/纯逻辑由
#: _record_answer_source / _note_code_outcome 另记，取计数最多的一层为 origin。
_ONTOLOGY_ORIGIN = {
    "search_qdrant": "qdrant_doc",
}


#: 「裸名 id」字段 → 命名空间前缀（P1）。BKN 里 scenario/action 等对象在返回体里只给裸名
#: （如 bigdata_pipeline / create_compare），而 bkn_hits 的白名单只认「前缀:值」形态——
#: 故这里按**已知字段 + 已知命名空间**补前缀，只补白名单内的命名空间，不做启发式猜测。
_ID_FIELDS = (
    ("scenarios", "scenario", "id"),
    ("operations", "action", "capability"),
)


def _record_ontology_body(tool_name: str, body) -> None:
    """从**返回体**抽「参与了本次答案」的本体 ID / 文档命中数（P1 台账）。

    - ID 抽取**复用** trajectory._collect_hits 的同一份命名空间白名单与同一份正则
      （不新写一套抽取规则——两处口径一旦漂移，'bkn_hits' 与 'bkn_used' 就没法对比）；
    - 'document_id'/'large_chunk_id' 只从 **structured** 返回体里数（search_qdrant 走豁免
      出口，raw_result 就是命中列表；JSON 串里的引号在文本层一律是 '\"document_id\":'，
      与这里的 '['document_id']' 键名形态不同，故不会互相误计）；
    - 只读、只累积；任何异常静默。
    """
    try:
        ontology_stage(_ONTOLOGY_STAGE.get(tool_name) or tool_name)
        ontology_source(_ONTOLOGY_ORIGIN.get(tool_name) or "bkn", ref=tool_name, n=0)
    except Exception:
        pass
    try:
        from .trajectory import _collect_hits, _ID_PREFIXES
        _hits = _collect_hits(body)
        for hid in _hits:
            ontology_use(hid)
        # P3：图给出的候选里有多少真进了返回体（0 也记——「本体给了路但输出没体现」是强信号）
        ontology_graph_used(_hits)
        # 裸名补前缀：只认白名单内的命名空间与其已知字段（不猜、不递归全树）
        if isinstance(body, dict):
            for key, ns, id_field in _ID_FIELDS:
                if ns not in _ID_PREFIXES:
                    continue
                for item in (body.get(key) or []):
                    if isinstance(item, dict) and item.get(id_field):
                        ontology_use(f"{ns}:{item[id_field]}")
                    elif isinstance(item, str) and item:
                        ontology_use(f"{ns}:{item}")
    except Exception:
        pass
    try:
        docs = 0

        def _walk(obj):
            nonlocal docs
            if isinstance(obj, dict):
                if obj.get("document_id") or obj.get("large_chunk_id"):
                    docs += 1
                for v in obj.values():
                    _walk(v)
            elif isinstance(obj, (list, tuple)):
                for v in obj:
                    _walk(v)

        _walk(body)
        if docs:
            ontology_source("qdrant_doc", n=docs)
    except Exception:
        pass


def _note_code_outcome(code: str) -> None:
    """记一次错误码入口的结果（P2）：命中归一侧车 / 未登记则记 dropped（本体审阅用）。

    只读 plugin/error_codes.yaml（值数据侧车），不改任何判定；异常静默。
    """
    try:
        if not code:
            return
        from .resolver import _load_error_codes
        try:
            codes = _load_error_codes() or {}
        except Exception:
            codes = {}
        ontology_source("sidecar", ref="error_codes.yaml", n=1)
        if not (code in codes or code.lstrip("-") in codes):
            ontology_drop(code, "code_unmapped")
    except Exception:
        pass


def _record_answer_source(tool_name: str, args: dict, risk: dict | None,
                          raw_result=None) -> None:
    """diagnose_error / diagnose_db_link 的**答案来源**判定（P1）。

    回答「本体真的起功能作用了吗，还是侧车/纯逻辑/外部文档在兜」：
    - sidecar：码在 plugin/error_codes.yaml（值数据层，**不是本体**）；
    - bkn_edge：命中 look 的维度/嫌疑进程/取证日志来自本体边；
    - bkn_used 由 _record_ontology_body 从返回体抽（两跳拼装出来的 dim/skill id）；
    - qdrant_doc：raw_result 里的外部文档命中数。
    """
    try:
        from .resolver import _load_error_codes
    except Exception:
        _load_error_codes = None
    try:
        code = str((args or {}).get("error_code") or "").strip()
        sidecar = False
        if code and _load_error_codes:
            try:
                codes = _load_error_codes() or {}
                sidecar = code in codes or code.lstrip("-") in codes
            except Exception:
                sidecar = False
        risk = risk or {}
        bkn_keys = sorted(k for k in ("dimensions", "suspected_process", "diagnosed_skills",
                                      "observed_logs", "retrieval_guide")
                          if risk.get(k))
        ontology_stage("diagnose_code")
        if risk:
            ontology_source("bkn", ref="error_codes.bkn", n=1)
        if sidecar:
            ontology_source("sidecar", ref="error_codes.yaml", n=1)
        docs = 0
        try:
            from .trajectory import _collect_hits
            _ = _collect_hits(raw_result)
        except Exception:
            pass

        def _walk(obj):
            nonlocal docs
            if isinstance(obj, dict):
                if obj.get("document_id") or obj.get("large_chunk_id"):
                    docs += 1
                for v in obj.values():
                    _walk(v)
            elif isinstance(obj, (list, tuple)):
                for v in obj:
                    _walk(v)

        _walk(raw_result)
        if docs:
            ontology_source("qdrant_doc", n=docs)
        from .observability import track
        track("answer_source", tool=tool_name, code=code or None, code_known=bool(risk),
              sidecar=sidecar, bkn_keys=bkn_keys or None, docs=docs or None)
    except Exception:
        pass


def _log_args(args) -> dict:
    """入参快照（21 号 2B 后 gap_log 仅 partial 时写 params，full 路径的入参观测靠此字段）。

    Tool 合并/裁撤裁定（21 号 P2 观测项）需要「怎么调用」：记哪些 operation、什么 source/target。
    截断长字符串、剔 task_id 与空值，保证单行体积可控。
    """
    snapshot = {}
    for k, v in (args or {}).items():
        if k == "task_id" or v in (None, "", [], {}):
            continue
        snapshot[k] = v[:80] if isinstance(v, str) else v
    return snapshot


def _session_ctx(ctx) -> dict:
    """从 Hermes 的 `**kwargs` 提取会话标识（批 U-0，2026-10-11）。

    **唯一通道＝kwargs**：Hermes 以 `entry.handler(args, **kwargs)` 调用（kwargs 携带
    `task_id`/`session_id`）；旧实现按 `args.get("task_id")` 取 → 9 个 Tool 恒空、
    真假流量不可分（22 号 §1.2#10b）。非空才写字段——压测/裸脚本调用保持旧条目形状。
    """
    ctx = ctx or {}
    out = {}
    tid = str(ctx.get("task_id") or "").strip()
    sid = str(ctx.get("session_id") or "").strip()
    if tid:
        out["task_id"] = tid[:48]
    if sid:
        out["session_id"] = sid[:48]
    return out


def _log_exempt_call(tool_name, args, kwargs, raw_result, final, usage_fields=None, assess=True):
    """豁免 Tool 的统一埋点（批 U-1 轨迹 + 批 4-2 置信度，2026-10-12）。

    三个豁免 `_wrap` 的 Tool 此前**完全不判置信度、不进 gap_log**（22 号 §1.4#18），
    本函数一处收口：`assess_confidence` → usage_log（confidence + 工具自有字段 + 会话 + 体积/耗时）
    → 非 full 写 gap_log → 任务级轨迹事件（U-1）。**只增日志，不改主输出**（22 号 §0.4-4）。
    任何异常静默——埋点不得影响主流程。

    44 号 §3.2：外面套一次 `observability.call_scope` —— 本函数内部（`assess_confidence`
    等过程函数）的 `track()` 累积在这里，出口一次性刷进 trajectory（`kind: "event"`）。
    """
    with _call_scope(tool_name, kwargs):
        try:
            _sctx = _session_ctx(kwargs)
            # P1 本体台账：先按**返回体**记账（raw_result 是本题 Tool 自己的产物；
            # search_qdrant 走本豁免出口，raw_result 就是命中列表 → 文档来源在这里数）
            _record_ontology_body(tool_name, raw_result)
            if assess:
                confidence, gaps = assess_confidence(raw_result, args, tool_name)
            else:
                confidence, gaps = "full", []  # 计算型输出（摘要/核对）不判知识覆盖，避免 gap 噪声
            from .usage_log import log_usage
            from .trajectory import log_call
            _metrics = _usage_metrics(final)
            # 44 号 §6 批 3：补 args + record_type——豁免 Tool 此前不写 args，是「args 35%」
            # 假象的一半来源（另一半见下方 _wrap）。args 置于 usage_fields 之前：三个调用点的
            # usage_fields 都不含 args 键（一旦含，Python 报重复关键字 → 整条埋点被静默吞掉）。
            log_usage(tool_name, record_type="call", confidence=confidence, args=_log_args(args),
                      **(usage_fields or {}), **_sctx, **_metrics)
            if assess and confidence != "full":
                log_gap(tool_name, args, confidence, gaps, task_id=_sctx.get("task_id"))
            log_call(tool_name, args_snapshot=_log_args(args), ctx=kwargs, result=raw_result,
                     confidence=confidence, gaps=gaps,
                     out_chars=_metrics.get("out_chars"),
                     duration_ms=_metrics.get("duration_ms"))
        except Exception:
            pass



def _wrap(result, args, tool_name, ctx=None):
    """通用包装: 置信度 + gap_log + Qdrant 兜底(SEARCH_DEFER_TO_HERMES=true 时仍执行内部兜底,
    并额外返回 `_search_deferred`/`_instruction` 供 Agent 自主补查) + context_loader 处理

    `ctx`（批 U-0）：Hermes `**kwargs` 的会话上下文（`_session_ctx` 提取；缺省不写字段）。

    44 号 §3.2：外面套一次 `observability.call_scope`——本函数内部（`assess_confidence` /
    `fallback_to_qdrant` 等过程函数）的 `track()` 累积在这里，出口一次性刷进 trajectory。"""
    with _call_scope(tool_name, ctx):
        _sctx = _session_ctx(ctx)
        # P1 本体台账：result 是**包装前**的原始返回体（与 log_call 抽 bkn_hits 用的是同一份），
        # 由此抽「参与了本次答案」的本体 ID 与阶段；不改 wrapped，不影响任何返回值。
        _record_ontology_body(tool_name, result)
        confidence, gaps = assess_confidence(result, args, tool_name)
        wrapped = result if isinstance(result, dict) else {"data": result}
        wrapped["confidence"] = confidence
        wrapped["gaps"] = gaps
        wrapped["_tool_name"] = tool_name  # v2.0: 传递Tool名给supplement做查询分解(v2.3: +质量评估)
        if confidence != "full":
            _extra = _diag_class_extra(tool_name, args) or {}
            _cand = _synonym_candidates_extra(tool_name, args) or {}
            if _cand:
                _extra.update(_cand)
            log_gap(tool_name, args, confidence, gaps, extra=_extra or None, task_id=_sctx.get("task_id"))
        # 批 5-7（22 号 5b-7 ①）：结构化 Skill 注入——get_prerequisites 已带 capability，
        # 用图查 get_skills_for_action() 替代 supplement 的正则兜底（正则保留为兼容层）。
        # 红线 1（`- **负责 Skill**: \`xxx\``）由 resolver 输出承载，此处注入的是结构化副本。
        if tool_name == "get_prerequisites" and isinstance(wrapped, dict):
            cap = wrapped.get("capability")
            if cap and _traverser is not None:
                skills = _traverser.get_skills_for_action(cap)
                if skills:
                    wrapped["_structured_skills"] = skills
        if confidence == "none" or confidence == "partial":
            wrapped = fallback_to_qdrant(args, wrapped, gaps=gaps)
        # 统一过滤可能残留的命令字段，作为 BKN 边界安全网
        leaked = []
        wrapped = _filter_command_fields(wrapped, leaked)
        if leaked:
            wrapped.setdefault("gaps", []).extend(
                f"BKN边界安全网拦截: {x}" for x in sorted(set(leaked))
            )
        # v1.5 (P3-1): 使用统计（静默，不影响主流程）；2A: 补耗时/输出体积（取 ContextLoader 后的最终输出）
        # 批 U-0（2026-10-11）：会话标识只认 Hermes 的 **kwargs 通道**（`_sctx`）——旧实现按 args 取，
        # 而真实通道是 kwargs → 9 个 Tool 恒空、真假流量不可分（22 号 §1.2#10b）。
        from .usage_log import log_usage
        from .trajectory import log_call
        final = _loader.process(wrapped, tool_name)
        _snap = _log_args(args)
        _metrics = _usage_metrics(final)
        # 44 号 §6 批 3：标注记录类别（工具调用级）——通用字段完整率按类分组的前提
        log_usage(tool_name, record_type="call", confidence=confidence, args=_snap,
                  **_sctx, **_metrics)
        # 批 U-1（2026-10-12）：任务级轨迹事件（仅真实会话；result 用**包装前**原始返回体抽 bkn_hits）
        log_call(tool_name, args_snapshot=_snap, ctx=ctx, result=result, confidence=confidence,
                 gaps=gaps, out_chars=_metrics.get("out_chars"),
                 duration_ms=_metrics.get("duration_ms"))
        return final


# ========== Tool 1: query_product ==========

def query_product(args, **kwargs):
    _init()
    aspect = args.get("aspect", "overview")
    competitor = args.get("competitor")
    result = _resolver.query_product(aspect)
    if competitor and aspect == "competitors":
        result["competitor"] = competitor
    return _wrap(result, args, "query_product", ctx=kwargs)


# ========== Tool 2: explain_architecture ==========

def explain_architecture(args, **kwargs):
    _init()
    topic = args.get("topic", "all")
    result = _resolver.query_architecture(topic)
    if not result:
        return _wrap({"error": f"未找到主题: {topic}", "available_topics": [
            "full_sync", "incremental_sync", "topology", "transaction",
            "validation", "performance", "oracle_log", "mssql_mode", "all"
        ]}, args, "explain_architecture", ctx=kwargs)
    return _wrap(result, args, "explain_architecture", ctx=kwargs)


# ========== Tool 3: design_solution ==========

def _extract_from_relations(expanded: dict, rel_type: str) -> list[str]:
    """从 expanded.relations 中提取所有实体指定关系类型的目标列表"""
    items = set()
    for entity, rels in expanded.get("relations", {}).items():
        if isinstance(rels, dict):
            for tgt in rels.get(rel_type, []):
                if isinstance(tgt, str):
                    items.add(tgt)
    return sorted(items)


def design_solution(args, **kwargs):
    _init()
    source = args.get("source", "")
    target = args.get("target", "")
    hint = args.get("scenario_hint", "auto")

    # scenario_hint 映射：英文 enum -> 中文场景名；无法解析时回退自动匹配
    # 21 号 2C：hint→场景名映射收敛到 constants.SCENARIO_HINTS（与 schema enum 同源）
    hinted_name = SCENARIO_HINTS.get(hint)
    if hinted_name:
        # 尝试按 hinted 场景名加载对应文件；失败则回退自动匹配
        scenario = _resolver.match_scenario_by_name(hinted_name, source, target)
    else:
        scenario = _resolver.match_scenario(source, target)

    expanded = _traverser.expand(f"scenario:{scenario.get('scenario', 'migration')}", depth=3)
    compat = _resolver.check_compatibility(source, target)
    result = {
        "scenario": scenario.get("scenario", "跨平台迁移"),
        "description": scenario.get("description", ""),
        "compatibility": compat,
        "relations": expanded.get("relations", {}),
        # v2.4: 从 relations 提取常用字段到顶层
        "prerequisites": _extract_from_relations(expanded, "prerequisite"),
        "constraints": _extract_from_relations(expanded, "constrains"),
        "risks": _extract_from_relations(expanded, "risks_of"),
    }
    return _wrap(result, args, "design_solution", ctx=kwargs)


# ========== Tool 4: check_compatibility ==========

def check_compatibility(args, **kwargs):
    _init()
    source = args.get("source", "")
    target = args.get("target", "")
    source_version = args.get("source_version")
    target_version = args.get("target_version")
    result = _resolver.check_compatibility(
        source, target,
        source_version=source_version,
        target_version=target_version,
    )
    return _wrap(result, args, "check_compatibility", ctx=kwargs)


# ========== Tool 5: list_scenarios ==========

def list_scenarios(args, **kwargs):
    _init()
    keywords = args.get("keywords", [])
    # 规范 keywords 类型：字符串转为单元素列表，其他非列表值按空列表处理
    if isinstance(keywords, str):
        keywords = [keywords]
    elif not isinstance(keywords, list):
        keywords = []
    scenarios = _resolver.list_scenarios()
    if keywords:
        kw_lower = [k.lower() for k in keywords if isinstance(k, str)]
        scenarios = [s for s in scenarios
                     if any(kw in " ".join(s.get("keywords", [])).lower() for kw in kw_lower)]
    result = {"scenarios": scenarios}
    return _wrap(result, args, "list_scenarios", ctx=kwargs)


# ========== Tool 6: diagnose_error ==========

def diagnose_error(args, **kwargs):
    _init()
    error_code = args.get("error_code", "")
    # 批 3-1 + 批 5-9：入口归一（精确键通道）——先同址别名（登录失败 → ORA-01017、
    # 2276 → YAS-02276 这类**语义别名**，须先查以免被格式归一吞掉），再格式归一
    # （4073 → -4073、ORA1555 → ORA-01555）。检索通道不需要归一，此处只保精确命中。
    # P2 埋点次序：先归一、再记账——「4050」这种裸码经 normalize 才是「-4050」，
    # 若在归一前记 synonym_miss 会造出假缺口（实测：4050 明明已登记却报 dropped）。
    _raw_code = error_code
    error_code = _resolver.normalize_error_code(_resolver.resolve_synonym(error_code))
    # 32 号（码只作入口，含义进推理链）：可选带上该码所在的**日志消息文本**与**日志来源**——
    # 有文本才能按语义规则定"含义类别"；有来源才能定"嫌疑进程"。两者都可缺，缺了会如实写进 needs。
    message = str(args.get("message") or "")
    log_source = str(args.get("log_source") or "")
    result = _resolver.get_risk(error_code, message=message, log_source=log_source)
    _note_code_outcome(error_code)
    if _raw_code != error_code:
        try:
            ontology_use(error_code, stage="code_norm")
        except Exception:
            pass
    if not result:
        return _wrap({
            "error_code": error_code,
            "diagnosis": "未给出错误码或消息文本——至少给一个（只给码会缺含义，只给文本没有归一码）",
        }, args, "diagnose_error", ctx=kwargs)
    # 25 号 get_risk 已 stub 化（error_code/retrieval_guide/suspected_process/dimensions/
    # aliases/unknown_rule）。旧契约的 diagnosis/raw 组装随之作废（21 号 2B）：
    # get_risk 从不返回 raw，旧代码把 diagnosis 组装成空串，再被 REQUIRED_FIELDS/
    # _deep_check 连打 3 个 gap——已登记错误码 100% 冤判 partial。直接透传 stub。
    # 68 号 E-2③：处置锚点（只给「去哪一节看」）；无匹配维度时为空列表，不臆断。
    try:
        _th = _treatment_hint(result.get("dimensions"))
        if _th:
            result["treatment_hint"] = _th
        from .observability import track
        track("treatment_hint", tool="diagnose_error",
              dimensions=len(result.get("dimensions") or []), hits=len(_th),
              skills=sorted({h["skill"] for h in _th}) or None)
    except Exception:
        pass
    # P1：答案来源判定（本体边 / 码表侧车 / 纯逻辑 / 外部文档）——「本体起没起作用」的判据。
    _record_answer_source("diagnose_error", args, result)
    return _wrap(dict(result), args, "diagnose_error", ctx=kwargs)


# ========== Tool 7: get_prerequisites ==========

def get_prerequisites(args, **kwargs):
    _init()
    operation = args.get("operation", "")
    # 批 3-1：入口归一——「启动规则」/「创建规则」这类口语写法经同址别名落到 capability
    operation = _resolver.resolve_synonym(operation)
    result = _resolver.get_prerequisites(operation)
    if not result:
        return _wrap({
            "operation": operation,
            "prerequisites": "未找到该操作的前置条件, 请检查操作名",
            "available": _resolver.list_operations(),
        }, args, "get_prerequisites", ctx=kwargs)
    # 规范化到文档约定的 schema：顶层必须包含 operation 与 prerequisites
    normalized = {
        "operation": operation,
        "prerequisites": result.get("raw", ""),
    }
    normalized.update(result)
    # v3.10: raw 与 prerequisites 同取自 result["raw"]，`update` 之后两者逐字节相同（批 2-1 派生
    # 实现起，schema enum 的 8 个 operation 逐个经 lookup_operation 解析，== 均为 True），不再重复
    # 输出。删之前必须先确认 prerequisites 已在 ToonFormatter._FULL_CONTENT_KEYS 里——否则这里删掉
    # raw 就等于把「显示不全」升级成真丢内容。条件式删除的理由同上：只在完全相同时删。
    if normalized.get("raw") == normalized.get("prerequisites"):
        normalized.pop("raw")
    return _wrap(normalized, args, "get_prerequisites", ctx=kwargs)


# ========== Tool 8: resolve_relation ==========

def _manifest_related_skills() -> list:
    """批 7-4：related_skills 默认集经 manifest 解析（entry 尾段为显示名）。"""
    ids = [
        ("skill:demo_product-rule-manager", "需要查看/修改规则配置"),
        ("skill:demo_product-db-diagnostics", "需要执行 dump 工具深度排查"),
        ("skill:demo_product-log-analyzer", "需要分析规则日志"),
        ("skill:demo_product-diff-op", "需要对比源目两端表数据"),
        ("skill:demo_product-iadebug", "需要处理 -4002 位点异常"),
    ]
    out = []
    for sid, when in ids:
        try:
            from .manifest import resolve_skill_id
            item = resolve_skill_id(sid)
            name = (item.get("entry", "") if item else "").rstrip("/").split("/")[-1]
            out.append({"name": name or sid.split(":", 1)[-1], "when": when})
        except Exception:
            out.append({"name": sid.split(":", 1)[-1], "when": when})
    return out


def _track_reasoning_path(tool: str, entry, axis: str, nodes=None, edges=None,
                          hops: int = 1, terminal: str = "") -> None:
    """记一次**推理路径**事件（trajectory；43 号 §7 D10）。

    只记路径的形状（轴 / 节点 / 边 / 跳数 / 终止原因），不记原始文本；
    无 task_id 时由 `log_event` 静默丢弃（探针/门禁流量不落生产轨迹）。
    """
    try:
        from .observability import track
        track("reasoning_path", tool=tool, entry=str(entry or "")[:80], axis=axis,
              nodes=[str(n) for n in (nodes or [])][:8],
              edges=[str(e) for e in (edges or [])][:8],
              hops=int(hops), terminal=terminal)
    except Exception:
        pass


def _resolve_diagnosis_path(source: str) -> dict:
    """O-域单跳查询出口：症状/错误码 → 完整诊断路径（20 号方案对象轴优先）。

    对象轴（优先）：症状/错误码 → suspected_in → process:* → 进程链
    （skills = 进程关联 Skill，evidence_logs = 进程日志标识，sources = 进程检索源）。
    跨切面回退：suspected_in 未命中（如 data_diff/resource_pressure/state_conflict 类故障）
    走 has_class → class:*（4 个跨切面维度类）→ diagnosed_by/observed_in/检索源。
    """
    processes: list[str] = []
    if not source.startswith(("class:", "dimension:", "process:")):
        processes = _traverser.get_targets(source, "suspected_in")

    if processes:
        # P3：本体走的是**对象轴**（症状/错误码 → suspected_in → 进程），不是兜底的类轴
        ontology_graph_branch("object_axis")
        skills: list[str] = []
        sources: list[str] = []
        chain = []
        for pid in processes:
            for seg in _resolver.get_process_chain(pid):
                if seg not in chain:
                    chain.append(seg)
            for s in _resolver.get_process_skills(pid):
                if s not in skills:
                    skills.append(s)
            for src in _resolver.get_evidence_sources(pid):
                if src not in sources:
                    sources.append(src)
        _track_reasoning_path("resolve_relation", source, "object_axis",
                              nodes=list(processes) + skills, edges=["suspected_in"],
                              hops=1, terminal="object_axis")
        return {
            "source": source,
            "classes": processes,
            "skills": skills,
            "evidence_logs": {p: [] for p in processes},
            "sources": sources,
            "process_chain": chain,
        }

    if source.startswith(("class:", "dimension:")):
        ontology_graph_branch("direct_axis")   # P3：调用方直接给了规范轴，无跨切面回退
        classes = [source]
        _track_reasoning_path("resolve_relation", source, "direct_axis",
                              nodes=classes, edges=[], hops=1, terminal="direct_axis")
    else:
        ontology_graph_branch("class_fallback")  # P3：对象轴未命中 → 退回 has_class 跨切面
        classes = _traverser.get_classes_for_symptom(source)
        if not classes:  # 兜底一等公民：未归类不等于无缺口
            classes = ["dimension:unknown"]
            _terminal_axis = "unknown_fallback"
        else:
            _terminal_axis = "class_fallback"
        _track_reasoning_path("resolve_relation", source, "class_axis",
                              nodes=classes, edges=["has_class"], hops=1,
                              terminal=_terminal_axis)
    skills: list[str] = []
    evidence_logs: dict[str, list[str]] = {}
    sources: list[str] = []
    for c in classes:
        for s in _traverser.get_skills_for_class(c):
            if s not in skills:
                skills.append(s)
        logs = _traverser.get_logs_for_class(c)
        if logs:
            evidence_logs[c] = logs
        # 批 6-3：检索源方向（诊断类段「检索源」有序列表，store:xxx）
        for src in _resolver.get_evidence_sources(c):
            if src not in sources:
                sources.append(src)
    return {
        "source": source,
        "classes": classes,
        "skills": skills,
        "evidence_logs": evidence_logs,
        "sources": sources,  # 证据源顺序：先查哪个集合/维度、后查哪个（18 号方向三元组）
    }


def resolve_relation(args, **kwargs):
    _init()
    source = args.get("source_entity", "")
    rel_type = args.get("relation_type", "all")
    target_hint = args.get("target_hint")
    # 批 3-1：入口归一（「规则」→ syncrule、「同步卡住」→ incremental_stuck）；
    # O-域命名空间节点（class:/error:/symptom:/log:/tool:）是规范写法，不动
    if ":" not in source:
        source = _resolver.resolve_synonym(source)

    # O-域单跳出口：症状/错误码 → 诊断类 → Skill → 取证日志，一次拿全
    if rel_type == "diagnosis_path":
        ontology_graph_branch("rel:diagnosis_path")
        return _wrap(_resolve_diagnosis_path(source), args, "resolve_relation", ctx=kwargs)

    # 运行时对象域出口（20 号方案）：进程 → 数据流链（上下游 + 日志 + 工具类别）
    # 沿 feeds 正向遍历，结构顺序 = 链路方向；每段附频度/自证性供模型排序
    if rel_type == "process_chain":
        if not source.startswith("process:"):
            source = f"process:{source}"
        chain = _resolver.get_process_chain(source)
        ontology_graph_branch("rel:process_chain")
        return _wrap({"source": source, "process_chain": chain}, args, "resolve_relation", ctx=kwargs)

    # 边语义闭包出口（C-20261013-04 接线）：传递 / 复合 / 对称的只读闭包，每跳带依据
    # （from/edge/to/way）；复合腿另带 composition 名（如 registered_on_then_runs_on）。
    # 本出口是 edge_semantics.yaml 的 `compositions` 键在生产路径上的**唯一可见面**
    # （`transitive` 另经类继承与进程链承重）；只读、不物化（37 号 Q3）。
    if rel_type == "closure":
        ontology_graph_branch("rel:closure")
        return _wrap({"source": source, "closure": _traverser.closure(source)},
                     args, "resolve_relation", ctx=kwargs)

    # 68 号 E-1（影响面出口）：沿**本体已声明**的承载边展开，给出「受牵连单元」与见证路径。
    # 边集不新发明——取自 fault_mechanism.necessary_criteria 第 2 条点名的 5 类关系
    # （与 _STRUCTURAL_EDGES 同源）。**both** 方向：承载关系正反两向都算牵连。
    # 空结果**不静默**——impact_note 说明覆盖边界（本体当前只有 12 个节点参与这 5 类边）。
    if rel_type == "impact":
        _d = args.get("depth") or 3
        try:
            _d = max(1, min(int(_d), 3))   # 与 schema 的 depth.maximum=3 一致（walk 内部上限 5）
        except (TypeError, ValueError):
            _d = 3
        _paths = _traverser.walk(source, depth=_d, direction="both",
                                 edge_types=list(_STRUCTURAL_EDGES))
        _by_unit = {}
        for _p in _paths:
            _by_unit.setdefault(_p.get("end"), []).append(_p.get("hops"))
        # 关键话放**最前**：输出预算会截断长字段（实测「不是无影响」曾被切掉），
        # 而这句话正是本出口区别于「静默返回空」的全部价值。
        _note = "" if _paths else (
            "**返回空是覆盖边界，不是「无影响」**：该起点不在影响面边集覆盖内——"
            "本体当前只有 12 个节点参与这 5 类边（见 doc/optimize/68-*.md §1.2）。")
        try:
            from .relations import _track_impact_query
            _track_impact_query(source, bool(_paths), len(_by_unit), len(_paths), _d, "both",
                                "covered" if _paths else "out_of_scope")
        except Exception:
            pass
        ontology_graph_branch("rel:impact")
        return _wrap({"source": source, "edge_types": list(_STRUCTURAL_EDGES),
                      "by_unit": _by_unit, "impact_note": _note},
                     args, "resolve_relation", ctx=kwargs)
    if rel_type == "all":
        # 批 0-3（P-A）：按关系类型分组返回，不再扁平化为 targets——
        # 角色/语义由边类型承载（如 reads_from=源端 / writes_to=目标端），扁平化会丢边类型
        grouped = {}
        for rel, tgts in _traverser.graph.get(source, {}).items():
            # P3：这是全仓**唯一**绕过 _targets_tagged 漏斗的图直读（同一 dict 已在此遍历），
            # 故就地补一条边消费台账——不改返回内容、不改插入顺序（等价于原 dict 推导式）。
            try:
                ontology_edge(rel, "out", len(tgts), source, tgts)
            except Exception:
                pass
            grouped[rel] = list(tgts)
        if target_hint:
            grouped = {
                rel: [t for t in tgts if target_hint in t]
                for rel, tgts in grouped.items()
            }
            grouped = {rel: tgts for rel, tgts in grouped.items() if tgts}
        result = {"source": source, "by_relation": grouped}
    else:
        targets = _traverser.get_targets(source, rel_type)
        if target_hint:
            targets = [t for t in targets if target_hint in t]
        result = {"source": source, "targets": targets}
    ontology_graph_branch("rel:all" if rel_type == "all" else "rel:single")

    # 38 号批 2（37 号 §3-A：只读求值器）：depth>1 → 追加 paths 段（边语义展开，每跳带依据）。
    # 默认（depth 缺省/1）**不加任何键**——输出与既有逐字节一致（④ 基线口径）。
    depth = args.get("depth") or 1
    if isinstance(depth, int) and depth > 1 and _traverser is not None:
        direction = args.get("direction") or "out"
        edge_types = None if rel_type == "all" else [rel_type]
        paths = _traverser.walk(source, depth=depth, direction=direction,
                                edge_types=edge_types)
        result["paths"] = paths
        result["depth"] = depth
        result["direction"] = direction
        ontology_graph_branch("walk")   # P3：追加而非替换（前面的直查出口已记过）
        if edge_types and not paths and rel_type not in (
                (_traverser.edge_semantics().get("walk_policy") or {}).get("traversable") or []):
            result["paths_note"] = ("该关系类型不在可穿边集（walk_policy.traversable）内——"
                                    "depth>1 无展开；见 plugin/edge_semantics.yaml")
    return _wrap(result, args, "resolve_relation", ctx=kwargs)


# ========== Tool 9: resolve_operation ==========

def resolve_operation(args, **kwargs):
    _init()
    operation = args.get("operation", "")
    # 批 3-1：入口归一（同址别名 → capability/对象 ID）
    operation = _resolver.resolve_synonym(operation)
    cap = _resolver.lookup_operation(operation)
    if not cap:
        return _wrap({
            "error": f"未找到操作: {operation}",
            "available_operations": _resolver.list_operations(),
        }, args, "resolve_operation", ctx=kwargs)
    # 从 relations 补充 Skill 绑定（支持多 Skill）
    skill_names = _traverser.get_skills_for_action(cap.get("capability", ""))
    primary_skill = skill_names[0] if skill_names else cap.get("implements", "")
    # lookup_operation 返回的 implements 可能已带 skill: 前缀，统一确保前缀存在
    if primary_skill and not primary_skill.startswith("skill:"):
        primary_skill = f"skill:{primary_skill}"

    # 通用前置知识：BKN + Qdrant 多维度检索，默认即查向量库
    prerequisite_knowledge = synthesize_operation_knowledge(
        capability=cap.get("capability", ""),
        operation_name=cap.get("name", operation),
        bkn_caps=cap,
        top_k=3,
    )
    skill_hint = f"如需获取具体命令和脚本，可加载 {primary_skill.replace('skill:', '')}" if primary_skill else ""

    # 图边单源：constraints 来自 action_routing.bkn constrained_by 边 + constraints.bkn 表 join
    from .risk_guard import get_risk_rules
    _rg_rules = get_risk_rules()
    _op_constraints = [rid for rid, r in _rg_rules.items() if r.get("action") == cap.get("capability")]
    _constraints_source = next(iter(_rg_rules.values())).get("source", "fallback") if _rg_rules else "fallback"

    result = {
        "operation": cap.get("name", operation),
        "capability": cap.get("capability", ""),
        "implements": primary_skill if primary_skill else cap.get("implements", ""),
        "implements_skills": [
            {"name": name, "role": "primary" if idx == 0 else "auxiliary"}
            for idx, name in enumerate(skill_names)
        ],
        "params": cap.get("params", ""),
        "constraints": cap.get("constraints", ""),
        "notes": cap.get("notes", ""),
        "prerequisites": cap.get("prerequisites", ""),
        "risks": cap.get("risks", ""),
        "prerequisite_knowledge": prerequisite_knowledge,
        "skill_hint": skill_hint,
        "hint": skill_hint,  # 保留兼容
        "constraints_source": _constraints_source,
        "constraint_ids": _op_constraints,
    }
    return _wrap(result, args, "resolve_operation", ctx=kwargs)


# ========== Tool 10: search_qdrant ==========

def search_qdrant_handler(args, **kwargs):
    """Hermes 原生 Qdrant 搜索工具 — 维度感知 + 覆盖度追踪

    两种模式:
      单查询: 传 query (字符串), 可选 dimension
      批量:   传 queries (数组) [{\"query\":..., \"dimension\":..., \"top_k\"?}, ...]
              内部 ThreadPoolExecutor 并行, 结果按原序返回
    特殊: dimension='__report__' → 仅返回覆盖度报告

    注意: 所有返回值必须经 json.dumps() 序列化为字符串,
    否则 dict 直接放入 tool message.content 会导致 DeepSeek API
    拒绝 (HTTP 400: "content should be a string or a list")。
    """
    # ── 批量模式: queries 参数存在 → 线程池并行 ──
    queries_spec = args.get("queries")
    if queries_spec and isinstance(queries_spec, list) and len(queries_spec) > 0:
        raw = json.loads(_search_qdrant_batch_inner(
            queries_spec, task_id=kwargs.get("task_id"),
            session_id=kwargs.get("session_id"),   # 批 U-0：会话标识随批次下传
            collection=args.get("collection"),     # 21 号 2E：批次级集合下传
            # 44 号 §6 批 3：call_detail 也要 args——本函数作用域内**没有** args（只有
            # normalized 后的 queries_spec），故由 handler 原样透传
            args=args))
        final = json.dumps(_apply_output_budget(raw, "search_qdrant"), ensure_ascii=False)
        # 批 4-2：统一埋点（置信度 + usage + 轨迹）；逐条 usage 记录仍由 batch_inner 负责
        _log_exempt_call("search_qdrant", args, kwargs, raw, final,
                         {"mode": "parallel_batch", "queries": raw.get("query_count", 0)})
        return final

    query = args.get("query", "")
    top_k = args.get("top_k", 5)
    try:
        top_k = int(top_k)
        if top_k < 1:
            top_k = 5
        elif top_k > 20:
            top_k = 20
    except (TypeError, ValueError):
        top_k = 5
    collection = args.get("collection")
    dimension = args.get("dimension")
    tool_name = args.get("tool_name")  # 用于确定维度集, 默认 design_solution
    chunk_mode = args.get("chunk_mode", SEARCH_CHUNK_MODE)
    task_id = kwargs.get("task_id")  # 维度覆盖按 task_id 分桶

    # ── 仅返回覆盖度报告 ──
    if dimension == "__report__":
        result = _filter_command_fields({
            "coverage": get_dimension_coverage(tool_name, task_id=task_id),
            "mode": "report_only",
            "hint": "用 dimension 参数标注每次搜索的目标维度以累积覆盖度",
        })
        final = json.dumps(result, ensure_ascii=False)
        # 批 4-2：早期返回路径此前完全无埋点，本次一并接入
        _log_exempt_call("search_qdrant", args, kwargs, result, final,
                         {"mode": "report_only", "dimension": "__report__"})
        return final

    # ── 重置当前任务覆盖度 ──
    if dimension == "__reset__":
        reset_dimension_coverage(task_id)
        result = _filter_command_fields({
            "mode": "reset",
            "hint": "当前任务的维度覆盖记录已清空，可开始新一轮逐维度搜索",
        })
        final = json.dumps(result, ensure_ascii=False)
        _log_exempt_call("search_qdrant", args, kwargs, result, final,
                         {"mode": "reset", "dimension": "__reset__"})
        return final

    if not query or not query.strip():
        result = _filter_command_fields({
            "error": "query 参数不能为空 (或使用 queries 参数进行批量搜索)",
            "hint": '单查询: {\"query\": \"...\"} 或批量: {\"queries\": [{\"query\":\"...\",\"dimension\":\"...\"}, ...]}',
        })
        final = json.dumps(result, ensure_ascii=False)
        _log_exempt_call("search_qdrant", args, kwargs, result, final,
                         {"mode": "single", "query": "", "hits": 0})
        return final

    result = {}
    try:
        # ── 路径1: 自定义 collection — v1.7 起支持 BM25 + chunk_mode（按设计稿分块结构） ──
        if collection:
            from .config import SEARCH_SCORE_THRESHOLD
            from .supplement import _get_qdrant_client, _get_embedding_model

            client = _get_qdrant_client()
            model = _get_embedding_model()

            if client is None:
                result = _filter_command_fields({
                    "error": "Qdrant 不可用, 无法搜索自定义 collection",
                    "query": query, "collection": collection,
                })
                return json.dumps(result, ensure_ascii=False)

            if model is None:
                result = _filter_command_fields({
                    "error": "Embedding 模型不可用, 无法搜索自定义 collection",
                    "query": query, "collection": collection,
                    "hint": "不使用 collection 参数时会走默认集合的混合搜索",
                })
                return json.dumps(result, ensure_ascii=False)

            # chunk_mode 路由（与默认路径一致的策略）
            if chunk_mode == "mini_first":
                raw_hits = _search_mini_first(query, top_k=top_k, collection=collection)
            elif chunk_mode == "standard_image":
                raw_hits = _search_chunk_level(query, top_k, ["standard", "image"], collection=collection)
            elif chunk_mode == "large_only":
                raw_hits = _search_chunk_level(query, top_k, ["large"], collection=collection)
            elif chunk_mode == "parent_expand":
                raw_hits = None  # parent_expand 走下方通用 BGE+BM25 后 _expand_parents
            else:  # auto
                raw_hits = None

            if raw_hits is None:
                # auto / parent_expand: BGE dense + BM25 RRF（特征提取优先）
                emb = model.encode(query).tolist()
                res = client.query_points(
                    collection_name=collection,
                    query=emb,
                    limit=top_k,
                    score_threshold=SEARCH_SCORE_THRESHOLD,
                )
                raw_hits = []
                for r in res.points:
                    content = _payload_content(r.payload or {})
                    if not _is_valid_content(content):
                        continue
                    hit = {
                        "content": content,
                        "score": round(r.score, 4) if hasattr(r, "score") and r.score else 0.0,
                        "source": (r.payload or {}).get("document_id", ""),
                    }
                    # 模式库 payload 字段透传（log_patterns_collection）
                    from .bm25 import PATTERN_META_KEYS
                    for f in PATTERN_META_KEYS:
                        v = (r.payload or {}).get(f)
                        if v is not None:
                            hit[f] = v
                    raw_hits.append(hit)

                # BM25 主通道：特征提取优先（错误码/精确项先 targeted BM25）
                try:
                    from .bm25 import bm25_search, rrf_fusion
                    from .supplement import _extract_exact_terms
                    exact_terms = _extract_exact_terms(query)
                    sparse_hits = []
                    seen_ids = set()
                    if exact_terms:
                        for h in bm25_search(" ".join(exact_terms), top_k=top_k, collection=collection):
                            sparse_hits.append(h)
                            seen_ids.add(h.get("id"))
                    for h in bm25_search(query, top_k=top_k * 2, collection=collection):
                        if h.get("id") not in seen_ids:
                            sparse_hits.append(h)
                            seen_ids.add(h.get("id"))
                    if sparse_hits:
                        merged = rrf_fusion(raw_hits, sparse_hits, top_k=top_k * 2)
                        # 21 号 2F：检索标记不再拼进 source（source 保持纯 document_id），
                        # 来源改由输出层 retrieval_path 表达
                        # severity 排序：RRF 分数相同时 critical 优先（日志模式库）
                        _sev_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
                        merged.sort(key=lambda x: (
                            -(x.get("rrf_score") or 0),
                            _sev_rank.get((x.get("severity") or "").lower(), 9),
                        ))
                        for h in merged:
                            h["retrieval_path"] = ["dense", "bm25"]
                        raw_hits = merged[:top_k]
                except ImportError:
                    pass

                if chunk_mode == "parent_expand":
                    raw_hits = _expand_parents(raw_hits, collection=collection)
        else:
            # ── 路径2: 默认集合 — 按 chunk_mode 路由 ──
            if chunk_mode == "mini_first":
                raw_hits = _search_mini_first(query, top_k=top_k)
            elif chunk_mode == "parent_expand":
                raw_hits = search_qdrant(query, top_k=top_k, hybrid=True)
                raw_hits = _expand_parents(raw_hits)
            elif chunk_mode == "standard_image":
                raw_hits = _search_chunk_level(query, top_k, ["standard", "image"])
            elif chunk_mode == "large_only":
                raw_hits = _search_chunk_level(query, top_k, ["large"])
            else:  # "auto" 或未知值：旧行为，全量 BGE+BM25→RRF
                raw_hits = search_qdrant(query, top_k=top_k, hybrid=True)

        # ── 维度追踪 ──
        if dimension:
            _track_dimension(dimension, len(raw_hits), task_id=task_id)
        coverage = get_dimension_coverage(tool_name, task_id=task_id)

        # 截断 content 到 500 字符, 添加维度标签与 chunk_mode 特有字段
        hits = []
        for h in raw_hits:
            h_out = {
                "content": h.get("content", "")[:500],
                "score": h.get("score", 0),
                "source": h.get("source", ""),
            }
            # chunk_mode 特有字段透传
            if "chunk_id" in h:
                h_out["chunk_id"] = h["chunk_id"]
            if "chunk_level" in h:
                h_out["chunk_level"] = h["chunk_level"]
            if "section_type" in h:
                h_out["section_type"] = h["section_type"]
            if "image_file_id" in h:
                h_out["image_file_id"] = h["image_file_id"]
            if "large_chunk_id" in h:
                h_out["large_chunk_id"] = h["large_chunk_id"]
            if "title" in h:
                h_out["title"] = h["title"]
            if "blurb" in h:
                h_out["blurb"] = h["blurb"]
            if "mini_chunk_count" in h:
                h_out["mini_chunk_count"] = h["mini_chunk_count"]
            if "hit_mini" in h:
                h_out["hit_mini"] = [
                    {**m, "text": (m.get("text") or "")[:500]}
                    for m in h["hit_mini"]
                ]
            if "_parent" in h:
                h_out["_parent"] = h["_parent"]
            # 21 号 2F: 检索来源路径（替代此前拼进 source 的 [RRF]/[PG] 标记）
            if h.get("retrieval_path"):
                h_out["retrieval_path"] = h["retrieval_path"]
            # 日志模式库 payload 字段透传（v1.7，log_patterns_collection）
            from .bm25 import PATTERN_META_KEYS
            for _f in PATTERN_META_KEYS:
                if _f in h:
                    h_out[_f] = h[_f]
            if dimension:
                h_out["_dim"] = dimension
            if h.get("_fallback_reason"):
                h_out["_fallback_reason"] = h["_fallback_reason"]
            hits.append(h_out)

        # 收集初始化/降级警告, 让上层知道结果是否可靠
        from .supplement import get_search_warnings
        from .bm25 import get_bm25_warnings
        warnings = get_search_warnings() + get_bm25_warnings()

        # ── 无命中 ──
        if not hits:
            result = {
                "hits": [],
                "count": 0,
                "query": query,
                "dimension": dimension,
                "coverage": coverage,
                "chunk_mode": chunk_mode,
                "note": "未找到相关结果，尝试更换查询词",
            }
        else:
            result = {
                "hits": hits,
                "count": len(hits),
                "query": query,
                "dimension": dimension,
                "coverage": coverage,
                "chunk_mode": chunk_mode,
            }
        if warnings:
            result["_warning"] = "; ".join(warnings)

        # v1.5 (P3-1): 使用统计——chunk_mode 分布为块感知策略调优供数据
        # （2A: 统一挪到最终返回处记录，覆盖成功与异常两条路径）

    except Exception as e:
        result = _filter_command_fields({
            "error": f"Qdrant 搜索失败: {str(e)}",
            "query": query,
            "dimension": dimension,
            "collection": collection,
        })

    result = _filter_command_fields(result)
    final = json.dumps(_apply_output_budget(result, "search_qdrant"), ensure_ascii=False)
    _log_exempt_call("search_qdrant", args, kwargs, result, final,
                     {"chunk_mode": chunk_mode, "top_k": top_k,
                      "hits": result.get("count", 0), "mode": "single",
                      "query": (query or "")[:120]})  # 21 号 P2 零命中治理需要「什么查询」
    return final


# ========== 批量搜索内部函数 (由 search_qdrant_handler 在 queries 参数存在时调用) ==========

MAX_BATCH_QUERIES = 10  # 批量 queries 上限, 超出截断防线程爆炸


def _search_qdrant_batch_inner(queries_spec, task_id=None, session_id=None,
                                collection=None, args=None):
    """search_qdrant 批量模式 — 线程池并行搜索多维度

    queries_spec: [{"query": ..., "dimension": ..., "top_k"?: 5, "collection"?: ..., "chunk_mode"?: ...}, ...]
    复用 supplement.search_qdrant() 的 client/model 懒加载。
    超过 MAX_BATCH_QUERIES 的部分截断并在结果中标记 truncated。

    21 号 2E：`collection` 为批次默认集合，单项可用自身 `collection` 覆盖——
    此前批量模式完全丢弃 collection（规范化不读该键、路由不传），
    传了 collection 的用户会静默拿到主集合结果。

    44 号 §6 批 3：`args` 为**工具调用原始入参**（handler 透传，供 call_detail 记录补
    args 字段）。缺省 None = 直接调用方没传 → 不写该键（缺记如实反映在完整率里，
    不用空值冒充「有值」）。
    """
    import concurrent.futures
    from .supplement import get_dimension_coverage as _get_cov, get_search_warnings as _get_warn
    from .bm25 import get_bm25_warnings as _get_bm25_w

    # 规范化参数
    normalized = []
    for i, q in enumerate(queries_spec):
        if not isinstance(q, dict) or "query" not in q:
            continue
        top_k = int(q.get("top_k", 5))
        normalized.append({
            "idx": i,
            "query": q["query"],
            "dimension": q.get("dimension"),
            "chunk_mode": q.get("chunk_mode", SEARCH_CHUNK_MODE),
            "top_k": max(1, min(top_k, 20)),
            # 21 号 2E：单项 collection 覆盖批次默认（空值回落默认集合语义）
            "collection": q.get("collection") or collection,
        })

    truncated = len(normalized) > MAX_BATCH_QUERIES
    if truncated:
        normalized = normalized[:MAX_BATCH_QUERIES]

    if not normalized:
        result = _filter_command_fields({
            "error": "queries 数组中每项须包含 query 字段",
        })
        return json.dumps(result, ensure_ascii=False)

    def _run_one(nq):
        """线程池工作函数 — 按 chunk_mode 路由（21 号 2E：各路由透传 nq['collection']）"""
        try:
            mode = nq.get("chunk_mode", SEARCH_CHUNK_MODE)
            coll = nq.get("collection")
            if mode == "mini_first":
                raw = _search_mini_first(nq["query"], top_k=nq["top_k"], collection=coll)
            elif mode == "parent_expand":
                raw = search_qdrant(nq["query"], top_k=nq["top_k"], hybrid=True, collection=coll)
                raw = _expand_parents(raw, collection=coll)
            elif mode == "standard_image":
                raw = _search_chunk_level(nq["query"], nq["top_k"], ["standard", "image"],
                                          collection=coll)
            elif mode == "large_only":
                raw = _search_chunk_level(nq["query"], nq["top_k"], ["large"], collection=coll)
            else:  # "auto"
                raw = search_qdrant(nq["query"], top_k=nq["top_k"], hybrid=True, collection=coll)
            if nq["dimension"]:
                _track_dimension(nq["dimension"], len(raw), task_id=task_id)
            hits = []
            for h in raw:
                hit = {
                    "content": h.get("content", "")[:500],
                    "score": h.get("score", 0),
                    "source": h.get("source", ""),
                }
                # chunk_mode 特有字段透传
                if "chunk_id" in h:
                    hit["chunk_id"] = h["chunk_id"]
                if "chunk_level" in h:
                    hit["chunk_level"] = h["chunk_level"]
                if "section_type" in h:
                    hit["section_type"] = h["section_type"]
                if "image_file_id" in h:
                    hit["image_file_id"] = h["image_file_id"]
                if "large_chunk_id" in h:
                    hit["large_chunk_id"] = h["large_chunk_id"]
                if "title" in h:
                    hit["title"] = h["title"]
                if "blurb" in h:
                    hit["blurb"] = h["blurb"]
                if "mini_chunk_count" in h:
                    hit["mini_chunk_count"] = h["mini_chunk_count"]
                if "hit_mini" in h:
                    hit["hit_mini"] = [
                        {**m, "text": (m.get("text") or "")[:500]}
                        for m in h["hit_mini"]
                    ]
                if "_parent" in h:
                    hit["_parent"] = h["_parent"]
                if h.get("retrieval_path"):  # 21 号 2F: 检索来源路径
                    hit["retrieval_path"] = h["retrieval_path"]
                if nq["dimension"]:
                    hit["_dim"] = nq["dimension"]
                if h.get("_fallback_reason"):
                    hit["_fallback_reason"] = h["_fallback_reason"]
                hits.append(hit)
            return {"idx": nq["idx"], "query": nq["query"], "dimension": nq["dimension"],
                    "chunk_mode": mode, "hits": hits, "count": len(hits), "error": None}
        except Exception as e:
            return {"idx": nq["idx"], "query": nq["query"], "dimension": nq["dimension"],
                    "chunk_mode": nq.get("chunk_mode", SEARCH_CHUNK_MODE),
                    "hits": [], "count": 0, "error": str(e)}

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(normalized), MAX_BATCH_QUERIES)) as pool:
        futures = {pool.submit(_run_one, nq): nq["idx"] for nq in normalized}
        batch_results = []
        for fut in concurrent.futures.as_completed(futures):
            batch_results.append(fut.result())

    # 按原始 idx 排序恢复顺序
    batch_results.sort(key=lambda r: r["idx"])

    total_hits = sum(r["count"] for r in batch_results)
    warnings = _get_warn() + _get_bm25_w()

    result = {
        "results": batch_results,
        "total_hits": total_hits,
        "query_count": len(normalized),
        "coverage": _get_cov("search_qdrant", task_id=task_id),
        "mode": "parallel_batch",
        "hint": "results 数组按 queries 原始顺序排列，每项的 _dim 字段标注了维度",
    }
    if truncated:
        result["truncated"] = True
        result["note"] = f"queries 超过 {MAX_BATCH_QUERIES} 项，已截断"
    if warnings:
        result["_warning"] = "; ".join(warnings)

    # v1.5 (P3-1): 批量模式逐条记录 chunk_mode；2A: 补一条聚合耗时/体积记录（无 chunk_mode 键）
    # 44 号 §6 批 3：这两处是**查询明细级**记录（不是工具调用级）——标 call_detail：
    # 它们天性没有 confidence（本来就不该有），混进 call 组算完整率正是 47% 假象的成因。
    # args 只在 handler 透传时写（args=None 不吃空值）。
    from .usage_log import log_usage
    _args_fields = {"args": _log_args(args)} if args is not None else {}
    for r in batch_results:
        log_usage("search_qdrant", record_type="call_detail", **_args_fields,
                  chunk_mode=r.get("chunk_mode"),
                  hits=r.get("count", 0), mode="batch",
                  query=(r.get("query") or "")[:120],
                  **_session_ctx({"task_id": task_id, "session_id": session_id}))

    result = _filter_command_fields(result)
    final = json.dumps(result, ensure_ascii=False)
    log_usage("search_qdrant", record_type="call_detail", mode="batch",
              queries=len(batch_results), **_args_fields,
              **_session_ctx({"task_id": task_id, "session_id": session_id}),
              **_usage_metrics(final))
    return final


# ========== Tool 11: diagnose_db_link ==========

_SUPPORTED_DBS = None  # v3.8: 不再硬限制 DB 类型，接受用户传入的任意 DB


def _resolve_db_type(error_code: Optional[str], fallback: Optional[str] = None) -> Optional[str]:
    """根据错误码前缀推断数据库类型（前缀最长优先）。

    无前缀命中时返回 fallback（默认 None = unknown），不再默认按 Oracle 处理。
    """
    if not error_code:
        return fallback
    code_upper = error_code.upper()
    for prefix in sorted(DB_ERROR_PREFIXES, key=len, reverse=True):
        if code_upper.startswith(prefix.upper()):
            return DB_ERROR_PREFIXES[prefix]
    return fallback


def _extract_bkn_context(error_code: Optional[str], message: str = "",
                         log_source: str = "") -> Optional[dict]:
    """错误码诊断指引上下文（25 号：由「常量 + 边」组装，锚点表已删）。

    21 号：错误码完整 6 属性（风险级别/触发条件/处置策略/禁止）**已入库**；
    25 号：BKN 不再登记错误码清单——规范 ID 空间由 `suspected_in` 边承载，
    别名在 `plugin/constants.py::ERROR_ALIASES`（值数据层），检索指引为常量规则。
    返回字段（与 21 号对齐，消费者无需改）：`error_code` / `retrieval_guide` /
    `suspected_process`（来自边）/ `aliases` / `dimensions` / `unknown_rule`。
    """
    if not error_code:
        return None
    risk = _resolver.get_risk(error_code, message=message, log_source=log_source)
    if not risk:
        return None
    context = {"error_code": risk.get("error_code") or error_code}
    # 32 号新增键（含义链）：meaning / diagnosed_skills / observed_logs / needs——
    # 旧键保留（消费者无需改）；新键让"依据可溯、缺什么也明说"。
    for key in ("meaning", "dimensions", "diagnosed_skills", "observed_logs",
                "suspected_process", "retrieval_guide", "aliases", "unknown_rule", "needs"):
        val = risk.get(key)
        if val:
            context[key] = val
    return context if len(context) > 1 else None


def diagnose_db_link_handler(args, **kwargs):
    """根据症状+DB类型推荐诊断 Skill 并返回 BKN 风险上下文。

    Tool 只负责：识别 DB 类型、组装错误码诊断指引（边 + 常量）、推荐一组必需/可选 Skill。
    当 BKN 风险上下文不足时，会调用 Qdrant 补充相关背景片段。
    具体 action 路由和命令构建由 Skill 自己完成。
    返回统一 schema 的 JSON 字符串。
    """
    _init()
    symptom = args.get("symptom", "")
    raw_db_type = (args.get("db_type") or "auto").strip()
    error_code = args.get("error_code")
    process = (args.get("process") or "").strip()  # 20 号方案：进程入口（进程挂死常无错误码）

    if raw_db_type == "auto":
        db_type = _resolve_db_type(error_code)
        db_type_source = "error_code_prefix" if db_type else "unknown"
    else:
        db_type = raw_db_type
        db_type_source = "explicit"

    if not db_type:
        db_type = "unknown"

    bkn_context = _extract_bkn_context(error_code, message=str(args.get("message") or ""),
                                       log_source=str(args.get("log_source") or ""))
    display_symptom = error_code if error_code else symptom

    # 20 号方案：进程入口推导链——按进程定位故障（弥补「进程挂死常无错误码」空档）
    process_path = None
    if process:
        pid = process if process.startswith("process:") else f"process:{process}"
        chain = _resolver.get_process_chain(pid)
        if chain:
            # 频度排序（高→中→低），供模型决定先看谁；结构顺序保留在 chain 内
            freq_order = {"高": 0, "中": 1, "低": 2, "": 3}
            ordered = sorted(chain, key=lambda x: freq_order.get(x.get("frequency", ""), 3))
            process_path = {
                "entry": pid,
                "chain": chain,           # 结构顺序（feeds，理解因果）
                "suggested_order": ordered,  # 排查顺序（频度，先看高频）
            }

    skill_map = _resolver.get_symptom_skills(display_symptom)
    required = skill_map.get("required", [])
    optional = skill_map.get("optional", [])

    # 32 号：含义链推出来的 Skill 并入推荐（`dimension --diagnosed_by--> skill`）——
    # 去重且保持顺序（原 required 在前，含义链新增的在后）；这是"含义 → 找谁"在 Tool 层的落点。
    _have = {s["name"] for s in required} | {s["name"] for s in optional}
    for _sk in (bkn_context or {}).get("diagnosed_skills") or []:
        _name = str(_sk).split(":")[-1]
        if _name and _name not in _have:
            required.append({"name": _name,
                             "reason": "含义链：该维度由本 Skill 诊断（dimension --diagnosed_by--> skill）"})
            _have.add(_name)

    recommended_skills = [
        {"name": s["name"], "role": "required", "reason": s.get("reason", "")}
        for s in required
    ] + [
        {"name": s["name"], "role": "optional", "reason": s.get("reason", "")}
        for s in optional
    ]
    recommended_skill = required[0]["name"] if required else "demo_product-db-diagnostics"

    # 通用知识合成：Phase 1 读 BKN + Phase 2 查 Qdrant
    # 25 号接线：嫌疑进程的检索源（store:）→ 内部检索打对集合
    _ev_procs = _resolver.get_processes_for_symptom(display_symptom)
    _ev_sources = _resolver.get_evidence_sources(_ev_procs[0]) if _ev_procs else None
    knowledge = synthesize_diagnosis_knowledge(
        symptom=symptom or display_symptom,
        db_type=db_type,
        error_code=error_code,
        bkn_context=bkn_context,
        skill_map=skill_map,
        top_k=3,
        sources=_ev_sources,
    )

    # 扩展为带使用场景的 related_skills（Skill 索引，不诱导加载）
    # 23 号方案：默认 Skill 导航下延 Skill 层（manifest），本体侧不再持有导航段
    related_skills = _manifest_related_skills()
    when_to_load = "需要具体诊断工具名和命令参数时"

    # 摘要式 note，直接可用，不再是指令式「建议加载 Skill」
    note = knowledge.get("summary", "")
    if not note:
        note = f"整理了 {db_type} {symptom or display_symptom} 的排查知识，详情见 knowledge.dimensions。"

    # knowledge_snippets 改为轻量引用索引，避免与 dimensions/knowledge_context 重复完整内容
    knowledge_snippets = []
    for dim in knowledge.get("dimensions", []):
        for idx, snippet in enumerate(dim.get("snippets", [])):
            knowledge_snippets.append({
                "dimension": dim.get("name", ""),
                "index": idx,
                "preview": snippet.get("content", "")[:120],
                "score": snippet.get("score", 0),
                "source": snippet.get("source", ""),
            })

    # 知识上下文：可直接消费的知识（BKN + Qdrant，保留完整 snippets）
    knowledge_context = {
        "analysis_framework": skill_map.get("analysis_framework", ""),
        "skill_capabilities": skill_map.get("skill_capabilities", ""),
        "summary": knowledge.get("summary", ""),
        "common_causes": [],
        "recommended_steps": [],
        "configuration_checks": [],
        "logs_and_tools": [],
    }
    if bkn_context:
        knowledge_context["bkn_risk_context"] = bkn_context
    _DIM_TO_KC_KEY = {
        "常见原因": "common_causes",
        "排查步骤": "recommended_steps",
        "配置检查": "configuration_checks",
        "日志与工具": "logs_and_tools",
    }
    for dim in knowledge.get("dimensions", []):
        kc_key = _DIM_TO_KC_KEY.get(dim.get("name"))
        if kc_key:
            knowledge_context[kc_key] = dim.get("snippets", [])

    # knowledge.dimensions 降为轻量引用索引（同 knowledge_snippets 的处理）：
    # 完整 snippets 已保留在 knowledge_context 各维度字段中，此处不再重复全文。
    # 注意：上面 knowledge_context 直接引用了同一批 snippet 对象，所以这里必须
    # 「重新赋值」而非原地修改——重绑定 dim["snippets"] 会指向新对象，
    # knowledge_context 仍持有原列表，不会被连带降级。
    for dim in knowledge.get("dimensions", []):
        dim["snippets"] = [
            {
                "index": idx,
                "preview": s.get("content", "")[:120],
                "score": s.get("score", 0),
                "source": s.get("source", ""),
            }
            for idx, s in enumerate(dim.get("snippets", []))
        ]

    # 技能上下文：深入执行时需要加载 Skill 的索引
    skill_context = {
        "primary_skill": recommended_skill,
        "when_to_load": when_to_load,
        "related_skills": related_skills,
        "recommended_skills": recommended_skills,
    }

    # 导航层单源接线（log-map.bkn）：症状 → 该看哪些日志、按什么顺序。
    # 未命中症状省略字段（不报错不空转）；level_tuning/pattern_library 为全局静态。
    log_navigation = _resolver.get_log_map(symptom or display_symptom)

    # 引导 LLM 消费 + v3.7 维度搜索指引
    symptom_str = symptom or display_symptom
    dim_hints = _build_dimension_hints("diagnose_db_link", {
        "source": db_type, "target": "", "symptom": symptom_str,
    })
    critical_dims = [d for d in _get_known_dimensions("diagnose_db_link")
                     if _get_dimension_priority(symptom_str, d) == "critical"]
    _model_hint = (
        "CRITICAL_READ: 顶层 must_know 汇总了关键参数、错误码、路径与开关值；"
        "knowledge_context 保留了完整可读的排查知识（common_causes / recommended_steps / "
        "configuration_checks / logs_and_tools）。请完整阅读 configuration_checks 中的配置项，"
        "并逐条列出 common_causes 与 logs_and_tools，不要合并为一句话概括。"
        "DIMENSION_SEARCH: _available_dimensions 按优先级标注了 critical/suggested/optional，"
        "你必须至少搜索所有 critical 维度（共{0}个: {1}），"
        "建议继续搜索 suggested 维度以获得完整排查覆盖。".format(
            len(critical_dims), ", ".join(critical_dims)
        )
    )

    # v3.8: skill 加载强制机制，与 _model_hint / _divergence_prompt 同级
    required_names = [s["name"] for s in required]
    _skill_enforcement = {
        "level": "CRITICAL",
        "skills_required": required_names,
        "reason": (
            "诊断类 Tool 返回的是知识框架（原因/步骤/配置），不包含可执行命令和工具路径。"
            "Skill 才持有具体命令模板、工具参数、执行环境要求。"
            "缺少 Skill 的排查方案无法落地执行。"
        ),
        "guard": (
            "禁止在 required skill 未全部加载前输出最终排查方案。"
            "先 skill_view 加载全部 required skill，再结合 Qdrant 搜索结果输出完整方案。"
        ),
    }
    result = {
        "_model_hint": _model_hint,
        "_skill_enforcement": _skill_enforcement,
        "symptom": display_symptom,
        "db_type": db_type,
        "db_type_source": db_type_source,
        "error_code": error_code,
        "knowledge": knowledge,
        "knowledge_context": knowledge_context,
        "skill_context": skill_context,
        "related_skills": related_skills,
        "recommended_skill": recommended_skill,
        "recommended_skills": recommended_skills,
        "note": note,
        "bkn_context": bkn_context,
        "knowledge_snippets": knowledge_snippets,
    }
    if process_path:
        result["process_path"] = process_path
    if log_navigation:
        result["log_navigation"] = log_navigation
    # v3.7: Agent 自主维度选择 — 按症状优先级排序+标注
    available_dims = []
    for dim_name in _get_known_dimensions("diagnose_db_link"):
        priority = _get_dimension_priority(symptom_str, dim_name)
        available_dims.append({
            "name": dim_name,
            "priority": priority,
            "hint": dim_hints.get(dim_name, f"{dim_name} 相关配置参数和命令"),
        })
    available_dims.sort(key=lambda d: {"critical": 0, "suggested": 1, "optional": 2}.get(d["priority"], 3))
    result["_search_deferred"] = True
    result["_severity"] = "suggested"
    result["_available_dimensions"] = available_dims
    result["_divergence_prompt"] = (
        "以上 10 个维度是 Plugin 预设框架，不是全集。"
        "请你在搜索完 critical 维度后，基于领域经验自问："
        "\"是否存在框架外但与本症状相关的排查方向？\""
        "（例如「规则配置/装载策略」曾不在旧版框架中，但它正是本次数据丢失的关键维度。）"
        "若想到任何框架外的方向，自行构造 query 调用 search_qdrant，dimension 用该方向名称即可。"
        "发散是你的职责，不是 Plugin 的。"
    )
    # 安全网：过滤可能残留的命令字段（handler 绕过 _wrap，需独立应用）
    result = _filter_command_fields(result)
    final = json.dumps(_apply_output_budget(result, "diagnose_db_link"), ensure_ascii=False)
    # P1：答案来源判定（同 diagnose_error）——本 Tool 的 BKN 风险上下文也是两跳拼装出来的
    try:
        _risk_for_src = _extract_bkn_context(args.get("error_code"), message="",
                                             log_source=args.get("process") or "")
    except Exception:
        _risk_for_src = None
    _record_answer_source("diagnose_db_link", args, _risk_for_src)
    # 2A: 补埋点（此前完全不进 usage_log 的盲区 Tool）；批 4-2：统一走 _log_exempt_call（补置信度/gap/轨迹）
    _log_exempt_call("diagnose_db_link", args, kwargs, result, final,
                     {"db_type": (args.get("db_type") or ""), "symptom": (args.get("symptom") or "")})
    return final


# ========== Tool 12: check_action_risk ==========

def check_action_risk_handler(args, **kwargs):
    """RiskGuard 自查 Tool — 执行动作前检查是否违反 L0 状态前置约束。

    供 Agent 在执行危险操作前主动调用确认；同时 pre_tool_call hook
    会在受控动作执行时自动执行同一逻辑（灰度期只记录不阻断）。
    """
    from .risk_guard import check_action_risk, get_risk_rules

    action = args.get("action", "")
    state = args.get("current_state", "")

    if not action:
        result = _filter_command_fields({
            "error": "action 参数不能为空",
            "available_rules": {
                rid: {"action": r["action"], "forbidden_states": sorted(r["forbidden_states"]),
                      "severity": r["severity"]}
                for rid, r in get_risk_rules().items()
            },
        })
        # 2A: 补埋点（参数缺失的错误路径也记录）；批 4-2：统一埋点（补置信度/gap/轨迹）
        _final = json.dumps(result, ensure_ascii=False)
        _log_exempt_call("check_action_risk", args, kwargs, result, _final,
                         {"action": "", "passed": None})
        return _final

    check = check_action_risk(action, state)
    result = _filter_command_fields({
        "passed": check["passed"],
        "action": check["action"],
        "state": check["state"],
        "rule_id": check.get("rule_id"),
        "block_reason": check.get("block_reason"),
        "severity": check.get("severity"),
        "error_code": check.get("error_code"),
        "risk_type": check.get("risk_type"),
        "source": check.get("source"),
        "blockable": check.get("blockable"),
    })
    # 2A: 补埋点（此前完全不进 usage_log 的盲区 Tool）；批 4-2：统一埋点（补置信度/gap/轨迹）
    final = json.dumps(_apply_output_budget(result, "check_action_risk"), ensure_ascii=False)
    _log_exempt_call("check_action_risk", args, kwargs, result, final,
                     {"action": action, "passed": check.get("passed")})
    return final


# ========== Tool 13: diagnose_mechanism（54 号 · 裁 2＝C：M-4 输出契约）==========

_MECH_CACHE = None


def _mechanisms() -> dict:
    """读 plugin/mechanisms.yaml（惰性 import yaml，36 号教训；失败退化为 {}）。"""
    global _MECH_CACHE
    if _MECH_CACHE is None:
        try:
            import yaml
            from pathlib import Path
            # 注意 BKN_ROOT 指向**本体目录**（plugin/bkn），不是仓库根 ⇒ 用本文件所在目录
            p = Path(__file__).resolve().parent / "mechanisms.yaml"
            _MECH_CACHE = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception:
            _MECH_CACHE = {}
    return _MECH_CACHE


def _norm_entry(entry: str) -> tuple:
    """入口归一 → (kind, node, note)。与既有 handler 同序：先同址别名、再格式归一。"""
    e = (entry or "").strip()
    if e.startswith("process:"):
        return "process", e, "运行时对象域入口"
    if ":" in e:
        return "node", e, "命名空间节点（symptom: / error: / class: / dimension:）"
    syn = _resolver.resolve_synonym(e)
    norm = _resolver.normalize_error_code(syn)
    if re.fullmatch(r"-?[0-9]{3,}", str(norm)):
        return "code", norm, "错误码入口（Q27：只给码**不带消息文本**时含义未定）"
    node = syn if ":" in str(syn) else "symptom:" + str(syn)
    return "symptom", node, "症状入口（同址别名归一后）"


def _leaf_mechanisms() -> list:
    """**非根类**机制（＝可独立出证的候选池）。

    mechanisms.yaml 的 entry_fields 写明根类「**不独立出证**——它的 confirmed 必须由某个子类的
    hard 证据支撑」。故根类不进候选池：否则它每次都以一个永远 unknown 的候选出现，与自身声明矛盾
    （C-20261013-15）。
    """
    return [m for m in (_mechanisms().get("mechanisms") or [])
            if m.get("id") and m.get("kind") != "根类"]


def _mech_roots() -> list:
    """根类机制 id（不作出证，仅用于在输出里说明它们为何缺席）。"""
    return [m["id"] for m in (_mechanisms().get("mechanisms") or [])
            if m.get("id") and m.get("kind") == "根类"]


def _mech_candidates(targets: list) -> tuple:
    """候选机制召回：指向 targets 里任一端点的 manifests_as 入边的**非根类**机制。

    返回 (候选_id 列表, 是否由本体收窄)；给不出收窄时返回 (全部候选, False)。
    """
    mechs = _leaf_mechanisms()
    if targets:
        want = set(targets)
        hit = [m["id"] for m in mechs
               if want & set(_traverser.get_targets(m["id"], "manifests_as") or [])]
        if hit:
            return hit, True
    return [m["id"] for m in mechs], False


def _pat_match(pattern: str, text: str) -> bool:
    """判据模式匹配：把 <...> 占位当**通配**。

    判据表里本就把可变段写成占位（如 [track:<pid>] / dataConvert-<uuid>-thread-N）——
    若按字面量匹配，**真实日志行永远匹配不上**（实测：[track:1042] 对不上 [track:<pid>]），
    判据会退化成装饰。故占位一律展开为惰性通配。
    """
    if not pattern or not text:
        return False
    if "<" not in pattern:
        return pattern in text
    rx = re.sub(r"<[^>]*>", ".+?", re.escape(pattern))
    try:
        return re.search(rx, text) is not None
    except re.error:
        return False


def _obs_sources(observations: list) -> list:
    """观测条目的**来源标签**（形如 [来源]观测）。无标签一律归为同一源——保守，宁可判 unknown。"""
    out = []
    for o in observations:
        m = re.match(r"^\[([^\]]+)\]", o)
        out.append(m.group(1) if m else "未标注")
    return out


# 根类 structural 判据点名的既有关系类型（fault_mechanism.necessary_criteria 第 2 条：
# 「起点到受影响单元之间存在既有关系路径（feeds / reads_from / runs_on / registered_on / supervises）」）
_STRUCTURAL_EDGES = ("feeds", "reads_from", "runs_on", "registered_on", "supervises")


def _treatment_hint(dimensions) -> list:
    """68 号 E-2：**处置锚点**——只给「去哪一节看」，**不给命令**。

    两跳分开：『维度 → Skill』用**本体**的 `diagnosed_by`（不重复声明）；
    『Skill → 哪一节讲处置』用 `skill_manifest.yaml` 的 `treatment_entry`（这才是此前缺的一跳）。
    任何一跳缺了就**不产出该条**（宁少不臆断）；整段异常返回空列表，不影响主输出。
    """
    out = []
    try:
        from .manifest import resolve_skill_id
    except Exception:
        return out
    for d in dimensions or []:
        try:
            skills = _traverser.get_targets(d, "diagnosed_by")
        except Exception:
            skills = []
        for sk in skills:
            try:
                item = resolve_skill_id(sk) or {}
            except Exception:
                item = {}
            te = item.get("treatment_entry") or {}
            if not te.get("file"):
                continue
            out.append({
                "dimension": d, "skill": sk,
                "skill_name": (item.get("entry") or "").rstrip("/").split("/")[-1] or sk,
                "file": te.get("file"), "section": te.get("section"), "note": te.get("note"),
                "hint": "只给「去哪一节看」，不给命令",
            })
    return out

def _structural_evidence(node: str, criterion: dict, affected_unit: str = None) -> dict:
    """把 **structural** 判据接到 L2 图推理上（C-20261013-15）。

    判据里「起点到受影响单元之间存在既有关系路径」本可机械核验，但本 Tool 只有**一个**入口端点
    （缺「受影响单元」），故只做**本体侧可查的那一半**：起点在这些边类型上是否真的参与既有关系
    （出边或入边）。**只作证据、不改状态**——「受影响单元是谁」仍须人给。
    """
    present = []
    for e in _STRUCTURAL_EDGES:
        try:
            if _traverser.get_targets(node, e) or _traverser._sources(node, e):
                present.append(e)
        except Exception:
            continue
    # 68 号 E-2④：给了「受影响单元」⇒ 把「两单元之间存在路径」那半步**机械核验完**（partial → full）。
    # 用的仍是**声明边集**（既有关系路径的定义见 fault_mechanism.necessary_criteria 第 2 条）。
    two_end = None
    if affected_unit:
        try:
            ends = {p["end"]: p.get("hops") for p in _traverser.walk(
                node, depth=3, direction="both", edge_types=list(_STRUCTURAL_EDGES))}
            two_end = {"affected_unit": affected_unit, "path_found": affected_unit in ends,
                       "hops": ends.get(affected_unit),
                       "note": ("两单元间存在既有关系路径" if affected_unit in ends
                                else "在本体**已声明边集**上未找到两单元间路径——可能是真无路径，"                                     "也可能是**结构边未补密**（见 68 号 §1.2 的覆盖实测）")}
        except Exception:
            two_end = {"affected_unit": affected_unit, "path_found": None,
                       "note": "核验失败（按未知处理，不臆断）"}
    return {"entry_node": node, "declared_edges": list(_STRUCTURAL_EDGES),
            "present_at_entry": present, "path_exists": bool(present),
            "checkable": "full" if affected_unit else "partial",
            "two_endpoint": two_end,
            "note": ("本体侧已核：起点在 %s 参与既有关系；**并已核两单元间路径**（受影响单元＝%s）。"
                     % ("/".join(present) or "上述边类型上均无", affected_unit)) if affected_unit else
                    ("本体侧已核：起点在 %s 参与既有关系；**缺「受影响单元」**，故「两单元之间存在"
                     "路径」这半步仍须人给端点（C-20261013-15）。**给了 affected_unit 即可核完**（68 号 E-2）。"
                     % ("/".join(present) or "上述边类型上均无"))}


def diagnose_mechanism(args, **kwargs):
    """现象 → 候选机制 → 收敛（29 号 §4.5 输出契约；设计见 54 号）。

    **只读** plugin/mechanisms.yaml 的 criterion 与 convergence——判据表与收敛规则
    在此第一次有生产消费者。**不动** diagnose_error（裁 2＝C 的全部意义）。
    """
    _init()
    entry = str(args.get("entry", "")).strip()
    observations = [str(o) for o in (args.get("observations") or [])]
    try:
        max_c = int(args.get("max_candidates") or 4)
    except (TypeError, ValueError):
        max_c = 4
    sem = _mechanisms()
    mechs = {m["id"]: m for m in _leaf_mechanisms()}
    conv = sem.get("convergence") or {}
    tier_order = list(sem.get("tier_order") or [])

    # ① 入口归一
    kind, node, note = _norm_entry(entry)
    ctx, targets = {}, []
    if kind == "node":
        if node.startswith("error:"):
            kind, node = "code", node.split(":", 1)[1]
        elif node.startswith(("symptom:", "dimension:", "class:")):
            targets = [node]
        else:
            targets = [node]
    if kind == "code":
        ctx = _extract_bkn_context(node) or {}
        targets = list(ctx.get("dimensions") or [])
    elif kind in ("symptom", "process"):
        targets = [node]

    # ② 候选召回（第一优先；本体收窄优先，给不出就全量并如实标注）
    cand_ids, narrowed = _mech_candidates(targets)
    pool = [c for c in cand_ids if c in mechs][:max_c] or list(mechs)[:max_c]
    # P1：narrowed 是「本体是否起**功能**作用」的核心信号（此前只算不记，全代码零消费者）。
    # 一条决策点事件 + 一条台账 stage；任何异常只丢日志。
    try:
        ontology_stage("mechanism_narrow")
        if narrowed:
            for _mid in pool:
                ontology_use(_mid, stage="mechanism_narrow")
            # 收窄靠本体边（manifests_as）→ 来源分层记 bkn；判据表本身是侧车
            ontology_source("bkn", ref="mechanism_causality.bkn", n=1)
        ontology_source("sidecar", ref="mechanisms.yaml", n=1)
        from .observability import track
        track("mech_candidates", narrowed=bool(narrowed), targets=len(targets),
              targets_sample=list(targets)[:4], pool_size=len(pool), pool=list(pool)[:6])
    except Exception:
        pass

    # ③ 逐候选评估（逐条读 criterion）
    obs_text = chr(10).join(observations)
    srcs = _obs_sources(observations)
    results, counters, structurals = [], [], []
    for mid in pool:
        m = mechs.get(mid) or {}
        hits = []
        for c in (m.get("criterion") or []):
            t, strength = c.get("type"), c.get("evidence_strength")
            matched, weak = [], False
            if t in ("log_text", "log_text+sequence"):
                matched = [p for p in (c.get("patterns") or []) if _pat_match(p, obs_text)]
            elif t == "field_condition":
                matched = [f for f in (c.get("fields") or []) if f and f in obs_text]
                weak = bool(matched)
            elif t == "structural":
                continue  # 结构式判据另走池外一遍（须覆盖**根类**，故不能只扫候选池）
            if matched:
                hits.append({"type": t, "tier": c.get("tier"), "strength": strength,
                             "matched": matched, "weak": weak})
            # counter_check 自动判：**仅当判据显式给出 counter_patterns 时**（缺省＝仍须人判，
            # 否定推理的散文式 counter_check 保持人工；C-20261013-15）
            cp = [p for p in (c.get("counter_patterns") or []) if p]
            if cp and all(_pat_match(p, obs_text) for p in cp):
                counters.append({"mechanism": mid, "counter_patterns": cp,
                                 "counter_check": c.get("counter_check")})
        # ④ 收敛（逐条读 convergence；excluded 不自动判——否定推理须人判）
        # 修（C-20261013-15）：field_condition 只匹配**字段名出现**、未求值 criterion.condition
        # ⇒ weak 命中不得计入 hard（实测假阳性：观测里各提一句 state_time/last_op/delay 即 confirmed）
        hard = sum(1 for h in hits if h["strength"] == "hard" and not h.get("weak"))
        weak_hard = sum(1 for h in hits if h["strength"] == "hard" and h.get("weak"))
        srcs_hit = set()
        for h in hits:
            # 修（C-20261013-15）：归属也须用 _pat_match——否则含 <pid>/<uuid> 的日志模式
            # 永远归不到来源，恒判「来源不独立」，有 hard 证据也升不到 confirmed。
            # field_condition 的 matched 是**字段名**，仍按原样出现判（与命中判定同源）。
            _is_pat = h["type"] in ("log_text", "log_text+sequence")
            for i, o in enumerate(observations):
                if any((_pat_match(x, o) if _is_pat else x in o) for x in h["matched"]):
                    srcs_hit.add(srcs[i])
        counters_here = [c["counter_patterns"] for c in counters if c["mechanism"] == mid]
        state, why = "unknown", ""
        if counters_here:
            state = "excluded"
            why = ("counter_check 成立（counter_patterns 命中 %s）⇒ **excluded**，留档不静默丢弃"
                   "（convergence.requirements.excluded）"
                   % " / ".join(" + ".join(cp) for cp in counters_here))
        elif not hits:
            why = "无判据命中：需先取证（见 next_actions）"
        elif hard == 0:
            why = ("仅软证据命中%s ⇒ 按 hard_cap **只能到 unknown**（需一条独立 hard 证据硬化）"
                   % (("（另有 %d 条**弱**字段名命中——判据 condition 未求值，**不计** hard）" % weak_hard)
                      if weak_hard else ""))
        elif len(srcs_hit) >= 2:
            state = "confirmed"
            why = "≥2 个独立来源命中且含 hard ⇒ confirmed（counter_check 仍须人核）"
        else:
            why = "命中含 hard，但**来源不独立**（同源多命中只算 1）⇒ 停在 unknown"
        results.append({"id": mid, "state": state, "hits": hits, "why": why,
                        "tier": m.get("criteria_tier")})
    # 结构式判据**池外一遍**：根类不进候选池，但它的 structural 判据正是「起点到受影响单元之间
    # 存在既有关系路径」——本体侧那半步接 L2 图推理（C-20261013-15）。
    for _m in (_mechanisms().get("mechanisms") or []):
        for c in (_m.get("criterion") or []):
            if c.get("type") == "structural":
                ev = _structural_evidence(node, c, args.get("affected_unit"))
                if ev:
                    structurals.append(dict(ev, mechanism=_m.get("id")))
                    try:
                        from .observability import track
                        _te = ev.get("two_endpoint") or {}
                        track("structural_check", entry=node, has_affected_unit=bool(args.get("affected_unit")),
                              checkable=ev.get("checkable"), path_found=_te.get("path_found"),
                              hops=len(_te.get("hops") or []))
                    except Exception:
                        pass

    _rank = {"confirmed": 0, "unknown": 1, "excluded": 2}
    results.sort(key=lambda r: (_rank.get(r["state"], 1), -len(r["hits"]),
                                tier_order.index(r["tier"]) if r["tier"] in tier_order else 99))

    # ⑤ 五段输出（§4.5 契约）
    next_actions = []
    for r in results:
        m = mechs.get(r["id"]) or {}
        done = {h["type"] for h in r["hits"]}
        for c in (m.get("criterion") or []):
            if c.get("type") in done and c.get("type") != "field_condition":
                continue
            look = list(c.get("patterns") or []) + list(c.get("fields") or [])
            if c.get("condition"):
                look.append(c["condition"])
            if not look:
                continue
            next_actions.append({"mechanism": r["id"], "tier": c.get("tier"),
                                 "look_for": look[:3], "then": c.get("counter_check")})
            break
    if results:
        smp = (mechs.get(results[0]["id"]) or {}).get("sampling")
        if smp:
            next_actions.insert(0, {"mechanism": results[0]["id"], "tier": "sampling",
                                    "sampling": smp.get("method"),
                                    "thresholds": smp.get("thresholds")})

    gaps = []
    if kind == "code" and not (ctx.get("dimensions") or []) == []:
        dims = ctx.get("dimensions") or []
        if dims == ["dimension:unknown"] or not dims:
            gaps.append("该码**只给码定不了含义**（Q27）：需要**日志消息文本**或该码出现在哪个进程的日志")
    if not narrowed:
        gaps.append("本体未给出收窄（无机制经 manifests_as 指向该端点）⇒ 候选按**全量**给出，召回优先于精度")
    if any(h["strength"] == "soft" or h.get("weak") for r in results for h in r["hits"]) and        any(not any(x["strength"] == "hard" and not x.get("weak") for x in r["hits"]) for r in results):
        gaps.append("有候选**只有软证据或弱字段名命中**：须补一条**独立 hard 证据**"
                    "（见各判据的 hardened_by）才能升级为 confirmed")
    if not observations:
        gaps.append("本次**未提供任何观测**：结论只能是 unknown——取证动作见 next_actions")

    facts = [h for r in results for h in r["hits"]]
    _th = _treatment_hint(targets)
    try:
        from .observability import track
        track("treatment_hint", tool="diagnose_mechanism", entry_kind=kind,
              dimensions=len(targets), hits=len(_th),
              skills=sorted({h["skill"] for h in _th}) or None)
    except Exception:
        pass
    _track_reasoning_path(
        "diagnose_mechanism", node or entry, "mechanism",
        nodes=([node] if node else []) + list(targets) + list(pool),
        edges=["manifests_as"] if narrowed else [],
        hops=1,
        terminal=("no_candidate" if not results else
                  ("converged" if results[0].get("state") == "confirmed" else "candidates")),
    )
    return _wrap({
        "entry": entry, "entry_node": node, "entry_kind": kind, "entry_note": note,
        "candidates": results,
        "chain_note": "因果层**暂不可用**：机制间边 triggers/amplifies 留空"
                      "（50 号 §5；裁 3＝A）⇒ 候选**平铺**，按（状态 → 命中数 → 档位）排序。",
        "root_note": (("根类 %s **不独立出证**（mechanisms.yaml entry_fields）：它的 confirmed 必须由"
                       "某个子类的 hard 证据支撑，故**不进 candidates**（C-20261013-15）。"
                       % "/".join(_mech_roots())) if _mech_roots() else ""),
        "structural_evidence": structurals,
        # 68 号 E-2③：按入口收窄到的维度给处置锚点（同 diagnose_error 的两跳拼法）
        "treatment_hint": _th,
        "next_actions": next_actions,
        "evidence_gaps": gaps,
        "fact_vs_inference": {
            "facts": ["判据命中原文：" + " / ".join(h["matched"]) for h in facts] or ["本次无命中"],
            "inference": [r["id"] + " → " + r["state"] + "：" + r["why"] for r in results],
            "note": "**unknown 是合法答案**：证据不足时不许用推测填空"
                      "（29 号 §4.5 硬要求 3）。",
        },
        "silence_note": ("沉默端：**本次未提供任何观测**——没有观测不等于没有故障；"
                         "先按 next_actions 取证。") if not observations else (
            "已提供 %d 条观测；**未出现在观测里 ≠ 不存在**——沉默端仍需按 next_actions 主动采。" % len(observations)),
    }, args, "diagnose_mechanism", ctx=kwargs)


# ========== Handler 注册表 ==========

HANDLERS = {name: _timed_handler(fn, name) for name, fn in {
    "query_product": query_product,
    "explain_architecture": explain_architecture,
    "design_solution": design_solution,
    "check_compatibility": check_compatibility,
    "list_scenarios": list_scenarios,
    "diagnose_error": diagnose_error,
    "get_prerequisites": get_prerequisites,
    "resolve_relation": resolve_relation,
    "resolve_operation": resolve_operation,
    "search_qdrant": search_qdrant_handler,
    "diagnose_db_link": diagnose_db_link_handler,
    "check_action_risk": check_action_risk_handler,
    "diagnose_mechanism": diagnose_mechanism,
    "bkn_ask": bkn_ask_handler,
    "check_plan": check_plan_handler,
}.items()}
