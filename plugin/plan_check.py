"""plan_check.py — 计划可行性检查（P2）：`,

按本体里**已登记的动作前置与约束**做机械核对，回答「这串操作能不能这么走」。
只做机械核对（不推理、不猜）：
  * `prerequisites: [X must be Y, ...]` → 与调用方给的 `states` 比对；
  * `constraints: [cid, ...]` → 查 `bkn/risks/constraints.bkn` 登记表，回类型与约束原文；
  * 中文/不可解析的前置 → 进 `todo`（如实说「需人工确认」，不编结论）。
"""
from __future__ import annotations

import json
import re

from .cards import BKN_ROOT

_ROW = re.compile(r"^\|[^|]+\|[ \t]*([a-z_][a-z0-9_]*)[ \t]*\|[ \t]*([a-z_]+)[ \t]*\|[ \t]*(.+?)[ \t]*\|$")
_REQ = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)[ \t]+must[ \t]+be[ \t]+([A-Za-z_][A-Za-z0-9_]*)")


def _list(line: str) -> list:
    """`- key: [a, b, c]` → ["a", "b", "c"]（2-1 修复：逐项去方括号）。"""
    raw = line.split(":", 1)[1].strip()
    return [x.strip().strip("[]") for x in raw.split(",") if x.strip().strip("[]")]


def _action_segments() -> dict:
    out = {}
    d = BKN_ROOT / "actions"
    if not d.is_dir():
        return out
    for f in sorted(d.glob("*.bkn")):
        try:
            lines = f.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        seg = None
        for ln in lines:
            s = ln.strip()
            if s.startswith("## Action: "):
                name = s[len("## Action: "):].strip()
                seg = {"name": name, "file": f.name, "prereq": [], "constraints": [], "aliases": []}
                out[name] = seg
                continue
            if seg is None:
                continue
            if s.startswith("- aliases:"):
                seg["aliases"] = _list(s)
            elif s.startswith("- prerequisites:"):
                seg["prereq"] = _list(s)
            elif s.startswith("- constraints:"):
                seg["constraints"] = _list(s)
    return out


def _constraints() -> dict:
    rows = {}
    p = BKN_ROOT / "risks" / "constraints.bkn"
    if not p.is_file():
        return rows
    for ln in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = _ROW.match(ln.strip())
        if m and m.group(1) not in rows:
            rows[m.group(1)] = {"type": m.group(2), "text": m.group(3)}
    return rows


def _resolve(actions: dict, name: str):
    if name in actions:
        return actions[name]
    for seg in actions.values():
        if name in seg["aliases"]:
            return seg
    return None


def check_plan(args, **kwargs):
    steps = args.get("steps") or []
    states = args.get("states") or {}
    actions = _action_segments()
    constraints = _constraints()
    violations, advisories, todo = [], [], []
    for i, step in enumerate(steps, 1):
        name = str((step or {}).get("action") or "").strip()
        seg = _resolve(actions, name)
        if seg is None:
            todo.append({"step": i, "why": "动作未在本体登记：%s" % name})
            continue
        state = str((step or {}).get("state") or "").strip()
        for idx, req in enumerate(seg["prereq"]):
            m = _REQ.search(req)
            if not m:
                todo.append({"step": i, "why": "前置需人工确认：%s" % req})
                continue
            obj, want = m.group(1), m.group(2)
            have = states.get(obj)
            if have is None and idx == 0 and state:
                have = state
            if have is None:
                todo.append({"step": i, "why": "前置需人工确认：%s（未提供 %s 状态）" % (req, obj)})
                continue
            if str(have).upper() != want.upper():
                violations.append({"step": i, "rule": "state_prerequisite",
                                   "message": "%s 要求 %s=%s（现为 %s）" % (seg["name"], obj, want, have),
                                   "evidence": "%s · prerequisites" % seg["file"]})
        for cid in seg["constraints"]:
            info = constraints.get(cid) or {}
            advisories.append({"step": i, "constraint": cid, "type": info.get("type"),
                               "text": info.get("text"), "evidence": "risks/constraints.bkn"})
    result = {"ok": not violations, "checked_steps": len(steps),
              "violations": violations, "advisories": advisories, "todo": todo}
    out = json.dumps(result, ensure_ascii=False)
    try:
        from .tools import _log_exempt_call
        _log_exempt_call("check_plan", args, kwargs, out, out,
                         usage_fields={"steps": len(steps), "violations": len(violations),
                                        "advisories": len(advisories), "todo": len(todo)},
                         assess=False)
    except Exception:  # noqa: BLE001
        pass
    return out
