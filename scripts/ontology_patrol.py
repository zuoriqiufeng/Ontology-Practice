#!/usr/bin/env python3
"""ontology_patrol.py — 本体使用巡检（对照驱动 G-13 的最小落地）

把三份日志（usage / gap / trajectory）汇成**一期巡检报告**，并与上一期对比给出**退化判定**。

设计纪律（三条）:
  1. **只出报告，不作门禁**：阈值与「退化」的处置是人的决策（43 号 §7）。本脚本不返回非 0
     （除用法错误），不写任何 logs/*.jsonl 流。
  2. **不调 Tool**：纯读日志 ⇒ 无 LOG_DIR 污染风险（43 号 §4 第 5 条铁律针对会调 Tool 的脚本）。
     报告落 logs/patrol/（不是 jsonl 流，不被 usage_stats 读到；logs/ 已 gitignore）。
  3. **口径以 43 号 §2 字段字典为准**：真实流量＝task_id 非空；零命中＝hits == 0（仅真实流量）。

用法:
  python3 scripts/ontology_patrol.py                 # 本期报告（默认近 7 天）
  python3 scripts/ontology_patrol.py --days 14       # 近 14 天
  python3 scripts/ontology_patrol.py --json          # 只打印机器可读 JSON
  python3 scripts/ontology_patrol.py --no-write      # 不落盘（只看）
退出码: 0（报告型脚本；退化只标记，不阻断）
依据: doc/comparison/openbkn-engineering/04-gap-register.md G-13；doc/build/demo_product-bkn/43-usage_log_analysis.md §4/§7
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from plugin.usage_log import resolve_log_path  # noqa: E402  （日志路径的唯一事实源）

#: 本体侧事件（69 号 §5 契约）
ONTOLOGY_EVENTS = ("ontology_use", "mech_candidates", "answer_source", "bkn_load", "source_miss", "source_error")


def _load(paths) -> tuple:
    """读 jsonl（含分片与旧命名）；返回 (条目, 坏行数)。坏行计数是数据卫生指标（43 号 §4）。"""
    rows, bad = [], 0
    for p in paths:
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                bad += 1
    return rows, bad


def _day_files(base: Path) -> list:
    """日期分片 + 旧命名（无日期）全集；旧命名无法判日，一并纳入（报告如实反映口径）。"""
    stem = base.name.split(".")[0]
    return [p for p in sorted(base.parent.glob(stem + "*")) if p.is_file()]


def collect(days: int) -> dict:
    since = date.today() - timedelta(days=days)
    usage_paths = _day_files(resolve_log_path("usage_log.jsonl"))
    gap_paths = _day_files(resolve_log_path("gap_log.jsonl"))
    traj_dir = resolve_log_path("usage_log.jsonl").parent / "trajectories"
    traj_paths = sorted(traj_dir.glob("trajectory_*.jsonl")) if traj_dir.is_dir() else []

    usage, bad_u = _load(usage_paths)
    gaps, bad_g = _load(gap_paths)
    traj, bad_t = _load(traj_paths)

    def _recent(rows):
        keep = []
        for r in rows:
            ts = r.get("ts")
            if isinstance(ts, (int, float)):
                if datetime.fromtimestamp(ts, tz=timezone.utc).date() < since:
                    continue
            keep.append(r)
        return keep

    usage, gaps, traj = _recent(usage), _recent(gaps), _recent(traj)
    real = [r for r in usage if r.get("task_id")]
    hits = [r for r in real if "hits" in r]
    zero = [r for r in hits if r.get("hits") == 0]
    events = Counter(r.get("event") for r in traj if r.get("event"))
    return {
        "window_days": days,
        "since": since.isoformat(),
        "usage": {"total": len(usage), "real": len(real),
                  "by_tool": dict(Counter(r.get("tool") for r in real).most_common(10))},
        "retrieval": {"with_hits": len(hits), "zero_hit": len(zero),
                      "zero_hit_rate": (round(len(zero) / len(hits), 3) if hits else None)},
        "gap_log": {"entries": len(gaps),
                    "by_tool": dict(Counter(r.get("tool") for r in gaps).most_common(10))},
        "trajectory": {"records": len(traj), "real": sum(1 for r in traj if r.get("task_id")),
                       "ontology_events": {k: events.get(k, 0) for k in ONTOLOGY_EVENTS},
                       "ontology_use_total": events.get("ontology_use", 0),
                       "events_total": sum(events.values()),
                       "other_events": dict(Counter(
                           {k: v for k, v in events.items() if k not in ONTOLOGY_EVENTS}).most_common(10))},
        "hygiene": {"bad_lines": bad_u + bad_g + bad_t},
    }


def _prev(report_dir: Path):
    files = sorted(report_dir.glob("patrol_*.json"))
    if not files:
        return None
    try:
        return json.loads(files[-1].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def degradation(cur: dict, prev) -> list:
    """退化判定（**只标记，不阻断**）。判据参考 43 号 §7 与对照项 G-13 的「与上期比」。"""
    if not prev:
        return []
    flags = []
    c, p = cur["retrieval"], prev.get("retrieval", {})
    if c.get("zero_hit_rate") is not None and p.get("zero_hit_rate") is not None:
        if c["zero_hit_rate"] - p["zero_hit_rate"] > 0.05:
            flags.append("零命中率上升 >5 个百分点（%.3f → %.3f）" % (p["zero_hit_rate"], c["zero_hit_rate"]))
    prev_real = prev.get("usage", {}).get("real", 0)
    if cur["usage"]["real"] < prev_real:
        flags.append("真实调用数少于上期（%d → %d）——先排除「没人用」，再谈退化" % (prev_real, cur["usage"]["real"]))
    if cur["gap_log"]["entries"] > prev.get("gap_log", {}).get("entries", 0):
        flags.append("缺口记录增加（%d → %d）" % (prev.get("gap_log", {}).get("entries", 0), cur["gap_log"]["entries"]))
    if cur["hygiene"]["bad_lines"] > 0:
        flags.append("日志存在坏行 %d 条（数据卫生问题，先修日志再谈结论）" % cur["hygiene"]["bad_lines"])
    return flags


def render(cur: dict, prev_meta: str, flags: list) -> str:
    t = cur["trajectory"]
    lines = [
        "# 本体使用巡检报告（%s，窗口 %d 天）" % (date.today().isoformat(), cur["window_days"]),
        "",
        "> 生成：scripts/ontology_patrol.py｜窗口起点：%s｜上期报告：%s" % (cur["since"], prev_meta),
        "> **本报告不是门禁**：退化只标记，处置由人按 43 号 §7 决策表判。",
        "",
        "## 1. 流量",
        "",
        "| 项 | 值 |",
        "|---|---|",
        "| usage 条目 | %d |" % cur["usage"]["total"],
        "| **真实流量**（task_id 非空） | **%d** |" % cur["usage"]["real"],
        "| 真实流量 Top Tool | %s |" % (json.dumps(cur["usage"]["by_tool"], ensure_ascii=False) or "—"),
        "| trajectory 记录 | %d（其中真实 %d） |" % (t["records"], t["real"]),
        "",
        "## 2. 检索与缺口",
        "",
        "| 项 | 值 |",
        "|---|---|",
        "| 真实检索调用（带 hits） | %d |" % cur["retrieval"]["with_hits"],
        "| 零命中 | %d |" % cur["retrieval"]["zero_hit"],
        "| **零命中率** | %s |" % ("—" if cur["retrieval"]["zero_hit_rate"] is None
                                   else "%.1f%%" % (cur["retrieval"]["zero_hit_rate"] * 100)),
        "| gap_log 条目 | %d |" % cur["gap_log"]["entries"],
        "",
        "## 3. 本体事件（69 号 §5 契约）",
        "",
        "| 事件 | 次数 |",
        "|---|---|",
    ]
    for k, v in t["ontology_events"].items():
        lines.append("| %s | %d |" % (k, v))
    lines.append("| （本体事件小计） | %d |" % sum(t["ontology_events"].values()))
    lines.append("| **全部事件**（含非本体） | **%d** |" % t.get("events_total", 0))
    if t.get("other_events"):
        lines.append("")
        lines.append("非本体事件分布：%s" % json.dumps(t["other_events"], ensure_ascii=False))
    lines += [
        "",
        "> **读法**：ontology_use 为 **0** 时，一切「本体在真实流量里被用上了」的说法都是**未验证**的",
        "> ——只有探针（构造调用）数据，不是现场数据（见 capability 件 §4-c 的样本量纪律）。",
        "",
        "## 4. 退化判定（只标记）",
        "",
    ]
    lines += (["- " + f for f in flags] if flags else ["（无标记；首次运行或指标未超阈）"])
    lines += [
        "",
        "## 5. 数据卫生",
        "",
        "- 坏行：**%d**（>0 须先修日志再谈结论）" % cur["hygiene"]["bad_lines"],
        "- 本脚本**不写任何 jsonl 流**；报告落 logs/patrol/（gitignored，非被读口径）。",
        "",
        "---",
        "",
        "*阈值口径：零命中率 +5pp／缺口增加／真实调用下降；均为**标记**，非门禁。依据 43 号 §7 与对照项 G-13。*",
    ]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="本体使用巡检报告（报告型，不作门禁）")
    ap.add_argument("--days", type=int, default=7, help="窗口天数（默认 7）")
    ap.add_argument("--json", action="store_true", help="只打印 JSON")
    ap.add_argument("--no-write", action="store_true", help="不落盘")
    ns = ap.parse_args(argv)

    cur = collect(ns.days)
    out_dir = resolve_log_path("usage_log.jsonl").parent / "patrol"
    prev = _prev(out_dir)
    flags = degradation(cur, prev)
    if ns.json:
        print(json.dumps({"current": cur, "degradation": flags}, ensure_ascii=False, indent=1))
        return 0

    text = render(cur, ("有" if prev else "无（首次）"), flags)
    print(text)
    if not ns.no_write:
        out_dir.mkdir(parents=True, exist_ok=True)
        md = out_dir / ("patrol_%s.md" % date.today().isoformat())
        md.write_text(text, encoding="utf-8")
        (out_dir / ("patrol_%s.json" % date.today().isoformat())).write_text(
            json.dumps(cur, ensure_ascii=False, indent=1), encoding="utf-8")
        print("已落盘：%s" % md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
