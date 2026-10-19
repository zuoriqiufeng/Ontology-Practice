#!/usr/bin/env python3
"""propose_candidates.py — 从缺口日志生成候选**草稿**（P4：反馈闭环）。

只写 `doc/optimize/pending/_proposals/<date>.md`（下划线目录，不参与 apply/门禁），
每条形如：缺口 → 观测 → 建议动作 → 建议目标维度。**不创建候选、不写 payload、不审批。**

用法：python3 scripts/propose_candidates.py [--days 30]
"""
import argparse
import collections
import datetime
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _gaps(days: int):
    since_ts = int((datetime.datetime.now() - datetime.timedelta(days=days)).timestamp())
    rows = []
    for f in sorted(ROOT.glob("logs/gap_log_*.jsonl")):
        try:
            day = f.stem.split("_")[-1]
            datetime.date.fromisoformat(day)
        except Exception:
            day = None
        for ln in f.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                item = json.loads(ln)
            except Exception:
                continue
            ts = item.get("ts") or item.get("timestamp") or 0
            try:
                if int(ts) >= since_ts:
                    rows.append(item)
            except Exception:
                continue
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--top", type=int, default=10)
    a = ap.parse_args()
    rows = _gaps(a.days)
    counter = collections.Counter()
    for r in rows:
        for g in (r.get("gaps") or []):
            key = g if isinstance(g, str) else json.dumps(g, ensure_ascii=False)
            counter[key[:100]] += 1
    out = ["# 候选草稿（自动生成，勿直接落盘）", "",
           "> 来源：`logs/gap_log_*.jsonl`（近 %d 天，%d 条记录）｜ 生成于 %s" % (
               a.days, len(rows), datetime.date.today().isoformat()),
           "> 通过方式：人工挑一条 → 另建 `doc/optimize/pending/C-YYYYMMDD-NN/`（candidate.json + payload）→ 审批。",
           "", "| # | 缺口 | 次数 | 建议动作 |", "|---|---|---|---|"]
    for i, (gap, n) in enumerate(counter.most_common(a.top), 1):
        out.append("| %d | %s | %d | 判断是「本体缺」还是「Skill/侧车缺」：本体缺→补 .bkn（候选）；说法缺→补 aliases.yaml；检索缺→补 Qdrant 文档 |" % (i, gap.replace("|", "\\|"), n))
    if not counter:
        out.append("| - | （无缺口记录） | 0 | 先积累真实流量 |")
    out.extend(["", "## 复核清单", "", "- [ ] 缺口是否重复出现 ≥3 次？",
                "- [ ] 是语义缺失还是说法缺失？", "- [ ] 候选目标维度（bkn / aliases / skill / 侧车）？"])
    text = chr(10).join(out) + chr(10)
    dest_dir = ROOT / "doc/optimize/pending/_proposals"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / (datetime.date.today().isoformat() + ".md")
    dest.write_text(text, encoding="utf-8")
    print("草稿 → %s（%d 类缺口）" % (dest.relative_to(ROOT), len(counter)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
