#!/usr/bin/env python3
"""efficiency_report.py — 效率基线（只读日志，不做任何写入）。

口径（43 号 D16）：只统计真实会话（task_id 以 api- 开头），排除 eval/probe/selftest。
指标：会话数、调用/会话、检索调用/会话、摘要后紧随检索比例、输出 chars、tokens≈chars/2.5、p50/p95。
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import statistics


def _lines(patterns):
    for pat in patterns:
        for f in glob.glob(pat):
            with open(f, encoding="utf-8", errors="ignore") as fh:
                for ln in fh:
                    try:
                        yield json.loads(ln)
                    except Exception:
                        continue


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log-dir", default="logs")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    calls = [d for d in _lines([f"{args.log_dir}/usage_log_*.jsonl"])
             if d.get("record_type") == "call" and str(d.get("task_id") or "").startswith("api-")]
    sessions = collections.defaultdict(list)
    for d in calls:
        sessions[d.get("session_id") or d.get("task_id")].append(d)
    per_session = [len(v) for v in sessions.values()]
    retrieval = [d for d in calls if d.get("tool") in ("search_qdrant", "diagnose_db_link")]
    qdrant = [d for d in calls if d.get("tool") == "search_qdrant"]
    total_chars = sum(int(d.get("out_chars") or 0) for d in calls)
    ret_chars = sum(int(d.get("out_chars") or 0) for d in retrieval)
    qd_chars = sum(int(d.get("out_chars") or 0) for d in qdrant)
    after = 0
    for v in sessions.values():
        tools = [d.get("tool") for d in v]
        for i, t in enumerate(tools):
            if t == "bkn_ask" and i + 1 < len(tools) and tools[i + 1] == "search_qdrant":
                after += 1
    n_ask = sum(1 for d in calls if d.get("tool") == "bkn_ask")
    # 85 号：M10 相邻对分布 / M11 单任务调用次数 / P3 enrichment 采用率
    pairs = collections.Counter()
    for v in sessions.values():
        tools = [d.get("tool") for d in v]
        for a, b in zip(tools, tools[1:]):
            pairs[(a, b)] += 1
    top_pairs = pairs.most_common(5)
    counts = sorted(per_session)
    p90 = counts[min(len(counts) - 1, int(round(0.9 * (len(counts) - 1))))] if counts else 0
    heavy = sum(1 for c in counts if c > 30)
    enrich_calls = sum(1 for d in calls if d.get("enrich"))
    enrich_chars = sum(int(d.get("enrich_chars") or 0) for d in calls)
    durs = [int(d.get("duration_ms") or 0) for d in calls if d.get("duration_ms")]
    rows = [
        ("真实会话数", len(sessions)),
        ("调用总数", len(calls)),
        ("调用/会话（均值）", round(statistics.mean(per_session), 2) if per_session else 0),
        ("检索调用/会话（search_qdrant+db_link）", round(len(retrieval) / max(len(sessions), 1), 2)),
        ("bkn_ask 后紧跟 search_qdrant", "%d/%d" % (after, n_ask)),
        ("输出总 chars", total_chars),
        ("检索输出 chars", "%d（占 %d%%）" % (ret_chars, round(100 * ret_chars / max(total_chars, 1)))),
        ("其中 search_qdrant chars", qd_chars),
        ("tokens 代理（chars/2.5）", round(total_chars / 2.5)),
        ("延迟 p50 / p95（ms）", "%d / %d" % (round(statistics.median(durs)), max(durs)) if durs else "-"),
        ("M10 search_qdrant→search_qdrant", pairs.get(("search_qdrant", "search_qdrant"), 0)),
        ("M10 相邻对 Top5", "；".join("%s→%s %d" % (a, b, n) for (a, b), n in top_pairs) or "-"),
        ("M11 单任务调用 中位/P90/max", "%s / %s / %s" % (statistics.median(counts) if counts else 0, p90, counts[-1] if counts else 0)),
        ("M11 >30 次任务数", heavy),
        ("P3 enrichment（次数/字数）", "%d / %d" % (enrich_calls, enrich_chars)),
    ]
    lines = ["# 效率基线（真实会话 %d 个）" % len(sessions), "", "| 指标 | 值 |", "|---|---|"]
    lines += ["| %s | %s |" % r for r in rows]
    text = chr(10).join(lines) + chr(10)
    if args.out:
        open(args.out, "w", encoding="utf-8").write(text)
        print("报告 →", args.out)
    print(text)


if __name__ == "__main__":
    main()
