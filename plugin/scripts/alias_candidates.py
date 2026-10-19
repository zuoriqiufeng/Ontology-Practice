#!/usr/bin/env python3
"""alias_candidates.py — 从日志挖「别名候选」（别名机制 v2 的反馈闭环；43 号 §7 D11）。

只读：扫 trajectory 的 `mention_resolve`（path=unknown）与 `ontology_use`（dropped），
以及 gap_log 的 params，归一聚类后出 Markdown 报告——**不写任何数据**。
人工审后把确认的说法写进 `plugin/aliases.yaml`（带 provenance）。

用法:
    python3 plugin/scripts/alias_candidates.py [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--top 30]
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOGS = ROOT / "logs"

#: 可生成的码形态：命中即「L1 已覆盖」，不应当作别名候选
_CODE_FORMS = (
    re.compile(r"^-?[0-9]{3,6}$"),
    re.compile(r"^错误[ ]*-?[0-9]{3,6}$"),
    re.compile(r"^(?:error|err)[ ]*-?[0-9]{3,6}$", re.IGNORECASE),
    re.compile(r"^[A-Za-z]{2,6}-?[0-9]{2,6}$"),
)
_DROP_CHARS = " ,，。;；:：!！?？" + chr(39) + chr(34) + "()（）[]【】<>《》" + chr(96) + chr(9) + chr(10) + chr(13)
_DROP = set(_DROP_CHARS)


def _norm(text: str) -> str:
    s = str(text or "").strip().lower()
    return "".join(ch for ch in s if ch not in _DROP)[:80]


def _files(prefix: str, since: str, until: str) -> list[Path]:
    out = []
    for p in sorted(LOGS.glob(f"{prefix}_*.jsonl")):
        day = p.stem.split("_")[-1]
        if since and day < since:
            continue
        if until and day > until:
            continue
        out.append(p)
    traj = LOGS / "trajectories"
    if traj.is_dir():
        for p in sorted(traj.glob(f"{prefix}_*.jsonl")):
            day = p.stem.split("_")[-1]
            if since and day < since:
                continue
            if until and day > until:
                continue
            out.append(p)
    return out


def _scan(since: str, until: str) -> tuple[Counter, Counter]:
    """→ (未命中提及计数, 原因计数)。只读。"""
    mentions: Counter = Counter()
    reasons: Counter = Counter()
    paths = _files("trajectory", since, until) + _files("usage_log", since, until) \
        + _files("gap_log", since, until)
    for p in paths:
        try:
            lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for ln in lines:
            ln = ln.strip()
            if not ln:
                continue
            try:
                d = json.loads(ln)
            except Exception:  # noqa: BLE001 —— 坏行跳过
                continue
            if d.get("event") == "mention_resolve" and d.get("path") == "unknown":
                k = _norm(d.get("mention"))
                if k:
                    mentions[k] += 1
                    reasons["mention_unknown"] += 1
            dropped = d.get("dropped")
            for item in (dropped if isinstance(dropped, list) else []):
                if not isinstance(item, dict):
                    continue
                k = _norm(item.get("id"))
                if k:
                    mentions[k] += 1
                    reasons[str(item.get("reason") or "")] += 1
            params = d.get("params")
            if isinstance(params, dict):
                for v in params.values():
                    if not isinstance(v, str):
                        continue
                    raw = v.strip()
                    # 跳过字段名/枚举类值（gap_log 的 params 里大量是提参，不是「说法」）
                    if re.fullmatch(r"[a-z_]{1,24}", raw) or raw.lower() in ("all", "none", "unknown"):
                        continue
                    k = _norm(raw)
                    if k and 2 <= len(k) <= 40:
                        mentions[k] += 1
    return mentions, reasons


def _kind(key: str) -> str:
    if any(p.match(key) for p in _CODE_FORMS):
        return "可生成（L1 已覆盖，不入表）"
    if any(chr(0x4e00) <= ch <= chr(0x9fff) for ch in key):
        return "口语（候选：症状/维度）"
    return "待定"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="别名候选报告（只读）")
    ap.add_argument("--since", default="", help="起始日期 YYYY-MM-DD")
    ap.add_argument("--until", default="", help="结束日期 YYYY-MM-DD")
    ap.add_argument("--top", type=int, default=30)
    a = ap.parse_args(argv)
    mentions, reasons = _scan(a.since, a.until)
    total = sum(mentions.values())
    print(f"# 别名候选报告（{a.since or '全部'} ~ {a.until or 'now'}）")
    print()
    print(f"未命中条目 {total} 条 / 去重 {len(mentions)} 个；原因分布：{dict(reasons)}")
    print()
    print("| # | 说法 | 次数 | 判定 |")
    print("|---|---|---|---|")
    for i, (k, n) in enumerate(mentions.most_common(a.top), 1):
        print(f"| {i} | {k} | {n} | {_kind(k)} |")
    print()
    print("> 处置：口语候选 → 人工确认 → 写入 `plugin/aliases.yaml`（含 provenance）；")
    print("> 可生成形态 → 已由 L1 覆盖，不写表；`code_unmapped` → 补语料/登记，不写别名。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
