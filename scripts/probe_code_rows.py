#!/usr/bin/env python3
"""probe_code_rows.py — 「码查询」before/after 证据脚本（84 号验收 A1–A3）。

用法：
    python3 scripts/probe_code_rows.py                 # 默认 5 个代表查询
    python3 scripts/probe_code_rows.py --queries "-4217,4217,错误码 4217"

输出：每条查询一行 JSON（便于两次运行 diff），外加人类可读表格。
只读：LOG_DIR 指向临时目录，不写生产日志。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("LOG_DIR", tempfile.mkdtemp(prefix="probe_code_rows_"))

DEFAULT_QUERIES = [
    "错误码 4217 是什么",   # 裸码（A2）
    "错误码 -4217 是什么",  # 带负号
    "错误码 -4218 是什么",  # 相邻码（A1）
    "错误码 -4219 是什么",  # 相邻码（A1）
    "错误码 10928 怎么处理",  # 5 位码
]


def run_one(query: str, top_k: int) -> dict:
    from plugin.tools import HANDLERS
    raw = HANDLERS["search_qdrant"]({"query": query, "top_k": top_k},
                                    task_id="probe-code-rows")
    payload = json.loads(raw)
    hits = payload.get("hits") or []
    first = hits[0] if hits else {}
    return {
        "query": query,
        "count": len(hits),
        "chars": len(raw),
        "chunk_level": first.get("chunk_level"),
        "exact_code": first.get("exact_code"),
        "content_head": (first.get("content") or "").replace("\n", " / ")[:90],
        "source": first.get("source"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries", default=",".join(DEFAULT_QUERIES))
    ap.add_argument("--top-k", type=int, default=3)
    ap.add_argument("--json", action="store_true", help="只输出 JSON 行（供 diff）")
    args = ap.parse_args()

    rows = [run_one(q.strip(), args.top_k) for q in args.queries.split(",") if q.strip()]
    if args.json:
        for row in rows:
            print(json.dumps(row, ensure_ascii=False))
        return 0

    print("| 查询 | hits | chars | chunk_level | exact_code | 首条内容（前 90 字） |")
    print("|---|---|---|---|---|---|")
    for r in rows:
        print("| %s | %d | %d | %s | %s | %s |" % (
            r["query"], r["count"], r["chars"],
            r["chunk_level"] or "-", r["exact_code"] or "-", r["content_head"] or "-"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

