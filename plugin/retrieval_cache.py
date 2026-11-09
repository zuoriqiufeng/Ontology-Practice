"""retrieval_cache.py — 检索结果缓存（86 号计划 R1a，2026-11-01）。

只读加速、不做正确性：同 key 命中直接返回上次结果。默认 TTL + 容量上限，config 可关。

设计取舍：
- 覆盖 supplement 层 search_qdrant / _search_mini_first / _search_chunk_level 三个检索入口，
  使「模型直接 search_qdrant」与「diagnose_db_link 内部补充检索」都吃到缓存；
- 命中返回深拷贝快照（88 号 B1）——调用方原地改嵌套 list/dict 也不会污染缓存与后续命中；
- 版本热重载（bkn_reload 换版）时由 loaded_version 主动 clear()，避免脏命中。
"""
from __future__ import annotations

import contextvars
import copy
import json
import logging
import threading
import time

logger = logging.getLogger(__name__)

from .config import (
    SEARCH_CACHE_ENABLED,
    SEARCH_CACHE_MAX,
    SEARCH_CACHE_TTL,
)

_ttl = max(1, int(SEARCH_CACHE_TTL))
_max = max(1, int(SEARCH_CACHE_MAX))
_lock = threading.Lock()
# key -> (deadline, list)
_store: dict = {}
# 88 B3：命中/未命中计数（供 efficiency_report 与观测）
_stats = {"hit": 0, "miss": 0}
# 90：会话上下文（由 tools._timed_handler 在真入口灌入），供缓存命中写 usage 时带 task/session
_SESS = contextvars.ContextVar("bkn_retrieval_cache_sess", default=None)


def set_session_context(sess) -> None:
    _SESS.set(dict(sess or {}))


def enabled() -> bool:
    return bool(SEARCH_CACHE_ENABLED)


def _stable_part(p):
    """把 key 参数归一成**跨 reload 稳定**的值（88 号 B2）。

    qdrant client / embedding model 等对象若走 repr 会带内存地址，reload 即变、缓存必失效；
    这类对象不影响检索结果语义，统一记为 <类型名>。"""
    if p is None or isinstance(p, (str, int, float, bool)):
        return p
    if isinstance(p, (list, tuple)):
        return [_stable_part(x) for x in p]
    if isinstance(p, dict):
        return {k: _stable_part(v) for k, v in sorted(p.items(), key=lambda kv: str(kv[0]))}
    return "<" + type(p).__name__ + ">"


def make_key(*parts) -> str:
    """稳定 key：对参数做「稳定归一」（88 号 B2，去对象 repr 的地址漂移）。"""
    try:
        return json.dumps([_stable_part(p) for p in parts], ensure_ascii=False)
    except Exception:  # noqa: BLE001
        return repr(parts)


def get(key: str):
    if not enabled():
        return None
    with _lock:
        item = _store.get(key)
        if not item:
            _stats["miss"] += 1
            return None
        deadline, val = item
        if time.time() >= deadline:
            _store.pop(key, None)
            _stats["miss"] += 1
            return None
        _stats["hit"] += 1
        # 87 O-01
        return [_copy_hit(x) for x in val]


def set(key: str, val) -> None:
    if not enabled() or not isinstance(val, list):
        return
    with _lock:
        # 87 O-01
        _store[key] = (time.time() + _ttl, [_copy_hit(x) for x in val])
        if len(_store) > _max:
            oldest = min(_store, key=lambda k: _store[k][0])
            _store.pop(oldest, None)


def stats() -> dict:
    """88 B3：缓存命中/未命中计数快照。"""
    with _lock:
        return dict(_stats)


def reset_stats() -> None:
    with _lock:
        _stats["hit"] = 0
        _stats["miss"] = 0


def _track_event(layer: str, result: str) -> None:
    """88 B3：发一条缓存命中/未命中观测事件（失败静默，不影响检索）。"""
    try:
        from .observability import track
        track("retrieval_cache", layer=layer, result=result)
    except Exception:  # noqa: BLE001
        logger.warning("retrieval_cache._track_event 失败（命中埋点）", exc_info=True)


def log_cache_event(layer: str, result: str) -> None:
    """90 B3：缓存命中/未命中落 usage（record_type=cache_hit/cache_miss，带会话字段）。"""
    try:
        from .usage_log import log_usage
        s = _SESS.get() or {}
        fields = {"record_type": "cache_" + result, "layer": layer}
        if s.get("task_id"):
            fields["task_id"] = s["task_id"]
        if s.get("session_id"):
            fields["session_id"] = s["session_id"]
        log_usage("search_qdrant", **fields)
    except Exception:  # noqa: BLE001
        logger.warning("retrieval_cache.log_cache_event 失败（命中率埋点）", exc_info=True)


def _copy_hit(x):
    # 88 号 B1：深拷贝——仅顶层 dict(x) 不够，嵌套 list/dict 仍共享引用可跨用例污染。
    try:
        return copy.deepcopy(x)
    except Exception:  # noqa: BLE001
        return dict(x) if isinstance(x, dict) else x


def clear() -> None:
    with _lock:
        _store.clear()


def _cached_retrieval(fn):
    """装饰器：包裹 supplement 检索入口，命中直接返回上次数值。"""
    from functools import wraps

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not enabled():
            return fn(*args, **kwargs)
        key = make_key(fn.__name__, args, kwargs)
        hit = get(key)
        _track_event(fn.__name__, "hit" if hit is not None else "miss")
        log_cache_event(fn.__name__, "hit" if hit is not None else "miss")
        if hit is not None:
            return hit
        out = fn(*args, **kwargs)
        set(key, out)
        return out

    return wrapper
