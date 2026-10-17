#!/usr/bin/env python3
"""ontology_probe.py — 本体使用台账**现场探针**（69 号 §3；只读，不污染生产日志）

用途：插件的日志现在够不够回答「本体在哪个阶段被用、是否真起作用」？
本脚本用 13 个 Tool 的**固定电池**跑一遍真实调用（真入口 HANDLERS，带 task_id），
把落盘的台账事件原样打出来，再给一份 --ontology 同款汇总。

与 trajectory_report.py --ontology 的分工：
- 那个读**真实会话**累积的 logs/（观测期用）；
- 本脚本现跑一份**合成样本**（换环境自检、改埋点后回归看字段是否还在）。

纪律：LOG_DIR 指向临时目录（**绝不写生产 logs/**）；不联网（Qdrant 不可达时相应行会降级）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCRIPTS = ROOT / "plugin" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

TASK = "probe-ontology-0001"

#: 13 个 Tool 的固定电池（入参取各 Tool 的典型形态；不为探针改任何生产默认值）
BATTERY = [
    ("query_product", {"aspect": "overview"}),
    ("explain_architecture", {"topic": "all"}),
    ("design_solution", {"source": "oracle", "target": "mysql"}),
    ("check_compatibility", {"source": "oracle", "target": "mysql"}),
    ("list_scenarios", {}),
    ("diagnose_error", {"error_code": "4050", "log_source": "ialoader"}),
    ("get_prerequisites", {"operation": "创建规则"}),
    ("resolve_relation", {"source_entity": "process:iatrack", "relation_type": "all"}),
    ("resolve_operation", {"operation": "创建规则"}),
    ("search_qdrant", {"query": "proxy 集群部署 helper 离线 重连", "top_k": 3}),
    ("diagnose_db_link", {"symptom": "连接失败", "db_type": "oracle"}),
    ("check_action_risk", {"action": "delete_sync_rule", "current_state": "RUNNING"}),
    ("diagnose_mechanism", {"entry": "dimension:resource",
                            "observations": ["Killed process 58998 (java)"]}),
]

#: P3 补充：resolve_relation 的各条**图出口**分支（单跳／多跳／闭包／影响面／诊断路径／进程链）。
#: 单独一轮而不是并进 BATTERY，是为了不改变「13 个 Tool 各一次」这个基准口径。
GRAPH_BATTERY = [
    ("resolve_relation", {"source_entity": "process:iatrack", "relation_type": "all"}),
    ("resolve_relation", {"source_entity": "process:iatrack", "relation_type": "feeds"}),
    ("resolve_relation", {"source_entity": "syncrule", "relation_type": "all", "depth": 2}),
    ("resolve_relation", {"source_entity": "symptom:incremental_stuck",
                          "relation_type": "diagnosis_path"}),
    ("resolve_relation", {"source_entity": "process:iatrack", "relation_type": "process_chain"}),
    ("resolve_relation", {"source_entity": "process:iatrack", "relation_type": "closure"}),
    ("resolve_relation", {"source_entity": "process:iatrack", "relation_type": "impact"}),
    # diagnose_error 的两个诊断轴：-4002 有可信官方含义（本体接上），4050 没有（落 unknown）
    ("diagnose_error", {"error_code": "-4002"}),
    ("diagnose_error", {"error_code": "4050"}),
]


def run_battery(log_dir: Path) -> list[dict]:
    os.environ["LOG_DIR"] = str(log_dir)
    from plugin import trajectory, usage_log      # noqa: E402  （必须在 LOG_DIR 落定后导入）
    import importlib                              # noqa: E402
    importlib.reload(trajectory)
    importlib.reload(usage_log)
    from plugin.tools import HANDLERS, _init       # noqa: E402
    _init()
    for tool, args in BATTERY + GRAPH_BATTERY:
        try:
            HANDLERS[tool](dict(args), task_id=TASK)
        except Exception as exc:                   # 探针不因单点失败中断
            print(f"  ! {tool} 调用异常：{type(exc).__name__}: {exc}", file=sys.stderr)
    events: list[dict] = []
    for f in sorted((log_dir / "trajectories").glob("trajectory_*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))
    return events


def show(events: list[dict]) -> None:
    keys = ("stage", "stages", "origin", "sources", "bkn_read", "bkn_used", "bkn_dropped",
            "used", "dropped", "cold", "cold_files",
            # P3：图路径消耗
            "graph_branches", "graph_edges", "graph_ops",
            "paths_considered", "paths_id_considered", "paths_used", "paths_shape_gap")
    for e in events:
        ev = e.get("event")
        if ev == "ontology_use":
            payload = {k: e[k] for k in keys if k in e}
            if e.get("reads"):
                payload["reads"] = [r.get("file") for r in e["reads"]]
            print(f"[ontology_use] {e.get('tool'):<22} {json.dumps(payload, ensure_ascii=False)}")
    for e in events:
        if e.get("kind") == "event" and e.get("event") in (
                "mech_candidates", "answer_source", "bkn_load", "source_error", "source_miss"):
            payload = {k: v for k, v in e.items()
                       if k not in ("task_id", "seq", "ts", "kind", "event", "bkn_version")}
            print(f"[{e['event']}] {json.dumps(payload, ensure_ascii=False)[:400]}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="本体使用台账现场探针（69 号；只读）")
    ap.add_argument("--json", action="store_true", help="输出原始事件 JSON 数组")
    ap.add_argument("--keep", action="store_true", help="保留临时日志目录并打印路径")
    ns = ap.parse_args(argv)

    tmp = Path(tempfile.mkdtemp(prefix="bkn-ontology-probe-"))
    events = run_battery(tmp)
    if ns.json:
        print(json.dumps(events, ensure_ascii=False, indent=1))
    else:
        show(events)
        import trajectory_report                      # noqa: E402
        print()
        trajectory_report.render_ontology(trajectory_report.aggregate_ontology(events))
    if ns.keep:
        print(f"\n日志目录（--keep）：{tmp}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
