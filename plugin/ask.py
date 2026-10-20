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

from .code_origin import classify, route as route_code
from .constants import SYMPTOM_ALIASES

_CODE = re.compile(r"(?<![A-Za-z0-9])((?:[A-Za-z]{1,8}[-_]?)?[0-9]{3,5})(?![0-9])")
_NO_TOOL = {"answer": "", "evidence": [], "skills": [], "open": []}


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
            return ("diagnose_db_link", {"symptom": alias},
                    {"origin": "symptom", "vendor": "", "ambiguous": False, "rule": "symptom_alias", "confidence": "medium"})
    return None, {}, {"origin": "unknown", "vendor": "", "ambiguous": False, "rule": "", "confidence": "low"}


def ask(args, **kwargs):
    from .tools import HANDLERS, _init, _log_exempt_call  # 懒加载，避免 tools→ask→tools 循环
    _init()
    q = str(args.get("question") or "").strip()
    detail = str(args.get("detail") or "summary").strip().lower()
    tool, sub, meta = _route(q)
    raw = ""
    if tool is None:
        payload = _needs_payload(meta)
        out = json.dumps(_trim(payload, 600), ensure_ascii=False)
    else:
        raw = HANDLERS[tool](sub)
        if detail in ("ref", "full", "all"):
            out = raw
        else:
            payload = _summarize(tool, raw, meta)
            payload["ref"] = "detail=ref 取全文"
            out = json.dumps(_trim(payload, 600), ensure_ascii=False)
    _record(meta, q, out, raw, tool)
    _log_exempt_call("bkn_ask", args, kwargs, raw or out, out,
                     usage_fields={"route": tool or "none", "detail": detail,
                                    "code_origin": meta.get("origin"), "ambiguous": meta.get("ambiguous"),
                                    "delegated_to": tool or "none",
                                    "summary_chars": len(out), "raw_chars": len(raw),
                                    "compression": round(len(raw) / max(len(out), 1), 2) if raw else None},
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
        if origin in ("oracle", "mysql", "postgres", "db2", "sqlserver"):
            answer = ("该码是 %s 原生错误码（非 Demo Product 产品码）：本体只给排查落点与 Skill，"
                      "含义以 DB 文档/Skill 为准。" % vendor)
            open_ = ["需要精确含义时加载推荐 Skill（详情用 detail=ref）"]
        else:
            answer = str(summary)[:200]
            open_ = ["细节（常见原因/步骤/配置检查/日志）用 detail=ref 取"]
        return {"answer": answer, "evidence": evidence[:3], "skills": skills[:3], "open": open_[:2],
                "code_origin": origin, "confidence": _confidence(meta)}
    return {"answer": str(raw)[:300], "evidence": [], "skills": [], "open": [],
            "code_origin": origin, "confidence": _confidence(meta)}


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
