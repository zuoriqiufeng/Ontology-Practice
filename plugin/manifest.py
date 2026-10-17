"""manifest.py — 聚合间接层加载器（批 7，18 号方案 §3.3 / Q7 已裁：落 plugin）。

「ID → 实现」单点解析：BKN 只持语义 ID（skill:/tool:/store:），
manifest（plugin/skill_manifest.yaml）承载 ID → entry/collection/handler 映射。
改名/换实现 = 只动 manifest，不触发 .bkn 与测试断言 diff（P0 可操作化）。

未命中返回 None → 调用方走旧路径兜底（过渡期兼容；lint _check_ref_resolution 会拦悬空引用）。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

MANIFEST_PATH = Path(__file__).resolve().parent / "skill_manifest.yaml"


@lru_cache(maxsize=1)
def load_manifest() -> dict:
    """加载 manifest（带缓存）。缺失/解析失败返回空结构（调用方兜底）。"""
    if not MANIFEST_PATH.exists():
        return {"skills": [], "tools": [], "stores": []}
    try:
        import yaml
        data = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        return {"skills": [], "tools": [], "stores": []}
    return {
        "skills": data.get("skills") or [],
        "tools": data.get("tools") or [],
        "stores": data.get("stores") or [],
    }


def _find(items: list, id_: str) -> Optional[dict]:
    for item in items:
        if item.get("id") == id_:
            return item
    return None


def resolve_skill_id(skill_id: str) -> Optional[dict]:
    """skill:xxx → manifest 项（含 entry/capability/load_criterion）。"""
    m = load_manifest()
    return _find(m["skills"], skill_id)


def resolve_tool_id(tool_id: str) -> Optional[dict]:
    """tool:xxx → manifest 项（含 handler/capability）。"""
    m = load_manifest()
    return _find(m["tools"], tool_id)


def resolve_store_id(store_id: str) -> Optional[dict]:
    """store:xxx（可带 #维度）→ manifest 项（collection 物理名 / intent）。

    `store:log_patterns_collection#日志模式` → 取 `store:` 前缀前的 ID 匹配，
    返回项 + 附维度（调用方用于维度级检索）。
    """
    base = store_id.split("#")[0]
    m = load_manifest()
    item = _find(m["stores"], base)
    if item is None:
        return None
    if "#" in store_id:
        return {**item, "dimension": store_id.split("#", 1)[1]}
    return item


def all_manifest_ids() -> dict:
    """返回 {类型: [id, ...]}，供 lint _check_ref_resolution 双向校验。"""
    m = load_manifest()
    return {
        "skills": [s["id"] for s in m["skills"]],
        "tools": [t["id"] for t in m["tools"]],
        "stores": [st["id"] for st in m["stores"]],
    }


def clear_cache():
    """测试用：清 manifest 缓存（改动 manifest 后重载）。"""
    load_manifest.cache_clear()
