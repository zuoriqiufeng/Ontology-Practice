#!/usr/bin/env python3
"""graph_metrics.py — 图结构量取数与基线对比（22 号批 1-1 / 1-2）

结构量的"不变量"是**只增不减**（16 号 §5 不变量 2 口径）：新增边/节点属正常演进，
减少则需要解释（可能是误删边、命名空间写错导致边静默未入图、或 files 被改动）。

用法:
  # 打印当前结构量
  python3 plugin/scripts/graph_metrics.py

  # 与基线对比（减少即非零退出码）
  python3 plugin/scripts/graph_metrics.py --compare plugin/baselines/graph.json --fail-on-regression

注意:
- 边数由 RelationTraverser 从 bkn/relations/*.bkn 实时构建，与运行时同源（不是另算一套）；
- `ingraph_relation_sections` 单独按 `**关系类型**:` 行计数——它反映"段级"数量，
  与"边数"不同（一个段可通过映射规则区展开成多条边）。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = PLUGIN_DIR.parent
sys.path.insert(0, str(REPO_ROOT))

#: 只增不减的指标（减少即劣化）
MONOTONIC_METRICS = (
    "nodes",
    "edges",
    "relation_type_count",
    "ingraph_relation_sections",
    "constrained_by_edges",
)


def _ingraph_relation_sections() -> int | None:
    """`**关系类型**:` 行计数（段级，非边级）。用 grep 保持与文档口径一致。"""
    try:
        out = subprocess.run(
            ["grep", "-h", r"\*\*关系类型\*\*:", *map(str, sorted((REPO_ROOT / "bkn" / "relations").glob("*.bkn")))],
            capture_output=True, text=True, check=False,
        )
        return len([ln for ln in out.stdout.splitlines() if ln.strip()])
    except Exception:
        return None


def measure() -> dict:
    from plugin.relations import RelationTraverser
    traverser = RelationTraverser()
    nodes = set(traverser.graph.keys())
    by_type: Counter = Counter()
    edges = 0
    for _src, rels in traverser.graph.items():
        for rel, targets in rels.items():
            by_type[rel] += len(targets)
            edges += len(targets)
            nodes.update(targets)
    return {
        "nodes": len(nodes),
        "edges": edges,
        "relation_type_count": len(RelationTraverser.RELATION_TYPES),
        "ingraph_relation_sections": _ingraph_relation_sections(),
        "constrained_by_edges": by_type.get("constrained_by", 0),
        "edges_by_type": dict(sorted(by_type.items())),
    }


def compare(baseline: dict, current: dict) -> tuple[bool, list[str]]:
    notes: list[str] = []
    regression = False
    b = baseline.get("metrics", {})
    for key in MONOTONIC_METRICS:
        bv, cv = b.get(key), current.get(key)
        if bv is None or cv is None:
            notes.append(f"⚠ {key}: 基线或当前缺失（{bv} vs {cv}），跳过")
            continue
        if cv < bv:
            regression = True
            notes.append(f"✗ {key} 减少：{bv} → {cv}（不变量为只增不减，需解释）")
        elif cv > bv:
            notes.append(f"✓ {key} 增加：{bv} → {cv}（合规）")
        else:
            notes.append(f"✓ {key} 持平：{cv}")
    return regression, notes


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="图结构量取数与基线对比")
    ap.add_argument("--compare", default=None, help="基线 JSON 路径（22 号批 1-2）")
    ap.add_argument("--fail-on-regression", action="store_true",
                    help="有减少时以非零退出码结束（需 --compare）")
    ap.add_argument("--out", default=None, help="把当前结构量写入 JSON（用于更新基线）")
    ns = ap.parse_args(argv)
    if ns.fail_on_regression and not ns.compare:
        ap.error("--fail-on-regression 需配合 --compare 使用")

    current = measure()
    print(f"nodes={current['nodes']} edges={current['edges']} "
          f"relation_types={current['relation_type_count']} "
          f"ingraph_sections={current['ingraph_relation_sections']} "
          f"constrained_by={current['constrained_by_edges']}")

    if ns.out:
        Path(ns.out).write_text(
            json.dumps({"schema": 1, "kind": "measured", "metrics": current},
                       ensure_ascii=False, indent=1),
            encoding="utf-8")
        print(f"已写入 {ns.out}")

    if not ns.compare:
        return 0

    baseline = json.loads(Path(ns.compare).read_text(encoding="utf-8"))
    regression, notes = compare(baseline, current)
    print(f"\n=== 与基线对比（{ns.compare}，measured_at={baseline.get('measured_at')}）===")
    for n in notes:
        print("  " + n)
    print(f"\n结论: {'❌ 结构量减少' if regression else '✅ 无减少'}")
    return 1 if (regression and ns.fail_on_regression) else 0


if __name__ == "__main__":
    raise SystemExit(main())
