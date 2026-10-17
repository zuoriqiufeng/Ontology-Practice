#!/usr/bin/env python3
"""field_length_probe.py — 字段长度与保护状态探针（候选门禁③的"可复现"证据工具）

回答一个具体问题：**哪些字段的值超过 `_fmt_scalar` 的 80 字符截断线，且未受
`_FULL_CONTENT_KEYS` 保护**——即"会被静默截断"的候选清单。

用途：
- 候选门禁③（证据）需要"可复现"——本脚本就是那条可复现的验证；
- 任何触及 ContextLoader / 白名单 / Tool 输出结构的改动，改前改后各跑一次。

用法:
  python3 plugin/scripts/field_length_probe.py
  python3 plugin/scripts/field_length_probe.py --threshold 80 --json

依据: doc/optimize/22-bkn-lifecycle-gate.md §3 批 3-2；plugin/CLAUDE.md v3.10 经验 #3
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_DIR.parent))

# 数据卫生：本脚本只调 resolver（不走 _wrap），但仍隔离日志路径以防万一
os.environ.setdefault("LOG_DIR", tempfile.mkdtemp(prefix="i2bkn_probe_logs_"))

from plugin.context_loader import ToonFormatter  # noqa: E402
from plugin.resolver import BKNResolver  # noqa: E402

DEFAULT_THRESHOLD = 80


def walk_long(obj, threshold: int, path: str = ""):
    """递归产出 (key_path, 长度, 值) —— 只报超过阈值的字符串。"""
    if isinstance(obj, str):
        if len(obj) > threshold:
            yield path, len(obj), obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk_long(v, threshold, f"{path}.{k}" if path else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk_long(v, threshold, f"{path}[{i}]")


def _protected(path: str) -> bool:
    parts = [p.split("[")[0] for p in path.split(".")]
    return ToonFormatter._is_protected(parts[-1], tuple(parts[:-1]))


def probes(resolver: BKNResolver) -> dict:
    """代表性调用（覆盖 REQUIRED_FIELDS 涉及的各 Tool 原始返回）。"""
    return {
        "check_compatibility(oracle→gaussdb)": lambda: resolver.check_compatibility("oracle", "gaussdb"),
        "design_solution(mysql→oracle)": lambda: resolver.match_scenario("mysql", "oracle"),
        "diagnose_error(-4073)": lambda: resolver.get_risk("-4073"),
        "query_product(overview)": lambda: resolver.query_product(),
        "explain_architecture(all)": lambda: resolver.query_architecture("all"),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="字段长度与保护状态探针")
    ap.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD,
                    help=f"截断阈值（默认 {DEFAULT_THRESHOLD}，与 _fmt_scalar 一致）")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    ns = ap.parse_args(argv)

    resolver = BKNResolver()
    findings = []
    for name, fn in probes(resolver).items():
        try:
            result = fn()
        except Exception as exc:  # 单点失败不拖垮探测
            findings.append({"probe": name, "error": str(exc)})
            continue
        for path, length, value in walk_long(result, ns.threshold):
            findings.append({
                "probe": name, "key_path": path, "length": length,
                "protected": _protected(path), "preview": value[:70],
            })

    if ns.json:
        print(json.dumps({"threshold": ns.threshold, "findings": findings},
                         ensure_ascii=False, indent=1))
        return 0

    print(f"阈値 {ns.threshold} 字符（_fmt_scalar 截断线）\n")
    risky = [f for f in findings if not f.get("error") and not f["protected"]]
    safe = [f for f in findings if f.get("error") or f["protected"]]
    if risky:
        print(f"⚠ 会被截断（未受白名单保护）{len(risky)} 条：")
        for f in risky:
            print(f"  [{f['probe']}] {f['key_path']} = {f['length']} 字符")
            print(f"      {f['preview']!r}")
    else:
        print("✅ 无「超阈值且未受保护」的字段")
    if safe:
        print(f"\n已受保护（或跳过）{len(safe)} 条：")
        for f in safe:
            if f.get("error"):
                print(f"  [{f['probe']}] 探针失败：{f['error']}")
            else:
                print(f"  [{f['probe']}] {f['key_path']} = {f['length']} 字符（受保护）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
