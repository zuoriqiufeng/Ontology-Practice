# -*- coding: utf-8 -*-
"""tier_router.py — 89 号：知识问答 vs 现场排查的三级分流（L0/L1/L2）。

判级复用 ask_router 的信号（entity/log_pattern = 环境锚点）与 constants 锚点词表（单源）。
纯知识且无锚点无实测词 → L0；有环境锚点 → 至少 L1；有实测/变更词 → L2。
纯只读判定，不改行为；供 ask.py 标注 tier 与浏览。
"""
import re

from . import constants as C  # 锚点词表单源（勿另抄）

# 显式字符类（禁反斜杠简写类 \d\w\s\b，见 test_bkn_boundary 硬门禁）
_IP_RE = re.compile(r"[0-9]{1,3}(?:\.[0-9]{1,3}){3}")
_UUID_RE = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}|[0-9a-fA-F]{8}")
_PATH_RE = re.compile(r"(?:/[A-Za-z0-9_./-]{2,})|(?:[A-Za-z]:\\[A-Za-z0-9_\\./-]+)")
_TIME_RE = re.compile(r"(?:今天|昨天|前天|凌晨|上午|下午|晚上|[0-9]{1,2}[:：][0-9]{2}|[0-9]{1,2}点[0-9]{0,2})")
_HOST_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,61}[a-z0-9]\.[a-z]{2,}")


def _has_env_anchor(text: str) -> bool:
    return bool(_IP_RE.search(text) or _UUID_RE.search(text)
                or _PATH_RE.search(text) or _TIME_RE.search(text)
                or _HOST_RE.search(text))


def _has_change(text: str) -> bool:
    return any(w in text for w in C.TIER_CHANGE_WORDS)


def _has_look(text: str) -> bool:
    return any(w in text for w in C.TIER_LOOK_WORDS)


def tier_classify(text: str, signals=None) -> tuple:
    """返回 (tier, reason)。signals = ask_router.extract_all 的信号列表（可选，提升判级）。"""
    t = str(text or "")
    if _has_change(t):
        return ("L2", "含变更/实测意图词")
    kinds = {getattr(s, "kind", "") for s in (signals or [])}
    if kinds & {"entity", "log_pattern"}:
        return ("L1", "命中环境实体/日志模式信号")
    if _has_look(t) or _has_env_anchor(t):
        return ("L1", "只读看/查或含环境锚点")
    return ("L0", "纯知识问答")