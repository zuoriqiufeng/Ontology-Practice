"""ask.py — bkn_ask：问题型单入口（P1 摘要优先；C-20261019-01 码来源分流）。

为什么要有这个入口：
  1) 摘要：症状类工具单次返回 22,987 chars（77 号），默认只回 answer/evidence/skills/open；
  2) 分流：**错误码先分来源**——产品码 → diagnose_error；数据库原生码（ORA-/SQLSTATE/1062…）
     → diagnose_db_link(db_type=vendor)；来源不明 → 返回 needs，不猜（code_origin.py）；
  3) 展开：detail="ref" 时原样返回所委托工具的全文。
"""
from __future__ import annotations

import json
import re
import time

from .code_origin import classify, route as route_code
from .constants import SYMPTOM_ALIASES
from .ask_router import attach_intents, extract_all, log_route_trace, resolve_intent, router_enabled

_CODE = re.compile(r"(?<![A-Za-z0-9])((?:[A-Za-z]{1,8}[-_]?)?[0-9]{3,5})(?![0-9])")
_NO_TOOL = {"answer": "", "evidence": [], "skills": [], "open": []}

_CACHE = {}
_CACHE_TTL = 600
_CACHE_MAX = 64


def display_symptom(sid: str) -> str:
    """规范症状 ID → 首个中文别名（找不到回退原 ID）；只用于展示，evidence 仍保留 ID。"""
    for alias, canonical in SYMPTOM_ALIASES.items():
        if canonical == sid:
            return alias
    return sid


def _first_cause(d: dict) -> str:
    """从 db_link 的 knowledge_context 里取第一条常见原因，压到 160 字。"""
    kc = d.get("knowledge_context") or {}
    raw = kc.get("common_causes") or kc.get("recommended_steps") or ""
    items = raw
    if isinstance(raw, str):
        try:
            items = json.loads(raw)
        except Exception:  # noqa: BLE001
            items = []
    for it in items or []:
        if isinstance(it, dict):
            c = it.get("content") or it.get("preview") or ""
        else:
            c = str(it)
        if c:
            return str(c).strip()[:160]
    return ""


def _cache_get(key):
    item = _CACHE.get(key)
    if item and time.time() - item["ts"] < _CACHE_TTL:
        return item["out"]
    return None


def _cache_put(key, out: str) -> None:
    if len(_CACHE) >= _CACHE_MAX:
        _CACHE.clear()
    _CACHE[key] = {"ts": time.time(), "out": out}


def _route(q: str):
    """返回 (tool, args, meta)。meta 含 code_origin/vendor/ambiguous/confidence。"""
    m = _CODE.search(q)
    if m:
        code = m.group(1)
        tool, args, info = route_code(code, message=q)
        info = dict(info)
        info["code"] = code
        info["code_detected"] = True
        return tool, args, info
    for alias in sorted(SYMPTOM_ALIASES, key=len, reverse=True):
        if alias and alias in q:
            return ("diagnose_db_link", {"symptom": SYMPTOM_ALIASES[alias]},
                    {"origin": "symptom", "vendor": "", "ambiguous": False, "rule": "symptom_alias", "confidence": "medium"})
    return None, {}, {"origin": "unknown", "vendor": "", "ambiguous": False, "rule": "", "confidence": "low"}


def ask(args, **kwargs):
    from .tools import HANDLERS, _init, _log_exempt_call  # 懒加载，避免 tools→ask→tools 循环
    _init()
    q = str(args.get("question") or "").strip()
    detail = str(args.get("detail") or "summary").strip().lower()
    cache_key = (kwargs.get("task_id"), q, detail)
    if detail not in ("ref", "full", "all"):
        cached = _cache_get(cache_key)
        if cached is not None:
            _log_exempt_call("bkn_ask", args, kwargs, cached, cached,
                             usage_fields={"route": "cache", "detail": detail, "cache_hit": True,
                                            "summary_chars": len(cached), "raw_chars": 0},
                             assess=False, confidence="partial")
            return cached
    tool, sub, meta = _route(q)
    _sigs = []
    _primary = None
    if router_enabled():
        _sigs = extract_all(q)
        _primary = resolve_intent(q, signals=_sigs)
        log_route_trace(q, _sigs, _primary)
        if _primary is not None:
            _shadow_note(q, _primary, meta)
            tool, sub, meta = _primary
    raw = ""
    enrich_items, enrich_err, enrich_top = [], "", 0.0
    if tool is None:
        payload = _trim(_needs_payload(meta), 600)
        if _sigs:
            attach_intents(payload, _sigs, _primary)
        if detail not in ("ref", "full", "all") and _need_enrich(payload, tool):
            enrich_items, enrich_err, enrich_top = _enrich(q)
            if enrich_items:
                payload["enrichment"] = enrich_items
        out = json.dumps(payload, ensure_ascii=False)
    else:
        raw = HANDLERS[tool](sub)
        if detail in ("ref", "full", "all"):
            out = raw
        else:
            payload = _summarize(tool, raw, meta)
            payload["ref"] = "detail=ref 取全文"
            payload = _trim(payload, 600)
            if _sigs:
                attach_intents(payload, _sigs, _primary)
            if _need_enrich(payload, tool):
                enrich_items, enrich_err, enrich_top = _enrich(q)
                if enrich_items:
                    payload["enrichment"] = enrich_items
            out = json.dumps(payload, ensure_ascii=False)
    _record(meta, q, out, raw, tool)
    if detail not in ("ref", "full", "all"):
        _cache_put(cache_key, out)
    _log_exempt_call("bkn_ask", args, kwargs, raw or out, out,
                     usage_fields={"route": tool or "none", "detail": detail,
                                    "code_origin": meta.get("origin"), "ambiguous": meta.get("ambiguous"),
                                    "delegated_to": tool or "none", "cache_hit": False,
                                    "ask_router_enabled": bool(_sigs),
                                    "ask_router_hit": _primary is not None,
                                    "intents": len(_sigs),
                                    "summary_chars": len(out), "raw_chars": len(raw),
                                    "compression": round(len(raw) / max(len(out), 1), 2) if raw else None,
                                    "enrich": len(enrich_items),
                                    "enrich_chars": sum(len(x["content"]) for x in enrich_items),
                                    "enrich_top_score": round(enrich_top, 4) if enrich_top else None,
                                    "enrich_error": enrich_err or None},
                     assess=False, confidence=_confidence(meta))
    return out


def _confidence(meta: dict) -> str:
    origin = meta.get("origin")
    if origin == "product":
        return "full"
    if origin in ("oracle", "mysql", "postgres", "db2", "sqlserver", "symptom"):
        return "partial"
    return "partial"


def _needs_payload(meta: dict) -> dict:
    origin = meta.get("origin")
    code = meta.get("code") or ""
    evidence = [code] if code and meta.get("code_detected") else []
    if code and origin == "unknown":
        return {"answer": "已定位到码 %s，但无法识别来源（既不在产品码表，也不匹配已知数据库码形）。" % code,
                "evidence": evidence, "skills": [],
                "open": ["库类型（oracle/mysql/postgres/db2/sqlserver 之一），或该码所在日志文本/来源"],
                "code_origin": origin, "confidence": "partial"}
    if origin == "ambiguous":
        answer = "已识别为错误码，但**无法确定来源**（可能是 Demo Product 产品码，也可能是数据库原生码）。"
        need = ["库类型（oracle/mysql/postgres/db2/sqlserver 之一），或该码所在日志文本/来源"]
    else:
        answer = "未识别出本体入口（既没有可定位的错误码，也没有已登记的症状说法）。"
        need = ["给出错误码（含库类型更好），或换成已登记的症状说法"]
    return {"answer": answer, "evidence": evidence, "skills": [],
            "open": need, "code_origin": origin, "confidence": "partial"}


def _need_enrich(payload: dict, tool) -> bool:
    """摘要不足才附 enrichment。

    不附：sufficient 显式 True（症状已有处置）或 confidence=full（产品码含义直出）。
    要附：open 非空（DB 码缺 Skill 细节 / 症状缺证据）或路由 none（来源不明/未识别）。
    """
    if payload.get("sufficient") is True:
        return False
    if payload.get("confidence") == "full":
        return False
    if payload.get("open"):
        return True
    return tool is None


def _enrich(query: str):
    """检索 top 命中作为 enrichment；任何异常静默降级。

    返回 (items, err, top_score)。预算由 config.ASK_ENRICH_CHARS 控制（只计 content），
    不挤压 ≤600 字摘要（摘要先 _trim，再追加 enrichment 字段）。
    """
    from .config import ASK_ENRICH, ASK_ENRICH_TOPK, ASK_ENRICH_MIN_SCORE, ASK_ENRICH_CHARS
    if not ASK_ENRICH or ASK_ENRICH_TOPK <= 0:
        return [], "", 0.0
    try:
        from .supplement import search_qdrant as _search
        hits = _search(query, top_k=ASK_ENRICH_TOPK, hybrid=True) or []
    except Exception as exc:  # noqa: BLE001 - 降级：检索失败不影响主答案
        return [], type(exc).__name__, 0.0
    try:
        from .tools import _window_content
    except Exception:  # noqa: BLE001
        _window_content = None
    items = []
    used = 0
    top = 0.0
    for h in hits:
        try:
            score = float(h.get("score") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        top = max(top, score)
        if score < ASK_ENRICH_MIN_SCORE:
            continue
        content = str(h.get("content") or "").strip()
        if not content:
            continue
        if _window_content is not None:
            content = _window_content(content, query, 280)
        content = content[: max(0, ASK_ENRICH_CHARS - used)]
        if not content:
            break
        used += len(content)
        items.append({"content": content, "score": round(score, 4),
                      "source": h.get("source", ""), "chunk_level": h.get("chunk_level", "")})
        if len(items) >= ASK_ENRICH_TOPK:
            break
    return items, "", top


def _summarize(tool: str, raw: str, meta: dict) -> dict:
    try:
        d = json.loads(raw)
    except Exception:  # noqa: BLE001 - Toon 或其他形态
        return {"answer": str(raw)[:400], "evidence": [], "skills": [], "open": [],
                "code_origin": meta.get("origin"), "confidence": _confidence(meta)}
    origin = meta.get("origin")
    if tool == "diagnose_error":
        meaning = d.get("meaning") or {}
        answer = "%s -> %s" % (d.get("error_code", ""), meaning.get("rule") or meaning.get("dimension") or "未命中语义类别")
        evidence = [x for x in [d.get("error_code"), meaning.get("evidence"), meaning.get("dimension")] if x]
        skills = list(d.get("diagnosed_skills") or [])
        open_ = list(d.get("needs") or [])
        return {"answer": answer, "evidence": evidence[:3], "skills": skills[:3], "open": open_[:2],
                "code_origin": "product", "confidence": "full"}
    if tool == "diagnose_db_link":
        knowledge = d.get("knowledge") or {}
        summary = knowledge.get("summary") or d.get("note") or ""
        skill_ctx = d.get("skill_context") or {}
        skills = [skill_ctx.get("primary_skill")] if skill_ctx.get("primary_skill") else []
        skills += [s.get("name") for s in (d.get("related_skills") or []) if isinstance(s, dict) and s.get("name")]
        skills = list(dict.fromkeys(skills))
        nav = d.get("log_navigation") or {}
        vendor = meta.get("vendor") or d.get("db_type") or ""
        evidence = [x for x in [d.get("error_code") or d.get("symptom"), vendor, nav.get("primary")]
                    if x and str(x).lower() not in ("unknown", "none", "")]
        sym = str(d.get("symptom") or "")
        sym_name = display_symptom(sym) if origin == "symptom" else sym
        snippet = _first_cause(d)
        if origin in ("oracle", "mysql", "postgres", "db2", "sqlserver"):
            answer = ("该码是 %s 原生错误码（非 Demo Product 产品码）：本体只给排查落点与 Skill，"
                      "含义以 DB 文档/Skill 为准。" % vendor)
            open_ = ["需要精确含义时加载推荐 Skill（详情用 detail=ref）"]
            next_ = {}
            sufficient = False
        else:
            answer = str(summary)[:200]
            if sym and sym_name != sym:
                answer = answer.replace(sym, sym_name)
            sufficient = bool(snippet) or bool(skills)
            next_ = {"query": "%s 常见原因 排查步骤" % (sym_name or "该症状"), "top_k": 3}
            open_ = [] if sufficient else ["还缺具体细节：可 search_qdrant(compact=true, top_k=3) 一次"]
        return {"answer": answer, "evidence": evidence[:3], "skills": skills[:3], "open": open_[:2],
                "code_origin": origin, "confidence": _confidence(meta),
                "symptom_name": sym_name, "snippet": snippet, "next": next_, "sufficient": sufficient}
    return {"answer": str(raw)[:300], "evidence": [], "skills": [], "open": [],
            "code_origin": origin, "confidence": _confidence(meta)}


def _shadow_note(q, v2, meta_v1) -> None:
    """P2 影子对照：仅当 ask_router 启用且 v2 取了与 v1 不同的路径时记一条（供评估/回退）。"""
    try:
        origin_v2 = (v2[2] or {}).get("origin")
        origin_v1 = (meta_v1 or {}).get("origin")
        if origin_v2 == origin_v1:
            return
        from .supplement import log_gap
        log_gap("bkn_ask_shadow", {"question": (q or "")[:120], "v1_origin": origin_v1,
                                    "v2_tool": v2[0], "v2_origin": origin_v2},
                "partial", ["ask_router_v2"])
    except Exception:
        pass


def _record(meta: dict, q: str, out: str, raw: str, tool) -> None:
    """非产品码 → 记一条 foreign_code 缺口（进入缺口→候选闭环，不进本体）。

    只在**确实定位到码**时记录；没有码的普通问题不写 foreign_code（C-20261020-01：修误报）。
    """
    if not meta.get("code_detected"):
        return
    origin = meta.get("origin")
    if origin in ("product", "symptom"):
        return
    try:
        from .supplement import log_gap
        log_gap("bkn_ask", {"question": q[:120]}, "partial",
                ["foreign_code: origin=%s code_ambiguous=%s" % (origin, bool(meta.get("ambiguous")))])
    except Exception:  # noqa: BLE001
        pass


def _trim(payload: dict, limit: int) -> dict:
    """把 payload 压到 ≤limit 字符：先截列表字段，再兜底截 answer。"""
    if len(json.dumps(payload, ensure_ascii=False)) <= limit:
        return payload
    for key in ("open", "skills", "evidence"):
        payload[key] = payload.get(key, [])[:2]
        if len(json.dumps(payload, ensure_ascii=False)) <= limit:
            return payload
    if len(json.dumps(payload, ensure_ascii=False)) > limit:
        payload["answer"] = str(payload.get("answer", ""))[: max(40, limit // 3)]
    return payload
