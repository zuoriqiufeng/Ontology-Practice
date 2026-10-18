"""ask.py - bkn_ask：问题型单入口（P1：摘要优先，细节按需）

由来（77 号评测）：症状类工具单次返回 22,987 chars ≈ 9.2k tokens，Agent 用两次就吃掉一个窗口；
码类返回 854 chars 才是健康形态。因此新增一个入口做三件事：
  1) 路由：问题里带错误码 / 症状别名 -> 调既有 handler（不改旧工具契约）；
  2) 摘要：默认只回 answer + evidence + skills + open（≤600 chars）；
  3) 展开：detail="ref" 时原样返回旧 handler 的全文。
"""
from __future__ import annotations

import json
import re

from .constants import SYMPTOM_ALIASES
from .tools import HANDLERS, _init

SCHEMA = {
    "name": "bkn_ask",
    "description": (
        "用一句话问本体：给错误码或症状描述，返回摘要（≤600 字：结论 + 证据 + 该找哪个 Skill + 还缺什么）。",
        "当用户问「这个报错什么意思/怎么查」「某现象该怎么排查」时优先用它；",
        "需要完整细节时再传 detail=ref 取全文（体积可能很大）。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "自然语言问题（含错误码或症状描述最佳）"},
            "detail": {
                "type": "string",
                "enum": ["summary", "ref"],
                "description": "summary=摘要（默认）；ref=旧工具的完整返回",
            },
        },
        "required": ["question"],
    },
}

_CODE = re.compile(r"(?<![A-Za-z0-9])((?:[A-Za-z]{1,8}[-_]?)?[0-9]{3,5})(?![0-9])")


def _route(q: str):
    """返回 (tool, args)；识别不出返回 (None, 空 dict)。"""
    m = _CODE.search(q)
    if m:
        return "diagnose_error", {"error_code": m.group(1)}
    for alias in sorted(SYMPTOM_ALIASES, key=len, reverse=True):
        if alias and alias in q:
            return "diagnose_db_link", {"symptom": alias}
    return None, {}


def ask(args, **kwargs):
    _init()
    q = str(args.get("question") or "").strip()
    detail = str(args.get("detail") or "summary").strip().lower()
    tool, sub = _route(q)
    if tool is None:
        return json.dumps({
            "answer": "未识别出本体入口（问题里没有错误码，也没有已登记的症状说法）",
            "evidence": [],
            "skills": [],
            "open": ["给出错误码，或换成已登记的症状说法（见 plugin/constants.py::SYMPTOM_ALIASES）"],
        }, ensure_ascii=False)
    raw = HANDLERS[tool](sub)
    if detail in ("ref", "full", "all"):
        return raw
    payload = _summarize(tool, raw)
    payload["ref"] = "detail=ref 取全文"
    return json.dumps(_trim(payload, 600), ensure_ascii=False)


def _summarize(tool: str, raw: str) -> dict:
    try:
        d = json.loads(raw)
    except Exception:  # noqa: BLE001 - Toon 或其他形态
        return {"answer": str(raw)[:400], "evidence": [], "skills": [], "open": []}
    if tool == "diagnose_error":
        meaning = d.get("meaning") or {}
        answer = "%s -> %s" % (d.get("error_code", ""), meaning.get("rule") or meaning.get("dimension") or "未命中语义类别")
        evidence = [x for x in [d.get("error_code"), meaning.get("evidence"), meaning.get("dimension")] if x]
        skills = list(d.get("diagnosed_skills") or [])
        open_ = list(d.get("needs") or [])
        return {"answer": answer, "evidence": evidence[:3], "skills": skills[:3], "open": open_[:2]}
    if tool == "diagnose_db_link":
        knowledge = d.get("knowledge") or {}
        summary = knowledge.get("summary") or d.get("note") or ""
        skill_ctx = d.get("skill_context") or {}
        skills = [skill_ctx.get("primary_skill")] if skill_ctx.get("primary_skill") else []
        skills += [s.get("name") for s in (d.get("related_skills") or []) if isinstance(s, dict) and s.get("name")]
        skills = list(dict.fromkeys(skills))
        nav = d.get("log_navigation") or {}
        evidence = [x for x in [d.get("symptom"), d.get("db_type"), nav.get("primary")]
                    if x and str(x).lower() not in ("unknown", "none", "")]
        return {"answer": str(summary)[:200], "evidence": evidence[:3], "skills": skills[:3],
                "open": ["细节（常见原因/步骤/配置检查/日志）用 detail=ref 取"]}
    return {"answer": str(raw)[:300], "evidence": [], "skills": [], "open": []}


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
