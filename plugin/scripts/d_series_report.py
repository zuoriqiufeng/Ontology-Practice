#!/usr/bin/env python3
"""d_series_report.py — 43 号 §7「D1–D9 观察项判定表」的出数脚本（22 号批 5 的脚手架）

口径（43 号 §7 原文）：**全部以真实会话（`task_id` 非空）计**；数据满足判据即触发动作，
不满足则继续观测并记录本期数字。本脚本只出「命中 / 未命中 / **数据不足**」三态 + 本期数字，
**不做任何动作、不改任何配置**（立项属 22 号批 5 的人工作业）。

数据不足的判定（避免用薄样本硬凑结论）：
- 计数/比率类（D1/D2）：观测跨度 <7 天时**不给"次/周"结论**（标数据不足）；
- 分位/趋势类（D3 时长部分/D5/D6/D7/D8/D9）：相关样本 <30（43 号 §5 口径）标数据不足。

用法:
  python3 plugin/scripts/d_series_report.py                    # 全量真实会话
  python3 plugin/scripts/d_series_report.py --since 2026-10-12 --until 2026-10-19
  python3 plugin/scripts/d_series_report.py --all-traffic      # 连压测/测试流量一起算（默认不算）
  python3 plugin/scripts/d_series_report.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from usage_stats import USAGE_LOG, _load_entries, _parse_ts  # noqa: E402

MIN_N = 30            # 分位数/趋势类的最小样本（43 号 §5）
MIN_SPAN_DAYS = 7.0   # 「次/周」类的最小观测跨度

HIT, MISS, INSUFFICIENT = "命中", "未命中", "数据不足"


def _pct(vals: list, p: float):
    if not vals:
        return None
    vals = sorted(vals)
    return vals[min(len(vals) - 1, int(len(vals) * p))]


def _span_days(entries: list) -> float:
    ts = [e.get("ts") for e in entries if e.get("ts")]
    return (max(ts) - min(ts)) / 86400.0 if len(ts) >= 2 else 0.0


def _per_week(count: int, span_days: float):
    return None if span_days < MIN_SPAN_DAYS else round(count / span_days * 7, 2)


def _by_tool(entries: list, tool: str) -> list:
    return [e for e in entries if e.get("tool") == tool]


def _args_pairs(entries: list, keys: tuple) -> set:
    out = set()
    for e in entries:
        a = e.get("args") or {}
        pair = tuple(str(a.get(k, "")) for k in keys)
        if any(pair):
            out.add(pair)
    return out


def evaluate(entries: list) -> list[dict]:
    """返回九项结果：{id, name, verdict, metric, action}。"""
    res: list[dict] = []
    span = _span_days(entries)
    n = len(entries)

    def add(did, name, verdict, metric, action):
        res.append({"id": did, "name": name, "verdict": verdict, "metric": metric, "action": action})

    # D1 · Tool 合并候选：check_compatibility
    cc = _by_tool(entries, "check_compatibility")
    ds = _by_tool(entries, "design_solution")
    rate = _per_week(len(cc), span)
    cc_pairs, ds_pairs = _args_pairs(cc, ("source", "target")), _args_pairs(ds, ("source", "target"))
    cov = (len(cc_pairs & ds_pairs) / len(cc_pairs)) if cc_pairs else None
    if rate is None or cov is None:
        add("D1", "check_compatibility 合并", INSUFFICIENT,
            f"真实调用 {len(cc)} 次｜跨度 {span:.1f} 天｜覆盖 {'n/a' if cov is None else f'{cov:.0%}'}",
            "合并进 design_solution（21 号 P2）")
    else:
        hit = rate < 10 and cov >= 0.8
        add("D1", "check_compatibility 合并", HIT if hit else MISS,
            f"{rate}/周（<10）｜(source,target) 覆盖 {cov:.0%}（≥80%）", "合并进 design_solution（21 号 P2）")

    # D2 · resolve_relation 直连使用
    rr = _by_tool(entries, "resolve_relation")
    rate = _per_week(len(rr), span)
    if rate is None:
        add("D2", "resolve_relation 直连", INSUFFICIENT, f"真实调用 {len(rr)} 次｜跨度 {span:.1f} 天",
            "schema 收敛为内部出口（能力保留）")
    else:
        add("D2", "resolve_relation 直连", HIT if rate < 5 else MISS, f"{rate}/周（<5）",
            "schema 收敛为内部出口（能力保留）")

    # D3 · get_prerequisites ↔ resolve_operation 的 operation 集合重合
    gp = {str((e.get("args") or {}).get("operation", "")) for e in _by_tool(entries, "get_prerequisites")}
    ro = {str((e.get("args") or {}).get("operation", "")) for e in _by_tool(entries, "resolve_operation")}
    gp.discard(""), ro.discard("")
    if not gp or not ro:
        add("D3", "get_prerequisites ↔ resolve_operation", INSUFFICIENT,
            f"operation 集合 gp={len(gp)} / ro={len(ro)}（需两侧都有）", "合并为单出口（保留双 schema 别名期）")
    else:
        ov = len(gp & ro) / len(gp)
        add("D3", "get_prerequisites ↔ resolve_operation", HIT if ov > 0.7 else MISS,
            f"重合度 {ov:.0%}（>70%）｜时长趋势：未评估（需更长窗口人工复核）",
            "合并为单出口（保留双 schema 别名期）")

    # D4 · 零命中 query 聚类
    sq = _by_tool(entries, "search_qdrant")
    zero = [e for e in sq if e.get("hits") == 0 and e.get("mode") == "single" and e.get("query")]
    if not zero:
        add("D4", "零命中治理", INSUFFICIENT if not sq else MISS,
            f"零命中 {len(zero)} 条（search_qdrant 单查询 {len(sq)} 次）", "补语料 / xlsx chunking")
    else:
        from collections import Counter
        top10 = sum(c for _, c in Counter(e["query"] for e in zero).most_common(10))
        cov = top10 / len(zero)
        add("D4", "零命中治理", HIT if cov >= 0.5 else MISS,
            f"零命中 {len(zero)} 条｜top10 query 覆盖 {cov:.0%}（≥50%）", "补语料 / xlsx chunking")

    # D5 · 输出预算默认值
    batch_tok = [e.get("out_tokens_est", 0) for e in sq if e.get("mode") == "parallel_batch"]
    per_tool_p99 = {}
    for t in sorted({e.get("tool") for e in entries}):
        vals = [e.get("out_chars") for e in _by_tool(entries, t) if isinstance(e.get("out_chars"), int)]
        if len(vals) >= MIN_N:
            per_tool_p99[t] = _pct(vals, 0.99)
    if len(batch_tok) < MIN_N and not per_tool_p99:
        add("D5", "输出预算默认值", INSUFFICIENT,
            f"批量样本 {len(batch_tok)}（<{MIN_N}）｜无单 Tool 达 {MIN_N} 样本", "落 output_max_chars 默认值")
    else:
        p90 = _pct(batch_tok, 0.9) if len(batch_tok) >= MIN_N else None
        over = [f"{t} p99={v}" for t, v in per_tool_p99.items() if v and v > 6000]
        hit = (p90 is not None and p90 > 8000) or bool(over)
        add("D5", "输出预算默认值", HIT if hit else MISS,
            f"批量 out_tokens_est p90={p90}（>8k）｜单 Tool out_chars p99 超 6k：{over or '无'}",
            "落 output_max_chars 默认值")

    # D6 · 查询向量缓存
    durs = [e.get("duration_ms") for e in sq if isinstance(e.get("duration_ms"), int)]
    from collections import Counter
    qs = Counter(e.get("query") for e in sq if e.get("query"))
    dup = sum(c for c in qs.values() if c >= 2) / max(sum(qs.values()), 1)
    if len(durs) < MIN_N:
        add("D6", "查询向量缓存", INSUFFICIENT, f"search_qdrant 计时样本 {len(durs)}（<{MIN_N}）",
            "实施 LRU 向量缓存（21 号 P1）")
    else:
        p50 = _pct(durs, 0.5)
        add("D6", "查询向量缓存", HIT if (p50 > 300 and dup > 0.3) else MISS,
            f"p50={p50}ms（>300）｜重复 query 率 {dup:.0%}（>30%）", "实施 LRU 向量缓存（21 号 P1）")

    # D7 · 检索合并（resolve_operation / diagnose_db_link 的 p50 vs 单次 search）
    def _p50(tool, only_single=False):
        vals = [e.get("duration_ms") for e in _by_tool(entries, tool)
                if isinstance(e.get("duration_ms"), int)]
        return _pct(vals, 0.5) if len(vals) >= MIN_N else None
    base = _pct([e.get("duration_ms") for e in sq
                 if e.get("mode") == "single" and isinstance(e.get("duration_ms"), int)], 0.5) \
        if len([e for e in sq if e.get("mode") == "single"]) >= MIN_N else None
    ro_p50, dl_p50 = _p50("resolve_operation"), _p50("diagnose_db_link")
    if base is None or (ro_p50 is None and dl_p50 is None):
        add("D7", "检索合并", INSUFFICIENT,
            f"单次 search p50={base}｜resolve_operation p50={ro_p50}｜diagnose_db_link p50={dl_p50}"
            f"（各需 ≥{MIN_N} 样本）", "内部多次检索合并为批量入口")
    else:
        worst = max(x for x in (ro_p50, dl_p50) if x is not None)
        add("D7", "检索合并", HIT if worst > 2 * base else MISS,
            f"max(p50)={worst}ms vs 单次 search {base}ms（>2×）", "内部多次检索合并为批量入口")

    # D8 · 冷启动预热（每 task_id 首条 vs 后续 p50）
    per_task: dict[str, list] = {}
    for e in entries:
        if e.get("task_id") and isinstance(e.get("duration_ms"), int):
            per_task.setdefault(e["task_id"], []).append(e)
    firsts, rests = [], []
    for tid, es in per_task.items():
        es = sorted(es, key=lambda x: x.get("ts", 0))
        if es:
            firsts.append(es[0]["duration_ms"])
            rests.extend(x["duration_ms"] for x in es[1:])
    if len(firsts) < MIN_N:
        add("D8", "冷启动预热", INSUFFICIENT,
            f"会话数 {len(firsts)}（<{MIN_N}）", "register() 后台预热（21 号 P2）")
    else:
        f95, r50 = _pct(firsts, 0.95), _pct(rests, 0.5)
        add("D8", "冷启动预热", HIT if (r50 and f95 > 5 * r50) else MISS,
            f"首条 p95={f95}ms vs 后续 p50={r50}ms（>5×）", "register() 后台预热（21 号 P2）")

    # D9 · 置信度回归监测（前后半窗 partial 占比）
    conf = [e for e in entries if e.get("confidence") in ("full", "partial", "none")]
    if len(conf) < 2 * MIN_N:
        add("D9", "置信度回归监测", INSUFFICIENT,
            f"带 confidence 样本 {len(conf)}（需 ≥{2 * MIN_N} 才能分前后半窗）", "检查 REQUIRED_FIELDS 与 schema 演进")
    else:
        conf.sort(key=lambda e: e.get("ts", 0))
        h = len(conf) // 2
        early = sum(1 for e in conf[:h] if e["confidence"] == "partial") / h
        late = sum(1 for e in conf[h:] if e["confidence"] == "partial") / (len(conf) - h)
        rise = (late - early) / early if early else (float("inf") if late else 0.0)
        add("D9", "置信度回归监测", HIT if rise > 0.2 else MISS,
            f"partial 占比 {early:.0%} → {late:.0%}（回升 {rise:.0%}，>20%）",
            "检查 REQUIRED_FIELDS 与 schema 演进")

    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="D1–D9 观察项判定表出数（43 号 §7）")
    ap.add_argument("--since", help="起始（2026-10-12 或 '2026-10-12 12:00'，本地时区）")
    ap.add_argument("--until", help="截止（格式同 --since）")
    ap.add_argument("--all-traffic", action="store_true",
                    help="含非真实流量（默认只算 task_id 非空的真实会话——43 号 §7 口径）")
    ap.add_argument("--json", action="store_true", help="JSON 输出")
    ns = ap.parse_args(argv)

    entries = _load_entries(USAGE_LOG)
    if ns.since:
        cut = _parse_ts(ns.since)
        entries = [e for e in entries if e.get("ts", 0) > cut]
    if ns.until:
        cut = _parse_ts(ns.until)
        entries = [e for e in entries if e.get("ts", 0) <= cut]
    n_all = len(entries)
    if not ns.all_traffic:
        entries = [e for e in entries if e.get("task_id")]

    rows = evaluate(entries)
    if ns.json:
        print(json.dumps({"entries": len(entries), "entries_before_real_filter": n_all,
                          "span_days": round(_span_days(entries), 2), "rows": rows},
                         ensure_ascii=False, indent=1))
        return 0

    span = _span_days(entries)
    print(f"D1–D9 判定（真实会话 {len(entries)} 条 / 过滤前 {n_all} 条｜跨度 {span:.1f} 天"
          f"｜样本门槛：分位类 ≥{MIN_N}，比率类跨度 ≥{MIN_SPAN_DAYS:.0f} 天）\n")
    for r in rows:
        print(f"[{r['verdict']}] {r['id']} {r['name']}：{r['metric']}")
        if r["verdict"] == HIT:
            print(f"        → 触发动作：{r['action']}")
    counts = {k: sum(1 for r in rows if r["verdict"] == k) for k in (HIT, MISS, INSUFFICIENT)}
    print(f"\n合计：命中 {counts[HIT]}｜未命中 {counts[MISS]}｜数据不足 {counts[INSUFFICIENT]}")
    if counts[INSUFFICIENT] == len(rows):
        print("（全部数据不足——按 43 号 §7 口径：继续观测并记录本期数字，不据此立项）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
