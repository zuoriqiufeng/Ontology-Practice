#!/usr/bin/env python3
"""report_code_rows.py — 码行通道（84 号 T 阶段）观察报告。

只读本地 usage_log（LOG_DIR，默认 logs/），按天汇总：
    码查询数 / 码行命中率 / 码行内容字数 / 输出体积 / 时延

用法：
    python3 scripts/report_code_rows.py                 # 全部日志
    python3 scripts/report_code_rows.py --days 14       # 最近 14 天
    python3 scripts/report_code_rows.py --dir /tmp/logs # 指定日志目录

判读口径（43 号 D17）：
    - 码行命中率 <30% 且查询含码 → 侧车/提取漏了码；
    - 码行内容字数 >600 → 行窗口过大（CODE_ROW_WINDOW）；
    - 码查询 out_chars 中位数 >2.5k → 语义块挤占，考虑 CODE_ROWS_INLINE=1。
"""

from __future__ import annotations

import argparse
import glob
import json
import statistics
import sys
import time
from collections import defaultdict


def _load(dirpath: str, days: int) -> list[dict]:
    cutoff = time.time() - days * 86400 if days > 0 else 0
    rows: list[dict] = []
    for path in sorted(glob.glob(dirpath.rstrip("/") + "/usage_log_*.jsonl")):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("tool") != "search_qdrant" or rec.get("record_type") != "call":
                    continue
                if days > 0 and float(rec.get("ts") or 0) < cutoff:
                    continue
                rows.append(rec)
    return rows


def _digits_in(query: str) -> bool:
    return any(ch.isdigit() for ch in (query or ""))


def summarize(rows: list[dict]) -> dict:
    by_day: dict[str, list[dict]] = defaultdict(list)
    for rec in rows:
        day = time.strftime("%Y-%m-%d", time.localtime(float(rec.get("ts") or 0)))
        by_day[day].append(rec)
    out = {}
    for day, recs in sorted(by_day.items()):
        code_q = [r for r in recs if _digits_in(r.get("query") or "")]
        hit_q = [r for r in code_q if int(r.get("code_rows") or 0) > 0]
        out[day] = {
            "calls": len(recs),
            "code_queries": len(code_q),
            "code_hit_rate": round(100 * len(hit_q) / len(code_q), 1) if code_q else 0.0,
            "code_rows": sum(int(r.get("code_rows") or 0) for r in recs),
            "avg_code_row_chars": (round(statistics.mean([int(r.get("code_row_chars") or 0) for r in hit_q]), 0)
                                   if hit_q else 0),
            "p50_out_chars": (round(statistics.median([int(r.get("out_chars") or 0) for r in recs]), 0)
                              if recs else 0),
            "p50_ms": (round(statistics.median([int(r.get("duration_ms") or 0) for r in recs]), 0)
                       if recs else 0),
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="logs")
    ap.add_argument("--days", type=int, default=0)
    args = ap.parse_args()

    rows = _load(args.dir, args.days)
    if not rows:
        print("没有搜到 search_qdrant 调用记录（目录 %s）" % args.dir)
        return 0
    stats = summarize(rows)
    print("| 日期 | 调用 | 含码查询 | 码行命中率 | 码行数 | 码行平均字数 | 输出中位 | 时延中位 |")
    print("|---|---|---|---|---|---|---|---|")
    for day, s in stats.items():
        print("| %s | %d | %d | %.1f%% | %d | %d | %d | %d ms |" % (
            day, s["calls"], s["code_queries"], s["code_hit_rate"], s["code_rows"],
            s["avg_code_row_chars"], s["p50_out_chars"], s["p50_ms"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
