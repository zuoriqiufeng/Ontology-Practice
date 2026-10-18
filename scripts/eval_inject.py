#!/usr/bin/env python3
"""eval_inject.py — P1b 后测：请求级注入的命中率与体积。

对 45 条用例构造合成请求（system + user），跑 llm_request_middleware：
  1) 码/症状类应命中（返回 request）；关系/操作/兼容类应不命中（None）；
  2) 注入块 ≤600 字；
  3) 幂等：对注入后的请求再跑一次必须返回 None。
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

from plugin.inject import MARKER, llm_request_middleware  # noqa: E402


def _question(case: dict) -> str:
    return str(case.get("question") or "")


def _req(text: str) -> dict:
    return {"messages": [{"role": "system", "content": "SYS"}, {"role": "user", "content": text}]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default=str(ROOT / "evals" / "cases" / "ontology_qa_45.jsonl"))
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    cases = [json.loads(l) for l in Path(a.cases).read_text(encoding="utf-8").splitlines() if l.strip()]
    expect_hit = ("symptom", "error_code")
    rows = []
    for c in cases:
        req = _req(_question(c))
        out = llm_request_middleware(request=req)
        hit = out is not None
        size = 0
        idem = True
        if hit:
            msgs = out["request"]["messages"]
            content = str(msgs[0].get("content") or "")
            size = len(content) - len("SYS")
            idem = llm_request_middleware(request=out["request"]) is None
        rows.append({"case": c, "hit": hit, "size": size, "idem": idem,
                     "want": c.get("category") in expect_hit})
    want = [r for r in rows if r["want"]]
    notwant = [r for r in rows if not r["want"]]
    want_hit = sum(1 for r in want if r["hit"])
    false_pos = sum(1 for r in notwant if r["hit"])
    sizes = [r["size"] for r in want if r["hit"]]
    idem_ok = sum(1 for r in want if r["hit"] and r["idem"])
    lines = ["# 请求级注入后测（P1b）", "",
             "| 指标 | 值 |", "|---|---|"]
    lines.append("| 应命中用例（码+症状） | %d |" % len(want))
    lines.append("| **实际命中** | **%d/%d = %d%%** |" % (want_hit, len(want), round(100 * want_hit / max(len(want), 1))))
    lines.append("| 不应命中用例（关系/操作/兼容） | %d｜误命中 %d |" % (len(notwant), false_pos))
    lines.append("| 注入块 mean / max | %d / %d chars |" % (round(statistics.mean(sizes)) if sizes else 0, max(sizes) if sizes else 0))
    lines.append("| 幂等（二次调用返回 None） | %d/%d |" % (idem_ok, want_hit))
    text = chr(10).join(lines) + chr(10)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
        print("报告 → %s" % a.out)
    print("应命中 %d/%d｜误命中 %d/%d｜块 mean=%d max=%d｜幂等 %d/%d" % (
        want_hit, len(want), false_pos, len(notwant),
        round(statistics.mean(sizes)) if sizes else 0, max(sizes) if sizes else 0, idem_ok, want_hit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
