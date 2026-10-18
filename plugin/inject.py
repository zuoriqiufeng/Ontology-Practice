"""inject.py — 请求级卡片注入（P1b，`llm_request` middleware）

只做一件事：当**最近一条用户消息**里出现错误码或已登记症状时，在请求的 system 消息末尾
追加一段 ≤600 字的「本体卡片」（带 MARKER，幂等），让本体出现在模型「眼前」；无命中则零改动。

约束：
  * 有界：卡片 ≤600 字；一段会话只注一次（MARKER 去重）；
  * 可关：config.yaml `inject.enabled: false` 直接短路；
  * 不改历史：只动 system 消息或插入一条 system 消息，不改用户原文。
"""
from __future__ import annotations

import re

from .cards import build_card
from .config import _config
from .constants import SYMPTOM_ALIASES

MARKER = "【BKN 卡片】"
LIMIT = 600
_CODE = re.compile(r"(?<![A-Za-z0-9])((?:[A-Za-z]{1,8}[-_]?)?[0-9]{3,5})(?![0-9])")


def _last_user_text(messages: list) -> str:
    for m in reversed(messages):
        if isinstance(m, dict) and str(m.get("role")) == "user":
            c = m.get("content")
            if isinstance(c, str):
                return c
            if isinstance(c, list):
                return " ".join(str(x.get("text", "")) for x in c if isinstance(x, dict))
    return ""


def detect(text: str):
    """返回 ("code", 码) / ("symptom", 说法)，无命中返回 None。"""
    if not text:
        return None
    m = _CODE.search(text)
    if m:
        return ("code", m.group(1))
    for alias in sorted(SYMPTOM_ALIASES, key=len, reverse=True):
        if alias and alias in text:
            return ("symptom", alias)
    return None


def build_block(kind: str, target: str, limit: int = LIMIT) -> str:
    """生成注入块：码不内置码表（码＝入口）；症状给「先查本体」的指路。"""
    if kind == "code":
        return ("错误码 %s：码只是入口，不要凭记忆答码义。" % target
                + chr(10)
                + "下一步：调 bkn_ask（question=该码，或附日志文本）取 meaning/dimension。")[:limit]
    return ("症状「%s」：先查本体，再取证。" % target
            + chr(10)
            + "下一步：调 bkn_ask（question=「%s」）取 recommended_skills / log_navigation；细节用 detail=ref。" % target)[:limit]


def llm_request_middleware(**kwargs):
    """Hermes `llm_request` middleware：返回 {"request": ...} 或 None。"""
    try:
        if not _config.get("inject", {}).get("enabled", True):
            return None
    except Exception:  # noqa: BLE001
        pass
    req = kwargs.get("request")
    if not isinstance(req, dict):
        return None
    messages = req.get("messages")
    if not isinstance(messages, list) or not messages:
        return None
    text = _last_user_text(messages)
    hit = detect(text)
    if not hit:
        return None
    block = build_block(hit[0], hit[1])
    if not block or MARKER in block:
        return None
    block = "\n\n" + MARKER + "\n" + block
    new_msgs = [dict(m) if isinstance(m, dict) else m for m in messages]
    sys_idx = None
    for i, m in enumerate(new_msgs):
        if isinstance(m, dict) and str(m.get("role")) == "system":
            sys_idx = i
            break
    if sys_idx is not None and isinstance(new_msgs[sys_idx].get("content"), str):
        if MARKER in new_msgs[sys_idx]["content"]:
            return None
        new_msgs[sys_idx]["content"] = new_msgs[sys_idx]["content"] + block
    else:
        new_msgs.insert(0, {"role": "system", "content": block})
    new_req = dict(req)
    new_req["messages"] = new_msgs
    return {"request": new_req, "source": "bkn-ontology",
            "reason": "inject %s card for %s" % (hit[0], hit[1])}


def register_inject(plugin_api) -> bool:
    try:
        plugin_api.register_middleware("llm_request", llm_request_middleware)
        return True
    except Exception:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning("inject middleware 注册失败（平台可能不支持）", exc_info=True)
        return False
