#!/usr/bin/env python3
"""round_trip_report.py — 轮次成本只读报告（85 号 M12–M14）。

数据源（全部只读）：
  ~/.hermes/state.db
    messages.role/timestamp        → 拆轮次时间：tool→assistant = 模型决策；assistant→tool = 工具执行
    session_model_usage            → 真实 token（input/output/cache_read/reasoning），按 task='' 取主对话
  logs/usage_log_*.jsonl           → 工具耗时 duration_ms、out_chars、task_id/session_id

指标：
  M12 模型决策耗时中位/p95（秒）
  M13 每轮 token：input / output / cache_read / reasoning（按会话聚合 ÷ assistant 轮数）
  M14 工具耗时占比 = 工具总耗时 ÷（工具总耗时 + 决策总耗时）

关联键：usage_log.task_id == state.db.messages.session_id（形如 api-<hex>），已实测对齐。

用法：
  python3 scripts/round_trip_report.py                  # 默认近 7 天、logs/、~/.hermes/state.db
  python3 scripts/round_trip_report.py --days 0         # 全部历史
  python3 scripts/round_trip_report.py --json           # 机器可读
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sqlite3
import statistics
import time


def _calls(log_dir: str, days: int) -> dict:
    """task_id → [usage_log call...]；只取真实会话（api- 前缀）。"""
    cutoff = time.time() - days * 86400 if days > 0 else 0
    out: dict[str, list[dict]] = {}
    for path in sorted(glob.glob(os.path.join(log_dir, "usage_log_*.jsonl"))):
        with open(path, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("record_type") != "call":
                    continue
                task = str(rec.get("task_id") or "")
                if not task.startswith("api-"):
                    continue
                if days > 0 and float(rec.get("ts") or 0) < cutoff:
                    continue
                out.setdefault(task, []).append(rec)
    return out


def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))]


def _session_rounds(con: sqlite3.Connection, sid: str):
    """返回 (轮次列表[每用户轮 assistant 数], 决策间隔秒列表, 工具间隔秒列表)。"""
    rows = list(con.execute(
        "select role, timestamp from messages where session_id=? order by timestamp", (sid,)))
    turns: list[int] = []
    decide: list[float] = []
    tool_gap: list[float] = []
    calls = 0
    for i, (role, ts) in enumerate(rows):
        if role == "user":
            if calls:
                turns.append(calls)
            calls = 0
            continue
        if role == "assistant":
            calls += 1
            if i and rows[i - 1][0] == "tool":
                decide.append(float(ts) - float(rows[i - 1][1]))
        elif role == "tool" and i and rows[i - 1][0] == "assistant":
            tool_gap.append(float(ts) - float(rows[i - 1][1]))
    if calls:
        turns.append(calls)
    return turns, decide, tool_gap


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log-dir", default="logs")
    ap.add_argument("--db", default=os.path.expanduser("~/.hermes/state.db"))
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    by_task = _calls(args.log_dir, args.days)
    if not by_task:
        print("没有找到真实会话（task_id 以 api- 开头的 usage_log 调用）")
        return 0
    if not os.path.exists(args.db):
        print("找不到 Hermes state.db（%s），跳过轮次/ token 部分" % args.db)
        return 0
    con = sqlite3.connect("file:%s?mode=ro" % args.db, uri=True)

    rounds_per_turn: list[int] = []
    decide: list[float] = []
    tool_gap: list[float] = []
    tok = {"calls": 0, "input": 0, "output": 0, "cache_read": 0, "reasoning": 0}
    tool_ms = 0
    out_chars = 0
    matched = 0
    for sid, calls in by_task.items():
        matched += 1
        for rec in calls:
            tool_ms += int(rec.get("duration_ms") or 0)
            out_chars += int(rec.get("out_chars") or 0)
        turns, dec, tg = _session_rounds(con, sid)
        rounds_per_turn.extend(turns)
        decide.extend(dec)
        tool_gap.extend(tg)
        row = list(con.execute(
            "select coalesce(sum(api_call_count),0), coalesce(sum(input_tokens),0),"
            " coalesce(sum(output_tokens),0), coalesce(sum(cache_read_tokens),0),"
            " coalesce(sum(reasoning_tokens),0) from session_model_usage"
            " where session_id=? and coalesce(task,'')=''", (sid,)))[0]
        tok["calls"] += int(row[0] or 0)
        tok["input"] += int(row[1] or 0)
        tok["output"] += int(row[2] or 0)
        tok["cache_read"] += int(row[3] or 0)
        tok["reasoning"] += int(row[4] or 0)

    rounds = max(len(decide), tok["calls"], 1)
    total_tool_s = tool_ms / 1000.0
    total_decide_s = sum(decide)
    m14 = (100.0 * total_tool_s / (total_tool_s + total_decide_s)
           if (total_tool_s + total_decide_s) else 0.0)
    report = {
        "sessions": matched,
        "turns": len(rounds_per_turn),
        "rounds": len(decide),
        "rounds_per_turn_median": statistics.median(rounds_per_turn) if rounds_per_turn else 0,
        "rounds_per_turn_p90": _pct([float(x) for x in rounds_per_turn], 0.9),
        "rounds_per_turn_max": max(rounds_per_turn) if rounds_per_turn else 0,
        "m12_decide_median_s": round(statistics.median(decide), 2) if decide else 0,
        "m12_decide_p95_s": round(_pct(decide, 0.95), 2),
        "m13_input_per_round": round(tok["input"] / rounds),
        "m13_output_per_round": round(tok["output"] / rounds),
        "m13_cache_read_per_round": round(tok["cache_read"] / rounds),
        "m13_reasoning_per_round": round(tok["reasoning"] / rounds),
        "m14_tool_share_pct": round(m14, 1),
        "tool_total_s": round(total_tool_s, 1),
        "decide_total_s": round(total_decide_s, 1),
        "out_chars": out_chars,
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    print("# 轮次成本报告（近 %s 天，真实会话 %d 个 / %d 轮）" % (args.days or "全部", matched, report["rounds"]))
    print("")
    print("| 指标 | 值 |")
    print("|---|---|")
    print("| 用户轮数 | %d |" % report["turns"])
    print("| 每用户轮 API 调用 中位 / P90 / max | %s / %s / %s |" % (
        report["rounds_per_turn_median"], report["rounds_per_turn_p90"], report["rounds_per_turn_max"]))
    print("| **M12 模型决策耗时 中位 / p95** | **%ss / %ss** |" % (
        report["m12_decide_median_s"], report["m12_decide_p95_s"]))
    print("| **M13 每轮 token：input / output / cache_read / reasoning** | %d / %d / %d / %d |" % (
        report["m13_input_per_round"], report["m13_output_per_round"],
        report["m13_cache_read_per_round"], report["m13_reasoning_per_round"]))
    print("| **M14 工具耗时占比** | **%s%%**（工具 %ss / 决策 %ss） |" % (
        report["m14_tool_share_pct"], report["tool_total_s"], report["decide_total_s"]))
    print("| 工具输出 chars | %d |" % report["out_chars"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
