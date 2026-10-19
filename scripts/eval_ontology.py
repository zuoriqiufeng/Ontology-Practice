#!/usr/bin/env python3
"""eval_ontology.py — 本体接入的离线评测（P0 基线用）。

对 evals/cases/*.jsonl 逐条调用真实 handler，度量四件事：
  1) evidence 命中率（期望 token 是否出现在返回里）
  2) 输出体积（chars，token 成本代理）与延迟
  3) JSON 合法性
  4) 失败清单

不依赖 LLM / 网络；写入 LOG_DIR 指定目录，避免污染生产日志。

用法：
    LOG_DIR=/tmp/bkn-eval-logs python3 scripts/eval_ontology.py \
        --cases evals/cases/ontology_qa_50.jsonl --out /tmp/eval.md
"""
import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("LOG_DIR", "/tmp/bkn-eval-logs")

from plugin.tools import HANDLERS  # noqa: E402


def load_cases(path: Path) -> list:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def run(cases: list) -> list:
    out = []
    for c in cases:
        tool = c["tool"]
        handler = HANDLERS.get(tool)
        t0 = time.perf_counter()
        err = None
        text = ""
        if handler is None:
            err = "no handler: %s" % tool
        else:
            try:
                res = handler(c.get("args") or {})
                text = res if isinstance(res, str) else json.dumps(res, ensure_ascii=False)
            except Exception as exc:  # noqa: BLE001
                err = "%s: %s" % (type(exc).__name__, exc)
        ms = (time.perf_counter() - t0) * 1000
        hit = any(tok in text for tok in (c.get("expect") or []))
        try:
            json.loads(text)
            structured_ok = True
        except Exception:
            structured_ok = text.startswith(("root:", "{", "[", "'"))
        out.append({"case": c, "ms": ms, "chars": len(text), "hit": hit,
                    "json_ok": structured_ok, "err": err})
    return out


def pct(values, p):
    if not values:
        return 0.0
    k = max(0, min(len(values) - 1, int(round((p / 100.0) * (len(values) - 1)))))
    return sorted(values)[k]


def report(rows: list, cases_path: Path) -> tuple:
    n = len(rows)
    hits = sum(1 for r in rows if r["hit"])
    jsonok = sum(1 for r in rows if r["json_ok"])
    errs = [r for r in rows if r["err"]]
    ms = [r["ms"] for r in rows]
    cs = [r["chars"] for r in rows]
    lines = []
    lines.append("# 本体接入评测（P0 基线）")
    lines.append("")
    lines.append("> 用例：`%s`（%d 条）｜ 评测脚本：`scripts/eval_ontology.py` ｜ 无 LLM/网络" % (cases_path, n))
    lines.append("")
    lines.append("| 指标 | 值 |")
    lines.append("|---|---|")
    lines.append("| 证据命中率 | %d/%d = %.0f%% |" % (hits, n, 100.0 * hits / max(n, 1)))
    lines.append("| 结构化返回率（JSON 或 Toon） | %d/%d = %.0f%% |" % (jsonok, n, 100.0 * jsonok / max(n, 1)))
    lines.append("| 失败数 | %d |" % len(errs))
    lines.append("| 延迟 p50 / p95 | %.0f ms / %.0f ms |" % (pct(ms, 50), pct(ms, 95)))
    lines.append("| 输出体积 mean / p95 | %.0f / %.0f chars |" % (statistics.mean(cs) if cs else 0, pct(cs, 95)))
    lines.append("| 总输出体积（估算 token ≈ chars/2.5） | %.0f chars ≈ %d tokens |" % (sum(cs), sum(cs) / 2.5))
    lines.append("")
    lines.append("## 逐条结果")
    lines.append("")
    lines.append("| 用例 | 类别 | 工具 | 命中 | chars | ms |")
    lines.append("|---|---|---|---|---|---|")
    for r in rows:
        lines.append("| %s | %s | %s | %s | %d | %.0f |" % (
            r["case"]["id"], r["case"].get("category", ""), r["case"].get("tool", ""),
            "是" if r["hit"] else "否", r["chars"], r["ms"]))
    if errs:
        lines.append("")
        lines.append("## 失败")
        lines.append("")
        for r in errs:
            lines.append("- `%s`：%s" % (r["case"]["id"], r["err"]))
    return "\n".join(lines) + "\n", {"n": n, "hits": hits, "jsonok": jsonok, "errs": len(errs),
                                     "p50": pct(ms, 50), "p95": pct(ms, 95), "chars": sum(cs)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default=str(ROOT / "evals" / "cases" / "ontology_qa_50.jsonl"))
    ap.add_argument("--out", default="")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    path = Path(a.cases)
    if not path.is_file():
        print("用例文件不存在：%s（先跑 scripts/gen_eval_cases.py）" % path)
        return 2
    cases = load_cases(path)
    if a.limit:
        cases = cases[: a.limit]
    rows = run(cases)
    text, stats = report(rows, path)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
        print("报告 → %s" % a.out)
    print("n=%d 命中率=%.0f%% JSON=%.0f%% 失败=%d p50=%.0fms p95=%.0fms 总 chars=%d" % (
        stats["n"], 100.0 * stats["hits"] / max(stats["n"], 1),
        100.0 * stats["jsonok"] / max(stats["n"], 1), stats["errs"], stats["p50"], stats["p95"], stats["chars"]))
    return 0 if stats["errs"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
