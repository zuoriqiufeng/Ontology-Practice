"""context_refs.py — `@bkn:` 按需展开（P1b，Hermes context reference）。

用户/模型在消息里写 `@bkn:syncrule` 或 `@bkn:code/-4050` 时，把对应卡片展开进上下文；
与 `bkn_ask` 的 `detail=ref` 互补：一个按需拉、一个主动推。
"""
from __future__ import annotations

from .cards import BKN_ROOT, build_card

try:  # 在 Hermes 内运行
    from agent.context_references import ContextCompletionItem, ContextReferenceProvider
except Exception:  # noqa: BLE001 — 独立运行/测试环境
    class ContextCompletionItem:  # type: ignore[no-redef]
        __slots__ = ("text", "display", "meta")

        def __init__(self, text: str, display: str = "", meta: str = ""):
            self.text = text
            self.display = display or text
            self.meta = meta

    class ContextReferenceProvider:  # type: ignore[no-redef]
        prefix = ""
        description = ""

        async def autocomplete(self, query: str, *, limit: int = 10):
            return []

        async def expand(self, target: str):
            return None

_FOLDERS = {"object": "objects", "risk": "risks", "dimension": "objects", "relation": "relations", "action": "actions"}
_KINDS = {"object": "object", "obj": "object", "o": "object", "risk": "risk", "r": "risk",
          "dimension": "dimension", "dim": "dimension", "d": "dimension",
          "relation": "relation", "rel": "relation", "action": "action", "act": "action"}


def _scan(folder: str, limit: int = 300) -> list:
    d = BKN_ROOT / folder
    ids = []
    if not d.is_dir():
        return ids
    for f in sorted(d.glob("*.bkn")):
        ids.append(f.stem)
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for raw in text.splitlines():
            s = raw.strip()
            if s.startswith("## ") and ":" in s:
                seg = s[3:].split(":", 1)[1].strip()
                if seg:
                    ids.append(seg)
            elif s.startswith("id:"):
                ids.append(s[3:].strip())
    return list(dict.fromkeys(ids))[:limit]


class BknReferenceProvider(ContextReferenceProvider):
    prefix = "bkn"
    description = "本体卡片（@bkn:<id> / @bkn:code/<码> / @bkn:risk/<id>）"

    async def autocomplete(self, query: str, *, limit: int = 10) -> list:
        q = (query or "").strip().lower()
        out = []
        for ident in _scan("objects"):
            if q and q not in ident.lower():
                continue
            out.append(ContextCompletionItem("bkn:" + ident, ident, "本体对象/维度"))
            if len(out) >= limit:
                break
        return out

    async def expand(self, target: str):
        t = (target or "").strip()
        if not t:
            return None
        kind = "object"
        if "/" in t:
            head, t = t.split("/", 1)
            kind = _KINDS.get(head.strip().lower(), "object")
            t = t.strip()
        if kind == "object" and t[:1] in "-0123456789":
            return None  # 码不展开（码表不在本体）
        card = build_card(kind, t)
        if not card or card.startswith("未找到"):
            return None
        return card


def register_context_refs(plugin_api) -> bool:
    try:
        plugin_api.register_context_reference(BknReferenceProvider())
        return True
    except Exception:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning("context reference 注册失败（平台可能不支持）", exc_info=True)
        return False
