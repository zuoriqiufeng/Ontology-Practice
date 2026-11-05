"""retrieval_cache.py — 检索结果缓存（86 号计划 R1a，2026-11-01）。

只读加速、不做正确性：同 key 命中直接返回上次结果。默认 TTL + 容量上限，config 可关。

设计取舍：
- 覆盖 supplement 层 search_qdrant / _search_mini_first / _search_chunk_level 三个检索入口，
  使「模型直接 search_qdrant」与「diagnose_db_link 内部补充检索」都吃到缓存；
- 命中返回的是上次结果的列表引用（浅分享），调用方不得原地改写元素结构；
- 版本热重载（bkn_reload 换版）时由 loaded_version 主动 clear()，避免脏命中。
"""
from __future__ import annotations

import json
import threading
import time

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


def enabled() -> bool:
    return bool(SEARCH_CACHE_ENABLED)


def make_key(*parts) -> str:
    """稳定 key：对参数做 repr 归一（tuple/list/dict 皆可）。"""
    try:
        return json.dumps([repr(p) for p in parts], ensure_ascii=False)
    except Exception:  # noqa: BLE001
        return repr(parts)


def get(key: str):
    if not enabled():
        return None
    with _lock:
        item = _store.get(key)
        if not item:
            return None
        deadline, val = item
        if time.time() >= deadline:
            _store.pop(key, None)
            return None
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


def _copy_hit(x):
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
        if hit is not None:
            return hit
        out = fn(*args, **kwargs)
        set(key, out)
        return out

    return wrapper
