#!/usr/bin/env python3
"""pending_status.py — 待审区清单与账本校验（28 号批 R-1）

输出待审清单（按挂置天数排序、超期标红），并校验：
- I23 账本结构：每条记录 `by` / `reason` 非空，`decision` 合法（裁决 approve/reject/supersede + 事件 apply/ruling）
- I22 状态一致性：`status` 与账本最新 decision 相符（pending 的候选不得已生效）
- I24 留档：rejected / superseded 的候选目录不得被删除
- 目录契约：candidate.json 的 id 与目录名一致、必备字段齐备

用法:
  python3 scripts/pending_status.py           # 人读清单
  python3 scripts/pending_status.py --json    # 机器可读（供其它脚本消费）
  python3 scripts/pending_status.py --strict  # 结构问题以非零退出码结束

退出码：0 正常；1 有结构性问题（仅 --strict 时非零）

依据: doc/optimize/28-pending-review-loop.md §2（目录契约）/ §4（提醒机制）/ §5（不变量 I21–I25）
挂载: scripts/gate.sh 的 ⓪ 步（提醒项，不阻断门禁）
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PENDING_DIR = REPO_ROOT / "doc" / "optimize" / "pending"

VALID_DECISIONS = {"approve", "reject", "supersede"}
#: 账本事件（27 号批 V-4：`apply` 是**事件**不是裁决——`pending_apply` 落盘后追加，记下生效版本号；
#: 28 号 §2.2 扩展：`ruling` 记**口径裁定**，`id` 可为 `—`，必带 `ruling` 编号）。
#: 裁决类事件才参与 I22 的状态一致性判定，见 `_latest_decision`）
LEDGER_EVENTS = VALID_DECISIONS | {"apply", "ruling"}
REQUIRED_CANDIDATE_FIELDS = ("id", "created_at", "status", "target_dimension",
                             "landing", "hypothesis", "evidence", "changes",
                             "gates", "rollback", "risk")
GATE_KEYS = ("structure", "regression", "evidence")
#: 证据强度分级（24 号 D1；26 号 S4 证据门用它判"够不够硬"）
VALID_STRENGTH = {"strong", "medium", "medium+", "weak"}

#: 软默认（30 号 §2.2 Q22）：超过该天数标红，但**不自动过期、不自动丢弃**
STALE_DAYS = 14

#: payload 下的落盘前备份目录（与 `pending_apply.PRE_APPLY_DIRNAME` 同名同义）——同文件冲突检查跳过它
PRE_APPLY = ".pre-apply"

#: 允许候选触及的生效位置前缀——**权威定义在 `pending_apply.ALLOWED_PREFIXES`**，
#: 此处仅用于提前报警；测试 `test_pending_apply.TestWhitelistSingleSource` 钉住两者相等。
ALLOWED_PREFIXES = ("bkn/", "plugin/", "skill/", "doc/update/")


def _ledger_path() -> Path:
    return PENDING_DIR / "ledger.jsonl"


def _load_ledger() -> tuple[list[dict], list[str]]:
    problems: list[str] = []
    ledger = _ledger_path()
    if not ledger.exists():
        return [], [f"账本不存在：{ledger}"]
    entries: list[dict] = []
    for lineno, line in enumerate(ledger.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as exc:
            problems.append(f"ledger.jsonl:{lineno} JSON 解析失败：{exc}")
            continue
        if not isinstance(rec, dict):
            problems.append(f"ledger.jsonl:{lineno} 不是对象")
            continue
        for field in ("id", "at", "decision", "by", "reason"):
            if not str(rec.get(field, "")).strip():
                problems.append(f"ledger.jsonl:{lineno} 缺非空字段 `{field}`（I23）")
        if rec.get("decision") not in LEDGER_EVENTS:
            problems.append(f"ledger.jsonl:{lineno} decision 非法：{rec.get('decision')!r}")
        if rec.get("decision") == "apply" and not str(rec.get("version_id", "")).strip():
            problems.append(f"ledger.jsonl:{lineno} apply 事件缺非空 `version_id`（27 号批 V-4）")
        if rec.get("decision") == "ruling" and not str(rec.get("ruling", "")).strip():
            problems.append(f"ledger.jsonl:{lineno} ruling 事件缺非空 `ruling`（裁定编号，如 Q27；28 号 §2.2）")
        entries.append(rec)
    return entries, problems


def _latest_decision(entries: list[dict], candidate_id: str) -> dict | None:
    """该候选**最新的裁决**（approve/reject/supersede）。`apply` 等事件不参与——
    apply 之后 status 才变 applied，若把事件当裁决，I22 会误判（27 号批 V-4）。"""
    mine = [e for e in entries
            if e.get("id") == candidate_id and e.get("decision") in VALID_DECISIONS]
    if not mine:
        return None
    mine.sort(key=lambda e: str(e.get("at", "")))
    return mine[-1]


def _age_days(created_at: str) -> float | None:
    try:
        dt = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0


def _display(path: Path) -> str:
    """仓库内显示相对路径；演练用的临时目录显示绝对路径。"""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def collect() -> dict:
    ledger, problems = _load_ledger()
    candidates: list[dict] = []

    if not PENDING_DIR.is_dir():
        return {"pending": [], "counts": {}, "problems": problems + [f"待审区不存在：{PENDING_DIR}"]}

    for child in sorted(PENDING_DIR.iterdir()):
        if not child.is_dir() or child.name.startswith("_"):
            continue
        cid = child.name
        cpath = child / "candidate.json"
        if not cpath.exists():
            problems.append(f"{cid}/ 缺 candidate.json")
            continue
        try:
            cand = json.loads(cpath.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            problems.append(f"{cid}/candidate.json JSON 解析失败：{exc}")
            continue

        for field in REQUIRED_CANDIDATE_FIELDS:
            if field not in cand:
                problems.append(f"{cid}/candidate.json 缺字段 `{field}`（28 号 §2.1）")
        if cand.get("id") != cid:
            problems.append(f"{cid}/：candidate.json 的 id={cand.get('id')!r} 与目录名不符")

        gates = cand.get("gates") or {}
        gate_state = {}
        for gk in GATE_KEYS:
            g = gates.get(gk) or {}
            gate_state[gk] = bool(g.get("passed"))
        gates_ready = all(gate_state.values())

        # S4 证据门机检（26 号 §2 S4）：证据条目须有可定位引用与合法强度；
        # 且"可复现"才允许自动过门——否则必须有人审记录（LLM 不得充当证据门判定者）
        for i, ev in enumerate(cand.get("evidence") or []):
            ev = ev or {}
            if not str(ev.get("ref", "")).strip():
                problems.append(f"{cid}/evidence[{i}]：缺可定位的 ref（26 号 S4：每条证据须可复核）")
            if ev.get("strength") not in VALID_STRENGTH:
                problems.append(
                    f"{cid}/evidence[{i}]：strength={ev.get('strength')!r} 非法"
                    f"（应为 {sorted(VALID_STRENGTH)}，见 24 号 D1）")
        ev_gate = gates.get("evidence") or {}
        if ev_gate.get("passed") and not str(ev_gate.get("detail", "")).strip():
            problems.append(f"{cid}/gates.evidence：passed=true 但 detail 为空——证据门的判定依据必须写明")

        # removals（移动/删除的旧位置，2026-10-11 起）：结构提前报警——apply 会逐项严格校验，
        # 此处只避免"构造完才发现 apply 必拒"
        removals = cand.get("removals") or []
        for i, rm in enumerate(removals):
            rm = rm or {}
            rel = str(rm.get("path", "")).strip()
            if not rel:
                problems.append(f"{cid}/removals[{i}]：缺 `path`")
                continue
            if not rel.startswith(ALLOWED_PREFIXES):
                problems.append(f"{cid}/removals[{i}]：`{rel}` 越界（不在白名单 {ALLOWED_PREFIXES}）")
            if not str(rm.get("sha256", "")).strip():
                problems.append(f"{cid}/removals[{i}]：`{rel}` 缺 `sha256`（apply 会拒绝无校验删除）")

        latest = _latest_decision(ledger, cid)
        status = str(cand.get("status", ""))
        awaiting_apply = False
        if latest:
            expect = {"approve": "applied", "reject": "rejected", "supersede": "superseded"}[latest["decision"]]
            if status == "pending" and latest["decision"] == "approve":
                # 合法中间态：已批准、等待 pending_apply 落盘（apply 后 status → applied）
                awaiting_apply = True
            elif status != expect:
                problems.append(
                    f"{cid}/：status={status!r} 与账本最新 decision={latest['decision']!r}"
                    f"（应为 {expect!r}）——不一致（I22）"
                )
        elif status in {"applied", "rejected", "superseded"}:
            problems.append(f"{cid}/：status={status!r} 但账本无对应记录（I21）")

        age = _age_days(cand.get("created_at", ""))
        if age is not None and age < 0:
            problems.append(f"{cid}/：created_at={cand.get('created_at')!r} 在未来（年龄 {age:.1f} 天）"
                            "——时间戳错误，须修正")
            age = None
        candidates.append({
            "id": cid,
            "status": status,
            "version": str(cand.get("applied_version", "")),   # 27 号批 V-4：候选 → 版本
            "version_changed": bool(cand.get("version_changed", True)),
            "awaiting_apply": awaiting_apply,
            "hypothesis": str(cand.get("hypothesis", ""))[:80],
            "landing": cand.get("landing", ""),
            "dimension": cand.get("target_dimension", ""),
            "changes_n": len(cand.get("changes") or []),
            "removals_n": len(cand.get("removals") or []),
            "gates": gate_state,
            "gates_ready": gates_ready,
            "age_days": round(age, 1) if age is not None else None,
            "stale": (age is not None and age > STALE_DAYS and status == "pending"),
            "path": _display(child),
        })

    pending = [c for c in candidates if c["status"] == "pending"]
    pending.sort(key=lambda c: (-(c["age_days"] or 0), c["id"]))
    counts = {}
    for c in candidates:
        key = c["status"] or "<无状态>"
        if c.get("awaiting_apply"):
            key = "已批准待落盘"
        counts[key] = counts.get(key, 0) + 1

    # 留档检查（I24）：账本里已裁的候选目录必须仍在
    on_disk = {c["id"] for c in candidates}
    for e in ledger:
        if e.get("decision") in {"reject", "supersede"} and e.get("id") not in on_disk:
            problems.append(f"{e.get('id')}：账本已裁定 {e.get('decision')}，但候选目录不存在（I24 留档不可删）")

    # 同文件冲突检查（28 号待补项）：**payload 是整文件副本**——两个 pending 候选改同一文件时，
    # 先落的会被后落的整段覆盖（真正发生过的场景：C-20261011-01 与 C-20261011-03 都改
    # process_topology.bkn）。此处只**报**，不阻断：人工/产出方的处置是并合或重生 payload。
    # 2026-10-11 起把 `removals`（移动/删除的旧位置）一并计入"触及面"——删除同样会撞车。
    pending_ids = [c["id"] for c in candidates if c["status"] == "pending"]
    files_of: dict = {}
    for cid in pending_ids:
        payload = PENDING_DIR / cid / "payload"
        touched: set = set()
        if payload.is_dir():
            touched = {
                str(p.relative_to(payload)) for p in payload.rglob("*")
                if p.is_file() and PRE_APPLY not in p.parts and "__pycache__" not in p.parts
            }
        try:
            cj = json.loads((PENDING_DIR / cid / "candidate.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cj = {}
        touched |= {str((rm or {}).get("path", "")).strip() for rm in (cj.get("removals") or [])}
        touched.discard("")
        if not touched:
            continue
        files_of[cid] = touched
    for i, a in enumerate(sorted(files_of)):
        for b in sorted(files_of):
            if a >= b:
                continue
            both = sorted(files_of[a] & files_of[b])
            if both:
                problems.append(f"{a} 与 {b} 的 payload/removals 触及同一批文件（整文件副本会互相覆盖）："
                                f"{', '.join(both)}——处置：并合为一条，或先落一条后重生另一条的 payload")
    for i, a in enumerate(sorted(files_of)):
        for b in sorted(files_of):
            if a >= b:
                continue
            both = sorted(files_of[a] & files_of[b])
            if both:
                problems.append(f"{a} 与 {b} 的 payload 改同一批文件（整文件副本会互相覆盖）："
                                f"{', '.join(both)}——处置：并合为一条，或先落一条后重生另一条的 payload")

    return {"pending": pending, "candidates": candidates, "counts": counts,
            "problems": problems, "ledger_entries": len(ledger), "stale_days": STALE_DAYS}


def render(data: dict) -> None:
    print(f"待审区：{_display(PENDING_DIR)}｜账本 {data['ledger_entries']} 条记录")
    counts = data.get("counts") or {}
    if counts:
        print("状态分布：" + "，".join(f"{k}={v}" for k, v in sorted(counts.items())))
    applied = [c for c in data.get("candidates") or [] if c.get("version")]
    if applied:
        def _vf(c: dict) -> str:
            # 版本未变（无 .bkn 变更的候选）要标出来：否则会被读成"本候选属于该版本的内容"
            return f"{c['id']}→{c['version']}" + ("" if c.get("version_changed", True) else "（未变）")

        print("已生效版本：" + "，".join(_vf(c) for c in sorted(applied, key=lambda c: c["id"])))
    pending = data.get("pending") or []
    if not pending:
        print("\n✅ 无待审候选项")
    else:
        print(f"\n待审 {len(pending)} 项（按挂置天数降序；> {data['stale_days']} 天标红且不自动过期）：")
        for c in pending:
            mark = "🔴" if c["stale"] else "  "
            gate = "门禁齐备" if c["gates_ready"] else "门禁未齐备(" + ",".join(
                k for k, v in c["gates"].items() if not v) + ")"
            age = f"{c['age_days']}天" if c["age_days"] is not None else "年龄未知"
            stage = "**已批准，待 pending_apply 落盘**" if c.get("awaiting_apply") else "待审批"
            rm_note = f"（含 {c['removals_n']} 删）" if c.get("removals_n") else ""
            print(f"{mark} [{c['id']}] {age}｜{c['dimension']}/{c['landing']}｜{gate}｜{stage}｜改动 {c['changes_n']} 处{rm_note}")
            print(f"     假设：{c['hypothesis']}")
    problems = data.get("problems") or []
    if problems:
        print(f"\n⚠ 结构性问题 {len(problems)} 条：")
        for p in problems:
            print(f"  - {p}")
    else:
        print("\n✅ 账本与目录结构校验通过")


def main(argv=None) -> int:
    global PENDING_DIR
    ap = argparse.ArgumentParser(description="待审区清单与账本校验（28 号批 R-1）")
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    ap.add_argument("--strict", action="store_true", help="有结构性问题时以非零退出码结束")
    ap.add_argument("--pending-dir", default=None,
                    help="覆盖待审区目录（演练/自测用；默认 doc/optimize/pending）")
    ns = ap.parse_args(argv)
    if ns.pending_dir:
        PENDING_DIR = Path(ns.pending_dir).expanduser().resolve()

    data = collect()
    if ns.json:
        print(json.dumps(data, ensure_ascii=False, indent=1))
    else:
        render(data)
    return 1 if (data["problems"] and ns.strict) else 0


if __name__ == "__main__":
    raise SystemExit(main())
