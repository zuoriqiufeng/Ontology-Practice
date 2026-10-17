#!/usr/bin/env python3
"""usage_stats.py — 聚合 usage_log.jsonl 输出使用分布 (P3-1)

用法:
  python3 plugin/scripts/usage_stats.py                          # 全量
  python3 plugin/scripts/usage_stats.py --tool search_qdrant     # 只看指定 tool
  python3 plugin/scripts/usage_stats.py --real-only              # 只统计真实会话流量(task_id 非空)
  python3 plugin/scripts/usage_stats.py --since 2026-09-29       # 只看该时刻之后的记录
  python3 plugin/scripts/usage_stats.py --since "2026-09-29 12:00"

过滤参数说明（43 号文档 §4 数据卫生）:
- --real-only: Hermes 真实会话调用必带 task_id；压测/pytest/裸脚本不带。观测期取数应默认加此参数。
- --since/--until: 时间窗过滤（本地时区），用于切分观测期、剔除历史污染段。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

# 2A: 与运行时同源——日志路径从 plugin/config.py 读取（env LOG_DIR 可覆盖）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import resolve_log_path  # noqa: E402
from log_rotate import load_jsonl_entries  # noqa: E402

USAGE_LOG = resolve_log_path("usage_log.jsonl")  # 逻辑基名（实际文件含日期）

# 44 号 §6 批 3：通用字段完整率口径——跨类别都有意义的最小字段集
COMMON_FIELDS = ("args", "confidence", "out_chars", "duration_ms", "task_id")

#: 记录类别（写入点自己声明）；缺 record_type 的历史记录统一归 legacy，只展示不判劣化
RECORD_TYPES = ("call", "call_detail", "process", "legacy")


def _parse_ts(s: str) -> float:
    """'2026-09-29' 或 '2026-09-29 12:00' → epoch 秒（本地时区）。"""
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).timestamp()
        except ValueError:
            continue
    raise SystemExit(f"无法解析时间: {s}（格式: 2026-09-29 或 '2026-09-29 12:00'）")


def _load_entries(path: Path) -> list[dict]:
    """读全部数据文件（新旧命名兼容：日期文件 + 旧命名分片），按 ts 升序合并。"""
    entries = load_jsonl_entries(path)
    entries.sort(key=lambda e: e.get("ts", 0))
    return entries


def main(argv=None):
    ap = argparse.ArgumentParser(description="Tool 使用统计")
    ap.add_argument("--tool", help="只看指定 tool")
    ap.add_argument("--real-only", action="store_true",
                    help="只统计 task_id 非空的记录（Hermes 真实会话；压测/测试流量无 task_id）")
    ap.add_argument("--since", help="只统计该时刻之后（格式: 2026-09-29 或 '2026-09-29 12:00'）")
    ap.add_argument("--until", help="只统计该时刻之前（格式同 --since）")
    args = ap.parse_args(argv)

    entries = _load_entries(USAGE_LOG)

    if args.since:
        cut = _parse_ts(args.since)
        entries = [e for e in entries if e.get("ts", 0) > cut]
    if args.until:
        cut = _parse_ts(args.until)
        entries = [e for e in entries if e.get("ts", 0) <= cut]
    if args.real_only:
        n_all = len(entries)
        entries = [e for e in entries if e.get("task_id")]
        print(f"--real-only: {n_all} → {len(entries)} 条（task_id 非空 = 真实会话流量）\n")
    if args.tool:
        entries = [e for e in entries if e.get("tool") == args.tool]

    if not entries:
        print("过滤后无记录（检查过滤条件或尚无使用记录）")
        return 0

    ts_list = [e.get("ts") for e in entries if e.get("ts")]
    span = ""
    if ts_list:
        span = f"（{datetime.fromtimestamp(min(ts_list)):%Y-%m-%d %H:%M} ~ " \
               f"{datetime.fromtimestamp(max(ts_list)):%Y-%m-%d %H:%M}）"
    print(f"总记录: {len(entries)} {span}\n")

    by_tool = Counter(e.get("tool") for e in entries)
    print("== tool 调用分布 ==")
    for t, c in by_tool.most_common():
        print(f"  {t}: {c}")

    # chunk_mode 分布（search_qdrant 专用）
    cm = Counter(e.get("chunk_mode") for e in entries if "chunk_mode" in e)
    if cm:
        print("\n== chunk_mode 分布 (search_qdrant) ==")
        for m, c in cm.most_common():
            print(f"  {m}: {c}")

    # confidence 分布
    conf = Counter(e.get("confidence") for e in entries if "confidence" in e)
    if conf:
        print("\n== confidence 分布 ==")
        for k, c in conf.most_common():
            print(f"  {k}: {c}")

    # 44 号 §6 批 3：通用字段完整率（按 record_type 分组）——新增段，不改既有段语义
    _print_field_coverage(entries)

    # 命中率
    hit_entries = [e for e in entries if "hits" in e]
    if hit_entries:
        zero = sum(1 for e in hit_entries if e.get("hits") == 0)
        print(f"\n== search_qdrant 命中 ==\n  有结果: {len(hit_entries)-zero}, 零命中: {zero}")
        # 21 号 P2 零命中治理取数：零命中 query 聚类
        zero_qs = Counter(e.get("query", "") for e in hit_entries
                          if e.get("hits") == 0 and e.get("query"))
        if zero_qs:
            print("  零命中 query top10:")
            for q, c in zero_qs.most_common(10):
                print(f"    [{c:3d}] {q[:70]}")

    # 2A: 耗时 / 输出体积分布
    timed = [e for e in entries if "duration_ms" in e]
    if timed:
        durs = sorted(e["duration_ms"] for e in timed)
        outs = sorted(e.get("out_chars", 0) for e in timed)

        def _pct(vals, p):
            return vals[min(len(vals) - 1, int(len(vals) * p))] if vals else 0

        sample_note = "" if len(timed) >= 30 else "  ⚠️ 样本 <30，分位数仅供参考"
        print(f"\n== 耗时 (n={len(timed)}){sample_note} ==")
        print(f"  p50={_pct(durs, 0.5)}ms  p90={_pct(durs, 0.9)}ms  p99={_pct(durs, 0.99)}ms  "
              f"max={durs[-1]}ms  mean={sum(durs)//len(durs)}ms")
        print("== 输出体积 ==")
        print(f"  out_chars p50={_pct(outs, 0.5)}  p90={_pct(outs, 0.9)}  max={outs[-1]}  "
              f"总 token 估算={sum(e.get('out_tokens_est', 0) for e in timed)}")

    # 真实会话聚合（21 号 P2 观测取数）
    sessions = Counter(e["task_id"] for e in entries if e.get("task_id"))
    if sessions:
        print(f"\n== 会话数 (task_id 去重): {len(sessions)} ==")
        for tid, c in sessions.most_common(5):
            print(f"  {tid[:40]}: {c} 次调用")

    _print_assembly_coverage(entries)
    return 0


def _record_type(entry: dict) -> str:
    """条目的记录类别；缺失/未知一律 legacy（历史记录没有这个字段）。"""
    rt = entry.get("record_type")
    return rt if rt in ("call", "call_detail", "process") else "legacy"


def field_coverage(entries: list[dict]) -> list[dict]:
    """按 record_type 分组统计通用字段**出现率**（键存在即算出现）。

    返回 4 行（call / call_detail / process / legacy），每行:
    {"record_type": str, "n": int, "present": {字段: 条数}, "rate": {字段: 百分比}}。

    为什么必须分组（44 号 §6 批 3 根因）：usage_log 有 6 个写入点、字段集各不相同，
    「args 35% / confidence 47%」是三类**不同性质**的记录混在一起算的结果——
    call 是工具调用级（要求 args/confidence 齐全）、call_detail 是批量检索的查询明细
    （天性没有 confidence）、process 是进程级事件（既无 args 也无 confidence）。
    分开算，call 行掉下 100% 才是真漏记。
    """
    grouped = {rt: [] for rt in RECORD_TYPES}
    for e in entries:
        grouped[_record_type(e)].append(e)
    rows = []
    for rt in RECORD_TYPES:
        bucket = grouped[rt]
        n = len(bucket)
        present = {f: sum(1 for e in bucket if f in e) for f in COMMON_FIELDS}
        rate = {f: (present[f] * 100.0 / n if n else 0.0) for f in COMMON_FIELDS}
        rows.append({"record_type": rt, "n": n, "present": present, "rate": rate})
    return rows


def _print_field_coverage(entries: list[dict]) -> None:
    """字段完整率段（44 号 §6 批 3）。

    - **只有 call 行要求 100%**：它的 args/confidence 是真漏记的判据，缺就打 ⚠；
    - call_detail / process / legacy **只展示不判劣化**（天性没有这些字段）；
    - 末尾一行给出「调用级记录 N 条，其中 args 缺失 M 条」——一眼看出还有没有真漏记。
    """
    rows = field_coverage(entries)
    if not any(r["n"] for r in rows):
        return
    fields_s = "、".join(COMMON_FIELDS)
    print("\n== 字段完整率（按 record_type 分组）==")
    print(f"  （字段={fields_s}；缺失 record_type 的旧记录归 legacy；"
          "仅 call 行要求 100%，其余行只展示不判劣化）")
    for r in rows:
        if not r["n"]:
            continue
        cells = "  ".join(f"{f}={r['rate'][f]:.0f}%" for f in COMMON_FIELDS)
        mark = ""
        if r["record_type"] == "call":
            missing = [f for f in COMMON_FIELDS if r["present"][f] < r["n"]]
            mark = ("  ⚠ 缺: " + ",".join(missing)) if missing else "  ✅ 100%"
        print(f"  {r['record_type']:<11} n={r['n']:<5} {cells}{mark}")
    call = next(r for r in rows if r["record_type"] == "call")
    print(f"  调用级记录 {call['n']} 条，其中 args 缺失 {call['n'] - call['present']['args']} 条")


def _print_assembly_coverage(entries: list[dict]) -> None:
    """BKN 约束覆盖率（22 号批 4-1 的 `risk_guard_assembly` 事件的消费面）。

    口径：覆盖率 = 1 − fallback 占比。两个分量都来自同一事件的字段：
    `rules_assembled`（由 BKN 图边装配出的规则数）与 `fallback_ids`（最终仍来自内置兜底的 rule_id 列表）。
    - 每进程一条事件；按 **ts 最近的最后一条**为准（进程重启后覆盖）；
    - **无事件时显式写「无数据」**（不打印 0——0 是「装出 0 条规则」的合法值，两者不可混）。
    """
    asm = [e for e in entries if e.get("tool") == "risk_guard_assembly"]
    print("\n== BKN 约束覆盖率（risk_guard 装配事件）==")
    if not asm:
        print("  ⚠ 无数据：尚无 risk_guard_assembly 事件（该事件在 check_action_risk 首次装配时写，"
              "每进程一条；服务重启后才有）")
        return
    last = max(asm, key=lambda e: e.get("ts", 0))
    assembled = int(last.get("rules_assembled") or 0)
    fallback = list(last.get("fallback_ids") or [])
    total = assembled + len(fallback)
    cov = (assembled / total) if total else None
    when = datetime.fromtimestamp(last.get("ts", 0)).strftime("%Y-%m-%d %H:%M")
    cov_s = f"{cov:.1%}" if cov is not None else "n/a（规则总数为 0）"
    print(f"  覆盖率 {cov_s}｜BKN 装配 {assembled} 条 + 兜底 {len(fallback)} 条"
          f"（来源 {last.get('assoc_source')}，degraded={last.get('degraded')}，{when}）")
    if fallback:
        print(f"  仍来自兜底: {', '.join(fallback)}")
    if last.get("error"):
        print(f"  ⚠ 装配异常: {last['error']}")


if __name__ == "__main__":
    raise SystemExit(main())
