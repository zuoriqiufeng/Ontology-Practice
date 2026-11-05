# -*- coding: utf-8 -*-
"""mechanism_detect.py — 机制发现的数据层（87 号批4 · O-15，从 tools.py 抽出）。

只承载 mechanisms.yaml 的**读与层次归类**（`_mechanisms`/`_leaf_mechanisms`/`_mech_roots`），
供 tools.diagnose_mechanism 与候选召回使用；行为与 tools.py 原实现逐字等价。
判据匹配/候选召回/入口归一等保留在 tools.py（依赖其 resolver/traverser 与 track 机制）。
"""

_MECH_CACHE = None


def _mechanisms() -> dict:
    """读 plugin/mechanisms.yaml（惰性 import yaml，36 号教训；失败退化为 {}）。"""
    global _MECH_CACHE
    if _MECH_CACHE is None:
        try:
            import yaml
            from pathlib import Path
            # 注意 BKN_ROOT 指向**本体目录**（plugin/bkn），不是仓库根 ⇒ 用本文件所在目录
            p = Path(__file__).resolve().parent / "mechanisms.yaml"
            _MECH_CACHE = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception:
            _MECH_CACHE = {}
    return _MECH_CACHE


def _leaf_mechanisms() -> list:
    """**非根类**机制（＝可独立出证的候选池）。

    mechanisms.yaml 的 entry_fields 写明根类「**不独立出证**——它的 confirmed 必须由某个子类的
    hard 证据支撑」。故根类不进候选池：否则它每次都以一个永远 unknown 的候选出现，与自身声明矛盾
    （C-20261013-15）。
    """
    return [m for m in (_mechanisms().get("mechanisms") or [])
            if m.get("id") and m.get("kind") != "根类"]


def _mech_roots() -> list:
    """根类机制 id（不作出证，仅用于在输出里说明它们为何缺席）。"""
    return [m["id"] for m in (_mechanisms().get("mechanisms") or [])
            if m.get("id") and m.get("kind") == "根类"]
