#!/usr/bin/env python3
"""eval_ask_delta.py — P1 后测：bkn_ask 摘要 vs 旧工具全文（同一批用例）。

对 evals/cases/ontology_qa_45.jsonl 里的症状/错误码用例：
  1) 按旧工具直接调用，记 raw chars（对照）；
  2) 走 bkn_ask 摘要，记 summary chars 与期望证据是否仍在；
  3) 输出压缩比与证据保留率。

用法：LOG_DIR=/tmp/bkn-eval-logs python3 scripts/eval_ask_delta.py --out /tmp/ask_delta.md
"""
import argparse
import json
import os
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("LOG_DIR", "/tmp/bkn-eval-logs")

from plugin.ask import ask  # noqa: E402
from plugin.tools import HANDLERS  # noqa: E402


def _question(case: dict) -> str:
    args = case.get("args") or {}
    if "error_code" in args:
        return "错误码 %s 是什么意思、该怎么处理？" % args["error_code"]
    if "symptom" in args:
        return "出现「%s」时该怎么排查？" % args["symptom"]
    return str(case.get("question") or "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default=str(ROOT / "evals" / "cases" / "ontology_qa_45.jsonl"))
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    cases = [json.loads(l) for l in Path(a.cases).read_text(encoding="utf-8").splitlines() if l.strip()]
    cases = [c for c in cases if c.get("tool") in ("diagnose_db_link", "diagnose_error")]
    rows = []
    for c in cases:
        raw = HANDLERS[c["tool"]](c.get("args") or {})
        q = _question(c)
        summ = ask({"question": q})
        rows.append({"case": c, "raw": len(raw), "sum": len(summ),
                     "hit": any(tok in summ for tok in (c.get("expect") or []))})
    lines = ["# bkn_ask 摘要 vs 旧工具全文（P1 后测）", ""]
    raw_total = sum(r["raw"] for r in rows)
    sum_total = sum(r["sum"] for r in rows)
    hits = sum(1 for r in rows if r["hit"])
    lines.append("| 指标 | 值 |")
    lines.append("|---|---|")
    lines.append("| 用例数 | %d（症状＋错误码） |" % len(rows))
    lines.append("| 旧工具全文合计 | %s chars |" % format(raw_total, ","))
    lines.append("| bkn_ask 摘要合计 | **%s chars** |" % format(sum_total, ","))
    lines.append("| 压缩比 | **%.1f×** |" % (raw_total / max(sum_total, 1)))
    lines.append("| 摘要里期望证据仍在 | **%d/%d** |" % (hits, len(rows)))
    lines.append("| 摘要均长 | %s chars |" % format(round(statistics.mean([r["sum"] for r in rows])), ","))
    lines.append("| 全文均长 | %s chars |" % format(round(statistics.mean([r["raw"] for r in rows])), ","))
    lines.append("")
    lines.append("| 用例 | 工具 | 全文 chars | 摘要 chars | 压缩 | 证据保留 |")
    lines.append("|---|---|---|---|---|---|")
    for r in rows:
        lines.append("| %s | %s | %d | %d | %.1f× | %s |" % (
            r["case"]["id"], r["case"]["tool"], r["raw"], r["sum"],
            r["raw"] / max(r["sum"], 1), "是" if r["hit"] else "否"))
    text = chr(10).join(lines) + chr(10)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
        print("报告 → %s" % a.out)
    print("n=%d 全文合计=%d 摘要合计=%d 压缩=%.1fx 证据保留=%d/%d" % (
        len(rows), raw_total, sum_total, raw_total / max(sum_total, 1), hits, len(rows)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
