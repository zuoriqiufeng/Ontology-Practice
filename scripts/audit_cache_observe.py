#!/usr/bin/env python3
"""101(批6)：只读观测——检索缓存命中、search duration 分布、冷启动。

读 logs/usage_log_*.jsonl，不做任何写入。
"""
import glob
import json
import os
import sys


def _rows(pattern):
    out = []
    for f in sorted(glob.glob(pattern)):
        for ln in open(f, encoding="utf-8", errors="ignore"):
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.loads(ln))
            except Exception:
                continue
    return out


def _pct(vals, p):
    if not vals:
        return None
    vals = sorted(vals)
    k = max(0, min(len(vals) - 1, int(round((p / 100.0) * (len(vals) - 1)))))
    return vals[k]


def main() -> int:
    logs = sys.argv[1] if len(sys.argv) > 1 else "logs"
    rows = _rows(os.path.join(logs, "usage_log_*.jsonl"))
    if not rows:
        print("no usage logs under", logs)
        return 0
    hits = sum(1 for r in rows if str(r.get("record_type", "")).startswith("cache_hit"))
    miss = sum(1 for r in rows if str(r.get("record_type", "")).startswith("cache_miss"))
    tot = hits + miss
    print("cache: hit=%d miss=%d rate=%.1f%%" % (hits, miss, (100.0 * hits / tot) if tot else 0.0))
    dur = [int(r["duration_ms"]) for r in rows
           if r.get("tool") == "search_qdrant" and isinstance(r.get("duration_ms"), (int, float))]
    print("search duration rows=%d p50=%s p95=%s max=%s" % (
        len(dur), _pct(dur, 50), _pct(dur, 95), (max(dur) if dur else None)))
    big = [r for r in rows if r.get("tool") == "search_qdrant"
           and isinstance(r.get("out_chars"), (int, float)) and r["out_chars"] > 12000]
    print("search out_chars>12000: %d" % len(big))
    cold = [r for r in rows if "bkn_load" in str(r.get("record_type", ""))
            or r.get("tool") == "bkn_load"]
    print("bkn_load rows=%d" % len(cold))
    return 0


if __name__ == "__main__":
    sys.exit(main())