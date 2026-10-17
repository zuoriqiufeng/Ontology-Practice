#!/usr/bin/env python3
"""m5_case_replay.py — 29 号批 M-5：4 案例回放基线（判据见 29 号 §6）

把 4 个案例的入口症状喂给**现有链路**，记录两层的结论：

1. **机制级**（29 号 §6 的第一优先判据：候选集是否含**真因机制**）——机制层尚未落地（M-1 卡 Q23/Q26），
   故预期 0/4；本脚本把它**显式记为 0/4 并说明原因**，不假装能测。
2. **路由级**（现有能力能给出的最好结果）：入口是否被识别（未登记码 → `{}`）、
   是否路由到正确的**进程/维度**、是否给出 Skill 或检索指引、以及**该说不知道时是否说了不知道**。

**为什么不走完整 handler**：`diagnose_error_handler` 在上下文不足时会调 Qdrant 兜底（需要网络与嵌入模型），
回放要的是**本体侧确定性结果**——故取 `plugin/tools._extract_bkn_context`（21→25 号后它就是"常量 + 边"的组装点）
与 `RelationTraverser`，与 handler 的本体段一致；Qdrant 段单独标注为"未测（需现场）"。

用法:
  python3 scripts/m5_case_replay.py                    # 在**当前仓库**上跑（before）
  python3 scripts/m5_case_replay.py --root /tmp/c03drill2   # 在隔离副本上跑（after）

退出码: 0（本脚本只测量，不作门禁）
依据: doc/_archived/optimize-plans/29-diagnosis-mechanism-layer.md §6/§7 M-5；报告 doc/_archived/optimize-plans/29-m5-case-replay-baseline.md
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

#: 4 案例（入口症状取自 29 号 §6 表；真因机制与预期进程照抄该表）
CASES = [
    {"id": "CASE-0002", "entry": "4021", "kind": "code",
     "true_mechanism": "upstream_busy_wait_under_backpressure + resource_exhaustion_cascade + single_point_fail_stop",
     "expect": None, "note": "4021 是规则状态码（非错误码），本体未登记状态码"},
    {"id": "CASE-0002-alt", "entry": "incremental_stuck", "kind": "symptom",
     "true_mechanism": "同上（同案的症状入口）", "expect": "process:iatrack", "note": "症状入口是否路由到源端解析"},
    {"id": "CASE-0003", "entry": "4050", "kind": "code",
     "true_mechanism": "stale_state_after_change（放大为 single_point_fail_stop）",
     "expect": None, "note": "4050 是规则状态码（非错误码）"},
    {"id": "报告D1", "entry": "4073", "kind": "code",
     "true_mechanism": "control_plane_desync（另有别名错配，属知识层缺陷）",
     "expect": None, "note": "用户口语入口「4073」（无负号）；**Q27 后只给码不路由**——正确行为是明说不知道（裁 1b 重新定基）"},
    {"id": "报告D1-dash", "entry": "-4073", "kind": "code",
     "true_mechanism": "同上", "expect": None, "note": "规范码形态；**Q27 后同 D1**——只给码不路由"},
    {"id": "报告D2", "entry": "incremental_stuck", "kind": "symptom",
     "true_mechanism": "未归因（案例未结）", "expect": "process:iatrack", "note": "停在'找到可疑规则但判不了'"},
]


def run(root: Path) -> list:
    # 必须按**包成员**导入：`plugin/tools.py` 用相对导入（`from .resolver import …`），
    # 以顶层 `import tools` 进会报 "attempted relative import with no known parent package"（踩过）。
    sys.path.insert(0, str(root))
    import plugin.tools as tools  # noqa: PLC0415  （本体侧组装点）

    tools._init()
    rows = []
    for c in CASES:
        if c["kind"] == "code":
            # 与 handler 同序：先同址别名（语义别名优先），再格式归一（4073 → -4073）。
            # 不做这一步会把用户口语入口「4073」误报为未登记（踩过）。
            syn = tools._resolver.resolve_synonym(c["entry"])
            norm = tools._resolver.normalize_error_code(syn)
            ctx = tools._extract_bkn_context(norm) or {}
            procs = ctx.get("suspected_process") or []
            dims = ctx.get("dimensions") or []
            needs = ctx.get("needs") or []
            aliases = ctx.get("aliases") or []
            registered = bool(ctx)
            # 裁 1b（2026-10-13）：**Q27 后的诚实形态**是「dimension:unknown ＋ needs 非空」——
            # 只给码（无消息文本）时系统明说不知道并要求消息文本/日志来源，**这就是**诚实兜底。
            # 旧判据「未登记即诚实」已过期（Q27 后码走语义规则，ctx 恒非空 ⇒ 该判据无判别力）。
            unknown = (not registered) or (dims == ["dimension:unknown"] and bool(needs))
            entry_display = f"{c['entry']}→{norm}" if norm != c["entry"] else c["entry"]
        else:
            node = f"symptom:{c['entry']}"
            procs = tools._traverser.get_targets(node, "suspected_in")
            dims = tools._traverser.get_classes_for_symptom(node)
            aliases = []
            registered = bool(procs or dims)
            unknown = not registered
            entry_display = c["entry"]
        hit = None
        if c["expect"]:
            hit = c["expect"] in (procs or []) or c["expect"] in (dims or [])
        rows.append({
            "id": c["id"], "entry": entry_display, "kind": c["kind"],
            "registered": registered, "processes": procs, "dimensions": dims, "aliases": aliases,
            "routed_to_expected": hit, "stated_unknown": unknown, "note": c["note"],
            "true_mechanism": c["true_mechanism"],
        })
    return rows


#: 机制级用例（裁 1c：**带观测**）——观测逐字取自**库内** bug-analysis 原文；
#: expect_mechanisms 只用**现行本体**的机制名。
#: 带 requires_class 的用例在其类**尚未落盘**时**不计入分母**（避免把「类还没落地」读成「召回失败」）。
MECH_CASES = [
    {"id": "CASE-0004", "entry": "dimension:state_machine",
     "observations": ["SvcManager service [track:1033] online, but process not found"],
     "expect_mechanisms": ["control_plane_desync"],
     "source": "doc/process/bug-analysis/CASE-0004-*.md §1（同一行内两断言互相否证）"},
    {"id": "CASE-0005", "entry": "dimension:resource",
     "observations": ["Killed process 58998 (java)", "SocketException: Connection reset",
                      "failed to close transfer client: timeout after 20000 milliseconds",
                      "export update stage: stop, state: 4045"],
     "expect_mechanisms": ["resource_exhaustion_cascade"],
     "source": "doc/process/bug-analysis/CASE-0005-*.md §1 的四步日志表"},
    {"id": "CASE-0006", "entry": "dimension:state_machine",
     "observations": ["java.lang.NoSuchMethodError: com.fasterxml.jackson.core.base.ParserMinimalBase.<init>(StreamReadConstraints)",
                      "Exception in thread dataConvert-<uuid>-thread-N"],
     "expect_mechanisms": ["single_point_fail_stop"],
     "source": "doc/process/bug-analysis/CASE-0006-*.md 异常原文"},
    {"id": "CASE-0007", "entry": "dimension:log_readable",
     "observations": ["fullsync point 保存进 track point: binlog.003621:480978618, GTID 358316266",
                      "track 实际启动 start lsn: binlog.001003:447854474, GTID 358315570"],
     "expect_mechanisms": ["position_regression"], "requires_class": "position_regression",
     "source": "doc/process/bug-analysis/CASE-0007-*.md §1"},
]


def mechanism_metric(root) -> dict:
    """机制级：**有观测时**候选集是否含真因机制（29 号 §6 的第一优先判据）。

    裁 1c（2026-10-13）：旧口径只给码 ⇒ 本体无收窄（候选＝全量）⇒ 召回恒 100%、无判别力；
    改为**带观测**的用例，指标语义＝「**有观测时**是否收敛到真因机制」。
    带 requires_class 的用例在其类未落盘时**不计入分母**（单列 pending）。
    """
    sys.path.insert(0, str(root))
    import plugin.tools as tools  # noqa: PLC0415
    tools._init()
    nodes = set(tools._traverser.graph)
    hit, total, pending, rows = 0, 0, [], []
    for c in MECH_CASES:
        need = c.get("requires_class")
        if need and need not in nodes:
            pending.append("%s（待 %s 落盘）" % (c["id"], need))
            continue
        out = str(tools.diagnose_mechanism({"entry": c["entry"],
                                            "observations": c["observations"]}))
        ok = all(m in out for m in c["expect_mechanisms"])
        hit += 1 if ok else 0
        total += 1
        rows.append({"id": c["id"], "ok": ok, "expect": c["expect_mechanisms"]})
    return {"hit": hit, "total": total, "pending": pending, "rows": rows}


def metrics(rows: list, mech: dict = None) -> dict:
    """三个指标。**定义随契约变**（metric_defs / caveats 见 floor 文件）。

    mechanism 由 mechanism_metric() 计算（裁 1c：带观测的用例，不再是常量 0）。
    """
    routed = [r for r in rows if r["routed_to_expected"] is not None]
    mech = mech or {"hit": 0, "total": 0}
    return {
        "mechanism": {"hit": mech["hit"], "total": mech["total"]},
        "routing": {"hit": sum(1 for r in routed if r["routed_to_expected"]), "total": len(routed)},
        "honest_unknown": {"hit": sum(1 for r in rows if r["stated_unknown"]), "total": len(rows)},
    }


def scale_hint(root: Path) -> str:
    # 非门禁提示：回放用例数 vs 本体规模（对照项 G-12）。
    # 为什么不作门禁：任何用例数下限都是判据变更——floor 是裁定产物
    # （m5_replay_floor.json 的 caveats 明写「要改 floor 必须先裁定」；本脚本只做比较）。
    # 故本函数只打印，不参与 --check 的判定、不影响退出码。
    # 为什么用 .bkn 文件数而不是节点/边：官方结构量由 plugin/scripts/graph_metrics.py 回答
    # （203 / 223 / 29）；本进程内的 _traverser.graph 只是边映射子图（实测 99 / 133），
    # 两套数字同源不同层，混用会造出第二套结构量——故此处只用无歧义的文件数。
    bkn_dir = root / "bkn"
    n_bkn = len(list(bkn_dir.rglob("*.bkn"))) if bkn_dir.is_dir() else 0
    return ("  用例规模提示（非门禁）：回放用例 %d 条 ＋ 机制带观测 %d 条；本体 .bkn %d 个"
            "｜数量门槛若入 floor 即判据变更，须先裁定（见 doc/optimize/56-open-items.md）"
            % (len(CASES), len(MECH_CASES), n_bkn))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="29 号 M-5：4 案例回放基线 / floor 检查（2026-10-13 裁定「1 B」接线）")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--json", action="store_true", help="输出 JSON（默认打印表）")
    ap.add_argument("--check", action="store_true",
                    help="对照 floor 检查**不许更差**（退步则退出码 1；判据取自裁定「1 B」）")
    ap.add_argument("--floor", default=str(Path(__file__).resolve().parent / "m5_replay_floor.json"),
                    help="floor 文件（默认 scripts/m5_replay_floor.json）")
    ns = ap.parse_args(argv)
    # 数据卫生（43 号 §4 第 5 条铁律）：本脚本会调 `diagnose_mechanism` ⇒ **必须先隔离 `LOG_DIR`**，
    # 否则每次回放都会往**生产** usage_log 写 MECH_CASES 条记录（2026-10-14 实测：4 条 `task_id=None`，
    # 由 gate ⑤ 每次运行产生）。用 setdefault：外部显式设了 LOG_DIR 就尊重外部。
    os.environ.setdefault("LOG_DIR", tempfile.mkdtemp(prefix="m5-replay-"))
    rows = run(Path(ns.root).expanduser().resolve())
    mech = mechanism_metric(Path(ns.root).expanduser().resolve())
    m = metrics(rows, mech)
    if ns.check:
        fp = Path(ns.floor)
        if not fp.is_file():
            print("✗ floor 文件不存在：" + str(fp), file=sys.stderr)
            return 2
        floor = json.loads(fp.read_text(encoding="utf-8"))
        lows, parts = [], []
        for k in ("mechanism", "routing", "honest_unknown"):
            cur = m[k]
            lo = (floor.get("floors") or {}).get(k)
            ok = lo is not None and cur["hit"] >= lo
            parts.append("%s %d/%d（floor %s）%s" % (k, cur["hit"], cur["total"], lo, "✓" if ok else "✗"))
            if not ok:
                lows.append(k)
        print("  回放 floor 对照：" + "｜".join(parts))
        if mech.get("pending"):
            print("  未计入分母（类未落盘）：" + "；".join(mech["pending"]))
        if lows:
            print("  ✗ 退步：" + repr(lows) + "（判据＝不许更差；要改 floor 须先裁定）", file=sys.stderr)
            return 1
        print(scale_hint(Path(ns.root).expanduser().resolve()))
        print("  判据＝**不许更差**（不做目标阈值）；口径（已按裁 1b 重定基到 Q27 后契约）见 doc/optimize/43-remaining-work.md §21")
        return 0
    if ns.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return 0
    print(f"回放根：{ns.root}")
    print(f"{'案例':16s}{'入口':18s}{'识别':4s}{'进程候选':28s}{'维度':22s}{'路由':6s}{'说不知道':8s}")
    for r in rows:
        print(f"{r['id']:16s}{r['entry']:18s}{'✓' if r['registered'] else '✗':4s}"
              f"{(','.join(r['processes']) or '—'):28s}{(','.join(r['dimensions']) or '—'):22s}"
              f"{('命中' if r['routed_to_expected'] else ('—' if r['routed_to_expected'] is None else '未命中')):6s}"
              f"{'是' if r['stated_unknown'] else '否':8s}")
    routed = [r for r in rows if r["routed_to_expected"] is not None]
    print(f"\n路由级命中：{sum(1 for r in routed if r['routed_to_expected'])}/{len(routed)}"
          f"｜诚实兜底（Q27 形态：明说不知道 ＋ 要消息文本）：{sum(1 for r in rows if r['stated_unknown'])}/{len(rows)}"
          f"｜机制级：{m['mechanism']['hit']}/{m['mechanism']['total']}"
          f"（**带观测**用例：候选集是否含真因机制；裁 1c）")
    print(scale_hint(Path(ns.root).expanduser().resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
