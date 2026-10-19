#!/usr/bin/env python3
"""weekly_report.py — 本体参与度周报（P4：把事件变成可读结论）。

读 logs/ 下 usage_log / trajectory / gap_log，产出：
  1) 调用总量与真实会话数（task_id 非空）；2) 工具分布；3) answer_source 来源层分布；
  4) mention_resolve 的 unknown 占比；5) 缺口 Top；6) 建议动作。

用法：python3 scripts/weekly_report.py [--days 7] [--out path]
"""
import argparse
import collections
import datetime
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _lines(patterns):
    for pat in patterns:
        for f in sorted(ROOT.glob(pat)):
            for ln in f.read_text(encoding="utf-8", errors="ignore").splitlines():
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    yield json.loads(ln)
                except Exception:
                    continue


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    since_date = datetime.date.today() - datetime.timedelta(days=a.days - 1)
    since = since_date.isoformat()
    since_ts = int(datetime.datetime.combine(since_date, datetime.time(0, 0)).timestamp())
    def _in_range(d):
        ts = d.get("ts") or d.get("timestamp") or 0
        try:
            return int(ts) >= since_ts
        except Exception:
            return False
    usage = [d for d in _lines(["logs/usage_log_*.jsonl"]) if _in_range(d)]
    traj = [d for d in _lines(["logs/trajectories/*.jsonl"]) if _in_range(d)]
    gaps = [d for d in _lines(["logs/gap_log_*.jsonl"]) if _in_range(d)]
    tools = collections.Counter(d.get("tool") for d in usage if d.get("tool"))
    real = {str(d.get("task_id")) for d in usage if d.get("task_id")}
    sources = collections.Counter()
    mentions = collections.Counter()
    for d in traj:
        ev = d.get("event")
        if ev == "answer_source":
            sources[str(d.get("layer") or d.get("source") or "unknown")] += 1
        elif ev == "mention_resolve":
            mentions[str(d.get("path") or "unknown")] += 1
    gap_reasons = collections.Counter()
    for g in gaps:
        for item in (g.get("gaps") or []):
            key = item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
            gap_reasons[key[:80]] += 1
    unknown = mentions.get("unknown", 0)
    total_m = sum(mentions.values())
    out = []
    out.append("# 本体参与度周报（近 %d 天，%s 起）" % (a.days, since))
    out.append("")
    out.append("| 指标 | 值 |")
    out.append("|---|---|")
    out.append("| 工具调用（usage_log） | %d |" % sum(tools.values()))
    out.append("| 真实会话（task_id 非空） | %d |" % len(real))
    out.append("| 轨迹事件（trajectory） | %d |" % len(traj))
    out.append("| answer_source 事件 | %d |" % sum(sources.values()))
    out.append("| mention_resolve unknown | %d/%d |" % (unknown, total_m))
    out.append("| 缺口记录 | %d |" % len(gaps))
    out.append("")
    out.append("## 工具分布")
    out.append("")
    out.append("| 工具 | 次数 |")
    out.append("|---|---|")
    for k, v in tools.most_common():
        out.append("| %s | %d |" % (k, v))
    if sources:
        out.append("")
        out.append("## 来源层分布（answer_source）")
        out.append("")
        out.append("| layer | 次数 |")
        out.append("|---|---|")
        for k, v in sources.most_common():
            out.append("| %s | %d |" % (k, v))
    if gap_reasons:
        out.append("")
        out.append("## 缺口 Top")
        out.append("")
        out.append("| 缺口 | 次数 |")
        out.append("|---|---|")
        for k, v in gap_reasons.most_common(10):
            out.append("| %s | %d |" % (k, v))
    actions = []
    if total_m and unknown / total_m >= 0.2:
        actions.append("mention_resolve unknown 占比 %d%% ≥20%% → 跑 `plugin/scripts/alias_candidates.py` 出别名候选" % round(100 * unknown / total_m))
    zero = [t for t in ("query_product", "explain_architecture", "design_solution", "list_scenarios", "get_prerequisites") if not tools.get(t)]
    if zero:
        actions.append("零调用工具：%s → 检查是否被 tool_search 延迟、或需改描述/加注入" % ", ".join(zero))
    if gap_reasons:
        actions.append("缺口 Top 前 3 条 → 跑 `scripts/propose_candidates.py` 出候选草稿")
    if not sources:
        actions.append("answer_source 为空 → 确认 trace middleware 已注册（C-20261018-08）")
    out.append("")
    out.append("## 建议动作")
    out.append("")
    out.extend("- " + x for x in actions) if actions else out.append("- 无（数据不足或全部健康）")
    text = chr(10).join(out) + chr(10)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
        print("报告 → %s" % a.out)
    print("tools=%d real_sessions=%d events=%d sources=%d gaps=%d" % (
        sum(tools.values()), len(real), len(traj), sum(sources.values()), len(gaps)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
