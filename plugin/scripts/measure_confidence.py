#!/usr/bin/env python3
"""measure_confidence.py — 置信度/输出体积前后对比复测（21 号 §5 统计方法的固化工具）

对 13 个 Tool 的固定用例集（50 例：9 个 _wrap() Tool 40 例 + diagnose_mechanism 2 例 + 3 个豁免 Tool 8 例）逐个调用 handler，
spy 挂钩 assess_confidence 抓取判定输入/输出，输出汇总表 + JSON 明细。
用途：任何置信度/输出体积相关改动（如 2B 校准、ContextLoader 策略调整）前后各跑一次，
对比 confidence 分布与 out_chars——**同脚本、同用例集、同环境**是对比有效性的前提。

**语料驱动用例（22 号批 4-3，2026-10-12）**：`diagnose_db_link` 内部会做 Qdrant 检索，
输出随语料增长；这些用例**不打逐用例回归阈值、也不进主聚合**（单列 `corpus_sensitive` 信息块），
否则语料正常增长（用户侧落库）会被判成门禁红。论证见 `doc/optimize/35-batch4-observability-design.md`。

用法:
  # 1) 出基线（落库，见 22 号批 1-1）
  python3 plugin/scripts/measure_confidence.py --out plugin/baselines/measure_confidence.json --label baseline

  # 2) 改动后复测 + 与基线对比（22 号批 1-2；劣化则非零退出码）
  python3 plugin/scripts/measure_confidence.py --out /tmp/conf_after.json --label after \\
      --compare plugin/baselines/measure_confidence.json --fail-on-regression

注意:
- 用例会真实调用 HANDLERS（含 search_qdrant 内部检索），耗时约 1-2 分钟；
- 脚本自带临时 LOG_DIR：测量流量不写入生产日志（数据卫生，见 43 号文档 §4）；
- Qdrant 不可达时 resolve_operation 等的内部检索静默降级，confidence 仍可测，
  但结论需注明环境差异——**payload 内的 `env` 块会记录可达性，对比时会提示环境不同**。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_DIR.parent))

# 数据卫生：测量流量走临时目录，不污染生产日志（必须在 plugin 首次导入前设置）
_MEASURE_LOG_DIR = tempfile.mkdtemp(prefix="i2bkn_measure_logs_")
os.environ["LOG_DIR"] = _MEASURE_LOG_DIR

import plugin.tools as tools  # noqa: E402

PAYLOAD_SCHEMA = 1

#: 基线对比阈值（22 号 §5「先宽后紧」：先只拦显著劣化，连续 2 周无误报再收紧）
#: 改阈值须评审——不得为了让门禁通过而放宽带（22 号 §0.4 / 26 号禁止项 1）
COMPARE_THRESHOLDS = {
    "full_ratio_drop_pp": 5.0,      # full 占比下降 > 5 个百分点 → 劣化
    "partial_ratio_rise_pp": 5.0,   # partial 占比上升 > 5 个百分点 → 劣化
    "out_chars_p90_rise_pct": 10.0,  # out_chars p90 增幅 > 10% → 劣化
    # ↓ 单例阈值（2026-10-10 补）：**p90 看不见少数用例的体量变化**
    #   —— 实测教训：某候选让 2 个用例各涨 +111/+205 字符，而 p90 前后逐字节相同（4021→4021），
    #      差点得出"这个改动没影响"的错误结论。故补逐用例对比 + 两条单例阈值。
    "per_case_decrease_pct": 10.0,   # 单例 out_chars **下降** > 10% → 判劣化（变小通常意味着丢内容）
    "per_case_increase_pct": 25.0,   # 单例**上升** > 25% → 标「需确认」（**不 fail**：解截断这类修复会合理增大输出）
}

# 固定用例集：9 Tool × schema enum 值（diagnose_mechanism 的 2 例另在 STABLE_EXTRA_CASES；改 schema enum 时同步此表，并重跑 before 基线）
CASES = [
    ("query_product", {"aspect": a}) for a in
    ["overview", "positioning", "advantages", "competitors", "all"]
] + [
    ("explain_architecture", {"topic": t}) for t in
    ["full_sync", "incremental_sync", "topology", "transaction", "all"]
] + [
    ("design_solution", {"source": s, "target": t, "scenario_hint": h}) for s, t, h in
    [("mysql", "oracle", "migration"), ("oracle", "mysql", "auto"), ("oracle", "gaussdb", "dual_active")]
] + [
    ("check_compatibility", {"source": s, "target": t}) for s, t in
    [("mysql", "oracle"), ("oracle", "dm")]
] + [
    ("list_scenarios", {"keywords": k}) for k in
    [[], ["双活"], ["大数据"]]
] + [
    ("diagnose_error", {"error_code": c}) for c in
    ["-4073", "-4002", "ORA-01555", "-4071", "YAS-02276", "ORA-99999"]
] + [
    ("get_prerequisites", {"operation": o}) for o in
    ["activate_node", "register_db", "create_rule", "start_rule", "stop_rule",
     "delete_rule", "compare_table", "failover"]
] + [
    ("resolve_relation", {"source_entity": s, "relation_type": r}) for s, r in
    # 32 号（Q27）：错误码已退出本体（码无关系可解析）→ 该例改用症状入口（同关系类型，仍考解析链路）
    [("syncrule", "all"), ("symptom:incremental_stuck", "suspected_in"),
     ("dimension:consistency", "observed_in"), ("process:iahelper", "supervises"),
     ("syncrule", "has_action")]
] + [
    ("resolve_operation", {"operation": o}) for o in
    ["start_rule", "delete_rule", "failover"]
]

#: 稳定新增用例（22 号批 4-3）：3 个豁免 Tool 中**不依赖 Qdrant 语料**的分支。
#: - search_qdrant：只取维度覆盖度报告（进程内计数，环境无关）；
#:   ⚠ 该例的 coverage 与**同进程内其它 search_qdrant 用例**共享计数——新增检索类用例会移动它，
#:     届时属"用例集变化"须重出基线（对比逻辑会以 case_id 提示）。
#: - check_action_risk：规则来自仓内 BKN 装配，确定性。
STABLE_EXTRA_CASES = [
    ("search_qdrant", {"dimension": "__report__", "tool_name": "design_solution"}),
] + [
    ("check_action_risk", {"action": a, "current_state": s}) for a, s in
    [("delete_sync_rule", "RUNNING"), ("register_db", "OFFLINE"),
     ("restart_sync_rule", "ABNORMAL"), ("", "")]
] + [
    # 54 号（裁 2＝C）：机制归因出口——症状入口（本体收窄路径）与只给码（Q27 诚实路径）各一例。
    ("diagnose_mechanism", {"entry": e}) for e in
    ["incremental_stuck", "-4073"]
]

#: 语料驱动用例（22 号批 4-3）：`diagnose_db_link` 走 `synthesize_diagnosis_knowledge`
#: 的 Qdrant 检索——输出随语料增长，**不判劣化**（数字单列）。
CORPUS_SENSITIVE_CASES = [
    ("diagnose_db_link", {"symptom": "incremental_stuck", "db_type": "oracle"}),
    ("diagnose_db_link", {"symptom": "crash_loop", "db_type": "mysql",
                          "process": "process:iatrack"}),
    ("diagnose_db_link", {"error_code": "-4073", "db_type": "auto"}),
]

ALL_CASES = CASES + STABLE_EXTRA_CASES + CORPUS_SENSITIVE_CASES


# ---- 环境戳（43 号 §5「同环境」要求）--------------------------------------

def _qdrant_reachable() -> bool:
    try:
        from plugin.config import QDRANT_HOST, QDRANT_PORT
        import socket
        with socket.create_connection((QDRANT_HOST, int(QDRANT_PORT)), timeout=1.5):
            return True
    except Exception:
        return False


def _env() -> dict:
    from plugin import config
    return {
        "python": sys.version.split()[0],
        "qdrant_reachable": _qdrant_reachable(),
        "collection": getattr(config, "QDRANT_COLLECTION", ""),
        "chunk_mode": getattr(config, "SEARCH_CHUNK_MODE", ""),
        "defer_to_hermes": getattr(config, "SEARCH_DEFER_TO_HERMES", None),
    }


# ---- 摘要与对比（22 号批 1-1 / 1-2）--------------------------------------

def _percentile(sorted_values: list, p: float):
    """最近秩法分位数（样本 <30 时调用方须自行标注——沿用 43 号 §5 口径）。"""
    if not sorted_values:
        return None
    k = int(round((p / 100.0) * (len(sorted_values) - 1)))
    return sorted_values[max(0, min(len(sorted_values) - 1, k))]


def _case_id(tool: str, args: dict) -> str:
    """用例的**稳定标识**：`tool|排序后的 args JSON`。

    刻意不用序号——序号会随 CASES 顺序调整而漂移，导致基线对比错位（把 A 的新值对到 B 的旧值）。
    """
    try:
        payload = json.dumps(args or {}, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        payload = str(args)
    return f"{tool}|{payload}"


#: 语料驱动用例的 case_id 集合（记录级标记随 run() 写入 records）
CORPUS_SENSITIVE_IDS = {_case_id(t, a) for t, a in CORPUS_SENSITIVE_CASES}


def _dist(records: list) -> dict:
    """一组记录的置信度分布与输出体积分位（主口径与语料块共用）。"""
    dist = Counter(r.get("confidence") for r in records)
    chars = sorted(r["out_chars"] for r in records if isinstance(r.get("out_chars"), int))
    return {
        "n": len(records),
        "confidence": {k: dist.get(k, 0) for k in ("full", "partial", "none", "EXC", "NO_CALL")},
        "out_chars": {
            "n": len(chars),
            "p50": _percentile(chars, 50),
            "p90": _percentile(chars, 90),
            "p99": _percentile(chars, 99),
            "max": chars[-1] if chars else None,
            "total": sum(chars) if chars else None,
            # 43 号 §5：样本 <30 不做分位数
            "percentiles_reliable": len(chars) >= 30,
        },
    }


def summarize(records: list) -> dict:
    """主口径＝**非语料驱动**用例（与 v3 的 40 例口径同源，并扩入稳定新增例）；
    语料驱动用例单列 `corpus_sensitive` 信息块（不打阈值、不进主聚合，见文件头注）。"""
    stable = [r for r in records if not r.get("corpus_sensitive")]
    corpus = [r for r in records if r.get("corpus_sensitive")]
    main = _dist(stable)
    total = main["n"]
    conf = main["confidence"]
    return {
        "total": total,
        "cases": len(CASES) + len(STABLE_EXTRA_CASES),
        "confidence": conf,
        "full_ratio": round(conf.get("full", 0) / total, 4) if total else None,
        "partial_ratio": round(conf.get("partial", 0) / total, 4) if total else None,
        "out_chars": main["out_chars"],
        "corpus_sensitive": _dist(corpus),  # 信息块（n=0 时为 0/None）
    }


def compare(baseline: dict, current: dict) -> tuple[bool, list[str]]:
    """返回 (是否劣化, 说明列表)。阈值见 COMPARE_THRESHOLDS。"""
    notes: list[str] = []
    regression = False

    b_env = baseline.get("env", {})
    c_env = current.get("env", {})
    if b_env.get("qdrant_reachable") != c_env.get("qdrant_reachable"):
        notes.append(
            f"⚠ 环境不同：baseline qdrant_reachable={b_env.get('qdrant_reachable')} "
            f"vs current {c_env.get('qdrant_reachable')} —— 结论须注明环境差异"
        )

    b, c = baseline.get("summary", {}), current.get("summary", {})
    if not b:
        return False, ["⚠ baseline 无 summary 块（旧格式？），跳过数值对比"]

    # full 占比
    bf, cf = b.get("full_ratio"), c.get("full_ratio")
    if bf is not None and cf is not None:
        drop_pp = (bf - cf) * 100
        flag = drop_pp > COMPARE_THRESHOLDS["full_ratio_drop_pp"]
        notes.append(f"{'✗' if flag else '✓'} full 占比 {bf:.1%} → {cf:.1%}"
                     f"（变化 {cf - bf:+.2%}，阈值 -{COMPARE_THRESHOLDS['full_ratio_drop_pp']}pp 以内）")
        regression |= flag

    # partial 占比
    bp, cp = b.get("partial_ratio"), c.get("partial_ratio")
    if bp is not None and cp is not None:
        rise_pp = (cp - bp) * 100
        flag = rise_pp > COMPARE_THRESHOLDS["partial_ratio_rise_pp"]
        notes.append(f"{'✗' if flag else '✓'} partial 占比 {bp:.1%} → {cp:.1%}"
                     f"（变化 {cp - bp:+.2%}，阈值 +{COMPARE_THRESHOLDS['partial_ratio_rise_pp']}pp 以内）")
        regression |= flag

    # out_chars p90
    b90 = (b.get("out_chars") or {}).get("p90")
    c90 = (c.get("out_chars") or {}).get("p90")
    if b90 and c90:
        rise = (c90 - b90) / b90 * 100
        flag = rise > COMPARE_THRESHOLDS["out_chars_p90_rise_pct"]
        notes.append(f"{'✗' if flag else '✓'} out_chars p90 {b90} → {c90}"
                     f"（{rise:+.1f}%，阈值 +{COMPARE_THRESHOLDS['out_chars_p90_rise_pct']}% 以内）")
        regression |= flag

    # 异常用例（保留记录，不武断判劣化）
    exc = c.get("confidence", {}).get("EXC", 0) + c.get("confidence", {}).get("NO_CALL", 0)
    if exc:
        notes.append(f"⚠ 本次有 {exc} 例异常/未捕获（EXC/NO_CALL），逐例排查后再看分布")

    # ── 逐用例对比（2026-10-10 补）────────────────────────────────────
    # 为什么需要：p90 是**分位数**，少数用例的体量变化可能完全不移动它。
    # 实测教训：某候选让 2 个用例各涨 +111/+205 字符，而 p90 前后逐字节相同（4021→4021）。
    # 因此这里**总是**把变化的用例列出来，并对单例设两条阈值。
    dec_limit = COMPARE_THRESHOLDS["per_case_decrease_pct"]
    inc_limit = COMPARE_THRESHOLDS["per_case_increase_pct"]
    b_cases = {r.get("case_id"): r for r in baseline.get("records", []) if r.get("case_id")}
    c_cases = {r.get("case_id"): r for r in current.get("records", []) if r.get("case_id")}

    if not b_cases:
        notes.append("⚠ baseline 无 case_id（旧格式基线）——逐用例对比跳过；建议重出基线")
    else:
        only_b = sorted(set(b_cases) - set(c_cases))
        only_c = sorted(set(c_cases) - set(b_cases))
        if only_b or only_c:
            notes.append(f"⚠ **用例集与基线不一致**：仅基线有 {len(only_b)} 例、仅本次有 {len(only_c)} 例"
                         "——对比有效性受损，须重出基线（改 CASES 后必须重跑 before）")

        compared = 0
        changed = []
        corpus_info = []
        for cid in sorted(set(b_cases) & set(c_cases)):
            ov = b_cases[cid].get("out_chars")
            nv = c_cases[cid].get("out_chars")
            if c_cases[cid].get("corpus_sensitive") or b_cases[cid].get("corpus_sensitive"):
                # 语料驱动用例：只报数字，不判劣化（输出随 Qdrant 语料增长——22 号批 4-3）
                if ov != nv:
                    corpus_info.append((cid, ov, nv))
                continue
            compared += 1
            if ov == nv:
                continue
            pct = ((nv - ov) / ov * 100) if isinstance(ov, int) and isinstance(nv, int) and ov else None
            changed.append((cid, ov, nv, pct))

        if corpus_info:
            notes.append(f"· 语料驱动用例 {len(corpus_info)} 例 out_chars 变化（**不判劣化**："
                         "输出随 Qdrant 语料增长，见 22 号批 4-3）：")
            for cid, ov, nv in corpus_info:
                notes.append(f"    · {cid[:78]}  {ov} → {nv}")

        if not changed:
            notes.append(f"✓ 逐用例 out_chars：**{compared} 例（非语料驱动）全部持平**")
        else:
            notes.append(f"⚠ 逐用例 out_chars：**{len(changed)} 例变化**（p90 可能看不见，故逐条列出）")
            for cid, ov, nv, pct in changed:
                tag = "·"
                if pct is not None and pct < -dec_limit:
                    tag = "✗ 劣化"
                    regression = True
                elif pct is not None and pct > inc_limit:
                    tag = f"⚠ 需确认（>{inc_limit:g}%，可能是刻意解截断/扩内容，请在候选文档里说明）"
                ps = f"{pct:+.1f}%" if pct is not None else "n/a"
                notes.append(f"    {tag} {cid[:78]}  {ov} → {nv}（{ps}）")

    return regression, notes


def run(out_path: str, label: str, compare_path: str | None = None,
        fail_on_regression: bool = False) -> int:
    records: list[dict] = []
    _orig = tools.assess_confidence
    buf: list[dict] = []

    def _spy(result, args, tool_name=None):
        conf, gaps = _orig(result, args, tool_name)
        buf.append({
            "tool": tool_name,
            "confidence": conf,
            "gaps": gaps,
            "result_chars": len(json.dumps(result, ensure_ascii=False, default=str)),
            "args": {k: v for k, v in (args or {}).items() if k != "task_id"},
        })
        return conf, gaps

    tools.assess_confidence = _spy
    try:
        for tool, args in ALL_CASES:
            buf.clear()
            cid = _case_id(tool, args)
            out_chars = None
            exc = None
            try:
                out = tools.HANDLERS[tool](dict(args))
                out_chars = (len(out) if isinstance(out, str)
                             else len(json.dumps(out, ensure_ascii=False, default=str)))
            except Exception as e:  # 单例失败不拖垮整体（环境问题如 Qdrant 不可达）
                exc = str(e)
            if buf:
                for r in buf:
                    r["case_id"] = cid
                    r["out_chars"] = out_chars
                    if cid in CORPUS_SENSITIVE_IDS:
                        r["corpus_sensitive"] = True
                records.extend(buf)
            if exc or not buf:
                rec = {
                    "case_id": cid,
                    "tool": tool,
                    "confidence": "EXC" if exc else "NO_CALL",
                    "gaps": [exc] if exc else ["assess_confidence 未被调用（非 _wrap 路径？）"],
                    "args": args,
                    "out_chars": out_chars,
                }
                if cid in CORPUS_SENSITIVE_IDS:
                    rec["corpus_sensitive"] = True
                records.append(rec)
    finally:
        tools.assess_confidence = _orig

    summary = summarize(records)
    payload = {
        "schema": PAYLOAD_SCHEMA,
        "label": label,
        "cases": len(ALL_CASES),
        "thresholds": COMPARE_THRESHOLDS,
        "env": _env(),
        "summary": summary,
        "records": records,
    }
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    by_tool: dict[str, list] = {}
    for r in records:
        by_tool.setdefault(r["tool"], []).append(r)
    print(f"[{label}] 用例 {len(ALL_CASES)}，明细已写入 {out_path}")
    print(f"环境: python {payload['env']['python']}｜qdrant_reachable={payload['env']['qdrant_reachable']}\n")
    print(f"{'tool':22s} {'n':>3s} {'full':>5s} {'partial':>8s} {'none':>5s}  平均gaps")
    for t, rs in by_tool.items():
        full = sum(1 for r in rs if r["confidence"] == "full")
        part = sum(1 for r in rs if r["confidence"] == "partial")
        none = sum(1 for r in rs if r["confidence"] == "none")
        n_gaps = sum(len(r.get("gaps", [])) for r in rs)
        print(f"{t:22s} {len(rs):3d} {full:5d} {part:8d} {none:5d}  {n_gaps / max(len(rs), 1):.1f}")
    oc = summary["out_chars"]
    print(f"\n合计: full {summary['confidence']['full']}/{summary['total']}"
          f"｜out_chars p50={oc['p50']} p90={oc['p90']} p99={oc['p99']} max={oc['max']}")

    if not compare_path:
        return 0

    baseline = json.loads(Path(compare_path).read_text(encoding="utf-8"))
    regression, notes = compare(baseline, payload)
    print(f"\n=== 与基线对比（{compare_path}，label={baseline.get('label')}）===")
    for n in notes:
        print("  " + n)
    print(f"\n结论: {'❌ 检测到劣化' if regression else '✅ 无劣化'}")
    if regression and fail_on_regression:
        return 1
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="置信度/输出体积前后对比复测")
    ap.add_argument("--out", default="/tmp/conf_measure.json", help="JSON 明细输出路径")
    ap.add_argument("--label", default="", help="标签（如 baseline/after），写入 JSON 供对比区分")
    ap.add_argument("--compare", default=None,
                    help="与给定基线 JSON 对比（22 号批 1-2）")
    ap.add_argument("--fail-on-regression", action="store_true",
                    help="有劣化时以非零退出码结束（需 --compare）")
    ns = ap.parse_args(argv)
    if ns.fail_on_regression and not ns.compare:
        ap.error("--fail-on-regression 需配合 --compare 使用")
    return run(ns.out, ns.label, compare_path=ns.compare,
               fail_on_regression=ns.fail_on_regression)


if __name__ == "__main__":
    raise SystemExit(main())
