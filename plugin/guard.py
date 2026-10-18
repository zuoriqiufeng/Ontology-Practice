"""guard.py — 回答溯源守卫（P2，灰度观测）：本体结论必须有证据，否则记 grounding_miss。

只观测、不改回答（grayscale）：
  * 从 LLM 响应里尽力取文本（dict/list/对象三种形态，取不到就跳过）；
  * 命中「本体结论」话术但没有任何证据标记 → 写一条 `grounding_miss` 轨迹事件；
  * 有证据（skill:/dimension:/symptom:/process:/证据/依据）→ 不记；
  * 任何异常都吞掉，绝不影响回答；config.yaml `guard.enabled: false` 可关。
"""
from __future__ import annotations

import json
import time

from .config import _config
from .trajectory import _append

CLAIM_MARKERS = ("根据本体", "本体显示", "本体中", "按本体", "本体表明", "本体记录", "本体里")
EVIDENCE_MARKERS = ("skill:", "dimension:", "symptom:", "process:", "证据", "依据", "来源", "bkn_hits", "paths")


def _text_of(resp) -> str:
    """尽力从响应里取文本；取不到返回空串。"""
    try:
        if isinstance(resp, str):
            return resp
        if isinstance(resp, dict):
            for key in ("content", "text", "message", "output"):
                v = resp.get(key)
                t = _text_of(v)
                if t:
                    return t
            return ""
        if isinstance(resp, (list, tuple)):
            return " ".join(_text_of(x) for x in resp)
        for attr in ("content", "text"):
            v = getattr(resp, attr, None)
            if v is not None:
                return _text_of(v)
        return ""
    except Exception:  # noqa: BLE001
        return ""


def is_ungrounded(text: str) -> bool:
    """有本体结论话术、却没有任何证据标记 → True。"""
    if not text:
        return False
    claim = any(m in text for m in CLAIM_MARKERS)
    evidence = any(m in text for m in EVIDENCE_MARKERS)
    return claim and not evidence


def llm_execution_middleware(*, request=None, next_call, **kwargs):
    resp = next_call(request)
    try:
        if not _config.get("guard", {}).get("enabled", True):
            return resp
        text = _text_of(resp)
        if is_ungrounded(text):
            _append({"event": "grounding_miss", "ts": int(time.time()),
                     "task_id": str(kwargs.get("task_id") or "")[:48],
                     "chars": len(text), "sample": text[:120], "via": "guard"})
    except Exception:  # noqa: BLE001
        pass
    return resp


def register_guard(plugin_api) -> bool:
    try:
        plugin_api.register_middleware("llm_execution", llm_execution_middleware)
        return True
    except Exception:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning("guard middleware 注册失败（平台可能不支持）", exc_info=True)
        return False
