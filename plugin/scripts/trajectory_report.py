#!/usr/bin/env python3
"""trajectory_report.py — 任务级轨迹聚合视图（25 号批 U-1，2026-10-12）

读 `logs/trajectories/trajectory_*.jsonl`（**调用级事件流**，写入方 `plugin/trajectory.py`），
按 task_id 组装 timeline：

- 排序键 `(ts, seq)`；事件数 > 40 时保留**首尾 + 异常项**（`confidence != full` 或带 `error`），
  在输出里标 `_trimmed` / `total_events`（对应 25 号 §3 的体量控制口径）；
- `final_answer` / `task_status` 属**上游获取**（Hermes `state.db`），本视图不含（Q13 探查结论）；
- I8 抽查：逐任务统计缺 `bkn_version` 的事件数。

用法:
  python3 plugin/scripts/trajectory_report.py                  # 全部任务概览
  python3 plugin/scripts/trajectory_report.py --task <task_id> # 单任务 timeline
  python3 plugin/scripts/trajectory_report.py --since 2026-10-12 --limit 5 --json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_DIR.parent))

MAX_TIMELINE = 40          # 单任务 timeline 上限（超出走首尾+异常截断）
KEEP_HEAD = 10             # 截断时保留的头部条数
KEEP_TAIL = 10             # 截断时保留的尾部条数
MAX_ANOMALIES = 20         # 异常项最多补入条数


def default_base() -> Path:
    """默认逻辑基名：<LOG_DIR>/trajectories/trajectory.jsonl（env LOG_DIR 生效）。"""
    from plugin.config import resolve_log_path
    return resolve_log_path("trajectories/trajectory.jsonl")


def find_files(base: Path) -> list[Path]:
    """枚举轨迹数据文件（日期分片 + 大小分片；容忍 .bak 之外的一切后缀）。"""
    from plugin.log_rotate import iter_data_files
    return iter_data_files(base)


def load_events(paths: list[Path]) -> list[dict]:
    """读取全部事件行（坏行跳过）。"""
    events: list[dict] = []
    for f in paths:
        try:
            with open(f, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(obj, dict) and obj.get("task_id"):
                        events.append(obj)
        except OSError:
            continue
    return events


def group_tasks(events: list[dict], max_timeline: int = MAX_TIMELINE) -> dict:
    """按 task_id 组装 timeline（含首尾+异常截断与 I8 缺版本计数）。"""
    by_task: dict[str, list[dict]] = {}
    for e in events:
        by_task.setdefault(str(e.get("task_id")), []).append(e)

    tasks: dict[str, dict] = {}
    for tid, evs in by_task.items():
        evs = sorted(evs, key=lambda e: (e.get("ts") or 0, e.get("seq") or 0))
        view = evs
        trimmed = False
        if len(evs) > max_timeline:
            head = evs[:KEEP_HEAD]
            tail = evs[-KEEP_TAIL:]
            anomalies = [e for e in evs
                         if e.get("error") or e.get("confidence") not in (None, "full")]
            picked = {id(e) for e in head + tail}
            extra = [e for e in anomalies if id(e) not in picked][:MAX_ANOMALIES]
            view = sorted(head + extra + tail,
                          key=lambda e: (e.get("ts") or 0, e.get("seq") or 0))
            trimmed = True
        sessions = {e.get("session_id") for e in evs if e.get("session_id")}
        tasks[tid] = {
            "task_id": tid,
            "session_id": sorted(sessions)[0] if sessions else None,
            "total_events": len(evs),
            "tools": dict(Counter(e.get("tool", "?") for e in evs)),
            "first_ts": evs[0].get("ts"),
            "last_ts": evs[-1].get("ts"),
            "missing_bkn_version": sum(1 for e in evs if not e.get("bkn_version")),
            "_trimmed": trimmed,
            "timeline": view,
        }
    return tasks



# ========== P1：本体使用台账聚合（2026-10-14，--ontology） ==========

def aggregate_ontology(events: list[dict]) -> dict:
    """按 Tool 汇总 `ontology_use` 事件，回答「本体在哪个阶段被用、是否真起作用」。

    只读同一份事件流（不新增流、不新增文件）。口径：
    - `bkn_used` 是**下界**（只统计「返回体里出现过」的 ID），不是「决定答案的条数」；
    - `origin` 是分层计数最多的那一层——混源时看 `sources` 明细；
    - `narrowed` 只在 `mech_candidates` 事件上存在（diagnose_mechanism 专有）；
    - P3：`paths_considered`/`paths_used` 是**图**口径（本体给出多少条候选 / 其中多少进了输出），
      与 `bkn_used`（展示列表，上限 8）不是同一口径，别互相替代。
    """
    per_tool: dict[str, dict] = {}
    origins: Counter = Counter()
    layers: Counter = Counter()
    stages: Counter = Counter()
    reads: Counter = Counter()
    graph_edges: Counter = Counter()
    graph_branches: Counter = Counter()
    narrowed = {"true": 0, "false": 0}
    ans_src = Counter()
    calls_with_ledger = 0
    calls_with_read_no_use = 0
    calls_offered_but_unused = 0
    calls_shape_gap = 0
    paths_considered = 0
    paths_id_considered = 0
    paths_used = 0
    warm_loads = 0
    warm_files = 0
    for e in events:
        ev = e.get("event")
        if ev == "ontology_use":
            calls_with_ledger += 1
            tool = str(e.get("tool") or "?")
            row = per_tool.setdefault(tool, {"calls": 0, "used": 0, "read": 0, "dropped": 0,
                                             "considered": 0, "id_considered": 0,
                                             "used_paths": 0, "graph_ops": 0,
                                             "origin": Counter(), "stages": Counter(),
                                             "branches": Counter()})
            row["calls"] += 1
            row["used"] += int(e.get("bkn_used") or 0)
            row["read"] += int(e.get("bkn_read") or 0)
            row["dropped"] += int(e.get("bkn_dropped") or 0)
            if e.get("origin"):
                row["origin"][e["origin"]] += 1
                origins[e["origin"]] += 1
            for s in (e.get("stages") or []):
                row["stages"][s] += 1
                stages[s] += 1
            for layer, info in (e.get("sources") or {}).items():
                layers[layer] += int((info or {}).get("n") or 0)
            for r in (e.get("reads") or []):
                if isinstance(r, dict) and r.get("file"):
                    reads[r["file"]] += 1
            if int(e.get("bkn_read") or 0) > 0 and int(e.get("bkn_used") or 0) == 0:
                calls_with_read_no_use += 1
            # ── P3：图（边）消费 ──
            _cons = int(e.get("paths_considered") or 0)
            _usedp = int(e.get("paths_used") or 0)
            _idcons = int(e.get("paths_id_considered") or 0)
            row["considered"] += _cons
            row["id_considered"] += _idcons
            row["used_paths"] += _usedp
            row["graph_ops"] += int(e.get("graph_ops") or 0)
            paths_considered += _cons
            paths_id_considered += _idcons
            paths_used += _usedp
            for edge, info in (e.get("graph_edges") or {}).items():
                graph_edges[edge] += int((info or {}).get("t") or 0)
            for b in (e.get("graph_branches") or []):
                row["branches"][b] += 1
                graph_branches[b] += 1
            # 「给了没接上」只对**形状可比**的候选成立；全部候选都不可比时另计，不算缺口
            if _idcons > 0 and _usedp == 0:
                calls_offered_but_unused += 1
                row["offered_but_unused"] = row.get("offered_but_unused", 0) + 1
            elif _cons > 0 and _idcons == 0:
                calls_shape_gap += 1
        elif ev == "mech_candidates":
            narrowed["true" if e.get("narrowed") else "false"] += 1
        elif ev == "answer_source":
            ans_src[str(e.get("from") or ("bkn_edge" if e.get("bkn_keys") else (
                "sidecar" if e.get("sidecar") else ("qdrant_doc" if e.get("docs") else "logic"))))] += 1
        elif ev == "bkn_load":
            warm_loads += 1
            warm_files = max(warm_files, int(e.get("files") or 0))
    for row in per_tool.values():
        row["origin"] = dict(row["origin"])
        row["stages"] = dict(row["stages"])
        row["branches"] = dict(row["branches"])
    return {"per_tool": per_tool, "origins": dict(origins), "layers": dict(layers),
            "stages": dict(stages), "top_reads": reads.most_common(10),
            "top_graph_edges": graph_edges.most_common(12),
            "graph_branches": dict(graph_branches),
            "paths_considered": paths_considered, "paths_used": paths_used,
            "paths_id_considered": paths_id_considered, "calls_shape_gap": calls_shape_gap,
            "calls_offered_but_unused": calls_offered_but_unused,
            "mech_narrowed": narrowed, "answer_source": dict(ans_src),
            "calls_with_ledger": calls_with_ledger,
            "calls_read_but_unused": calls_with_read_no_use,
            "warm_loads": warm_loads, "warm_files": warm_files}


def render_ontology(agg: dict, stream=None) -> None:
    """打印本体使用汇总（人读形态）。"""
    import sys as _sys
    out = stream or _sys.stdout
    out.write("本体使用台账（ontology_use）：%d 次有交互的 Tool 调用\n" % agg["calls_with_ledger"])
    if agg["warm_loads"]:
        out.write("冷启动预热：%d 次，全量 .bkn %d 件（进程内一次性，之后走内存缓存）\n"
                  % (agg["warm_loads"], agg["warm_files"]))
    out.write("来源分层（次数）：%s\n" % (agg["layers"] or "（无）"))
    out.write("答案来源（次数）：%s\n" % (agg["answer_source"] or "（无）"))
    out.write("机制收窄（本体是否起功能作用）：narrowed=%s\n" % (agg["mech_narrowed"] or "（无）"))
    if agg["calls_read_but_unused"]:
        out.write("⚠ 读了 .bkn 但返回体里没出现本体 ID 的调用：%d 次（读带/用带宽口径差异，需人看）\n"
                  % agg["calls_read_but_unused"])
    if agg["top_reads"]:
        out.write("被读最多的 .bkn：%s\n" % ", ".join("%s×%d" % (f, n) for f, n in agg["top_reads"]))
    # ── P3：图（边）消费 ──
    _cons, _used = agg.get("paths_considered", 0), agg.get("paths_used", 0)
    _idcons = agg.get("paths_id_considered", 0)
    if _cons or _used:
        # 分母用**形状可比**的去重候选（paths_id_considered）而不是 _cons：
        # _cons 含同一目标经多条边重复出现，且含输出识别器不认的命名空间（compatibility:…），
        # 拿它当分母会把命中率算得过低，看不出真实情况。
        out.write("图路径：本体给出 %d 条候选（去重后可比 %d 条），%d 条进输出（%.0f%%）\n"
                  % (_cons, _idcons, _used,
                     (100.0 * _used / _idcons) if _idcons else 0.0))
    if agg.get("top_graph_edges"):
        out.write("被消费的边（括号内＝本次产出目标数合计）：%s\n"
                  % ", ".join("%s×%d" % (e, n) for e, n in agg["top_graph_edges"]))
    if agg.get("graph_branches"):
        out.write("图出口分布：%s\n" % agg["graph_branches"])
    if agg.get("calls_shape_gap"):
        out.write("· 另有 %d 次调用的图目标**全在输出识别白名单之外**（如 compatibility:）——"
                  "结构性不可比，未计入命中率（见 69 号 §4 口径）\n" % agg["calls_shape_gap"])
    if agg.get("calls_offered_but_unused"):
        out.write("⚠ 本体给了候选路径、但一条都没进输出的调用：%d 次（不是「本体没给」，是「给了没接上」）\n"
                  % agg["calls_offered_but_unused"])
    out.write("\n%-24s %6s %8s %8s %8s %8s %8s  %s\n"
              % ("tool", "调用", "used均", "read均", "可比给均", "路径用均", "dropped", "主来源"))
    for tool, row in sorted(agg["per_tool"].items(), key=lambda kv: -kv[1]["calls"]):
        calls = max(row["calls"], 1)
        out.write("%-24s %6d %8.1f %8.1f %8.1f %8.1f %8d  %s\n" % (
            tool, row["calls"], row["used"] / calls, row["read"] / calls,
            row.get("id_considered", 0) / calls, row.get("used_paths", 0) / calls,
            row["dropped"], row["origin"] or "-"))
    out.write("\n阶段分布（stages）：%s\n" % (agg["stages"] or "（无）"))
    out.write("说明：bkn_used 只统计「返回体里出现过」的本体 ID（展示上限 8），是**下界**；\n"
              "      路径给/路径用是**图**口径（本体给出多少候选 / 多少进输出），两者不可互相替代。\n")

def _fmt_ts(ts) -> str:
    try:
        return datetime.fromtimestamp(int(ts)).strftime("%m-%d %H:%M:%S")
    except Exception:
        return "?"


def render(task: dict, stream) -> None:
    head = (f"任务 {task['task_id']}（session {task.get('session_id') or '-'}）："
            f"事件 {task['total_events']}（{_fmt_ts(task.get('first_ts'))} → "
            f"{_fmt_ts(task.get('last_ts'))}）｜工具 {len(task['tools'])} 种｜"
            f"缺 bkn_version {task['missing_bkn_version']}")
    if task.get("_trimmed"):
        head += f"｜⚠ 已截断（保留 {len(task['timeline'])} 条，含首尾+异常项）"
    print(head)
    print(f"  {'seq':>4s}  {'ts':17s}  {'tool':22s} {'conf':8s} {'hits':>4s} {'gaps':>4s} {'ms':>6s}")
    for e in task["timeline"]:
        print(f"  {e.get('seq', 0):4d}  {_fmt_ts(e.get('ts')):17s}  {str(e.get('tool')):22s} "
              f"{str(e.get('confidence') or '-'):8s} {len(e.get('bkn_hits') or []):4d} "
              f"{len(e.get('gaps') or []):4d} {str(e.get('duration_ms') or '-'):>6s}")
    print()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="任务级轨迹聚合视图（读 logs/trajectories/）")
    ap.add_argument("--log-dir", default=None,
                    help="日志目录（缺省走 LOG_DIR / plugin 配置；只用于定位 trajectories/）")
    ap.add_argument("--task", default=None, help="只看某任务")
    ap.add_argument("--since", default=None, help="只统计该日期（YYYY-MM-DD）之后的事件")
    ap.add_argument("--limit", type=int, default=20, help="最多展示的任务数（默认 20）")
    ap.add_argument("--json", action="store_true", help="输出 JSON（机器读）")
    ap.add_argument("--ontology", action="store_true",
                    help="本体使用台账汇总（ontology_use/bkn_load/mech_candidates/answer_source）")
    ns = ap.parse_args(argv)

    base = (Path(ns.log_dir) / "trajectories" / "trajectory.jsonl") if ns.log_dir else default_base()
    paths = find_files(base)
    events = load_events(paths)
    if ns.since:
        try:
            cutoff = int(datetime.strptime(ns.since, "%Y-%m-%d").timestamp())
            events = [e for e in events if (e.get("ts") or 0) >= cutoff]
        except ValueError:
            print(f"✗ --since 格式应为 YYYY-MM-DD：{ns.since}", file=sys.stderr)
            return 2

    tasks = group_tasks(events)
    if ns.task:
        tasks = {ns.task: tasks[ns.task]} if ns.task in tasks else {}

    if ns.ontology:
        agg = aggregate_ontology(events)
        if ns.json:
            print(json.dumps(agg, ensure_ascii=False, indent=1))
        else:
            render_ontology(agg)
        return 0

    if ns.json:
        print(json.dumps({"tasks": list(tasks.values())}, ensure_ascii=False, indent=1))
        return 0

    print(f"轨迹：{len(tasks)} 个任务｜{len(events)} 条事件｜来源 {base.parent}")
    if not tasks:
        print("（无轨迹数据——轨迹只写真实会话〔task_id 非空〕，见 plugin/trajectory.py 口径）")
        return 0
    print()
    for task in sorted(tasks.values(), key=lambda t: t.get("first_ts") or 0,
                       reverse=True)[:max(ns.limit, 0)]:
        render(task, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
