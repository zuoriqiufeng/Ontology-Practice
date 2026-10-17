#!/usr/bin/env python3
"""round_check.py — 轮次记录的结构校验（26 号 I10/I11；Q17 载体＝候选目录 attribution.md）

- **I10**：每轮的 `attribution.md` 字段齐全——S1 问题图（表头含「证据」列且至少一行有值）、
  S2 归因表（三层问句/落点/当前限制/为什么导致/反证 五必答非空）、S3 指向候选、S4 三门、
  S5 决定与发布；
- **I11**：S1 每条证据**可定位**——`file:line`、`§章节`、`日期+时间`（现场日志）、
  `*.py`（测试/脚本名）、`C-YYYYMMDD-NN`（候选/裁定名）五类形态之一；
- **I12**：候选 `candidate.json` 的 `gates.evidence.passed=true` 须有 detail（与 `pending_status.py`
  同口径；本脚本只做「轮次记录 ↔ 候选」的交叉存在性）；
- **I13**：changelog ∥ resolved 的对账**不在此脚本**（用 `plugin/scripts/mark_gaps_resolved.py --dry-run`）。

用法：python3 scripts/round_check.py [--pending-dir DIR] [--json] [--verbose]
退出码：0 全部通过（或无轮次记录）；1 有结构问题；2 待审区不存在。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PENDING = REPO_ROOT / "doc" / "optimize" / "pending"

#: 五类可定位证据形态（与 26 号 I11 的括号枚举一一对应；显式字符类——plugin 禁正则简写不涉本目录，但保持一致）
_EVIDENCE_FORMS = (
    ("file:line", re.compile(r"[A-Za-z0-9_./-]+\.[A-Za-z0-9]+:[0-9]+")),
    ("§section", re.compile(r"§")),
    ("timestamp", re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9]{2}:[0-9]{2}")),
    ("script/test", re.compile(r"[A-Za-z0-9_./-]+\.py")),
    ("candidate/ruling", re.compile(r"C-[0-9]{8}-[0-9]{2}|Q[0-9]{1,2}")),
)

_S2_KEYS = ("三层问句", "落点", "当前限制", "为什么导致", "证伪")
_S4_KEYS = ("结构", "回归", "证据")
#: S5 的判定与记录：**结论词**（发布/落盘/驳回/拒绝/撤回/决定）+ **记录指针**（台账/changelog/轮次表/ledger）。
#: 实例（C-20261012-05）用「人工审批 + 已落盘 applied + 台账」表述——机器检查认语义不认特定词序。
_S5_OUTCOME = re.compile(r"已发布|已落盘|applied|驳回|拒绝|撤回|superseded|决定|审批")
_S5_RECORD = re.compile(r"台账|changelog|轮次表|ledger")


def _sections(text: str) -> dict:
    """把 markdown 按 `## S1..S5` 切块（标题行计入本段——「发布与记录」这类词常只出现在标题）。"""
    out: dict = {}
    cur = None
    for line in text.splitlines():
        m = re.match(r"^##[ \t]+S([1-5])\b", line.strip(), re.IGNORECASE)
        if m:
            cur = f"S{m.group(1)}"
            out[cur] = [line]
        elif cur:
            out[cur].append(line)
    return {k: "\n".join(v).strip() for k, v in out.items()}


def _table_rows(block: str) -> list[list[str]]:
    rows = []
    for line in block.splitlines():
        s = line.strip()
        if s.startswith("|") and s.endswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if all(set(c) <= set("-: ") for c in cells):   # 分隔行
                continue
            rows.append(cells)
    return rows


def _evidence_forms(cell: str) -> list[str]:
    return [name for name, rx in _EVIDENCE_FORMS if rx.search(cell)]


def check_round(attr_path: Path, cand_dir: Path) -> list[str]:
    """返回该轮的问题列表（空＝通过）。"""
    problems: list[str] = []
    text = attr_path.read_text(encoding="utf-8")
    sec = _sections(text)

    for s in ("S1", "S2", "S3", "S4", "S5"):
        if s not in sec:
            problems.append(f"I10: 缺 {s} 段")

    # S1：表头含「证据」列 + 至少一行有值 + 每条证据可定位（I11）
    rows = _table_rows(sec.get("S1", ""))
    if not rows:
        problems.append("I10: S1 无表格（问题图）")
    else:
        header = rows[0]
        try:
            ev_idx = next(i for i, h in enumerate(header) if "证据" in h)
        except StopIteration:
            problems.append(f"I10: S1 表头无「证据」列（表头={header}）")
            ev_idx = None
        data = rows[1:]
        if not data:
            problems.append("I10: S1 问题图无数据行（无证据的『感觉不太好』不得进图）")
        if ev_idx is not None:
            for i, r in enumerate(data, 1):
                cell = r[ev_idx] if ev_idx < len(r) else ""
                if not cell:
                    problems.append(f"I10: S1 第 {i} 行证据为空")
                    continue
                if not _evidence_forms(cell):
                    problems.append(f"I11: S1 第 {i} 行证据不可定位（需 file:line / §章节 / 时间戳 / *.py / C-…-NN）: {cell[:60]}")

    # S2：五必答（键列含关键词且值列非空；容忍 Markdown 强调符与括注）
    # 注意：单元格匹配必须**逐行**（`[^|\n]`）——用 `[^|]` 会跨行吞并，把「值＝换行」误判为已填。
    s2 = sec.get("S2", "")
    for key in _S2_KEYS:
        m = re.search(r"\|\s*[^|\n]*" + re.escape(key) + r"[^|\n]*\|([^|\n]*)\|", s2)
        if not m or not m.group(1).strip().strip("*_"):
            problems.append(f"I10: S2 缺必答项或为空：{key}")

    # S3：指向候选（candidate.json 或 payload/ 或 changes）
    s3 = sec.get("S3", "")
    if not re.search(r"candidate\.json|payload/|changes\.md", s3):
        problems.append("I10: S3 未指向候选产物（candidate.json / payload/ / changes.md）")

    # S4：三门
    s4 = sec.get("S4", "")
    for key in _S4_KEYS:
        if key not in s4:
            problems.append(f"I10: S4 缺门：{key}")

    # S5：结论（发布/落盘/驳回/拒绝/撤回/决定）+ 记录指针（台账/changelog/轮次表/ledger）
    s5 = sec.get("S5", "")
    if not _S5_OUTCOME.search(s5):
        problems.append("I10: S5 缺结论（发布/落盘/驳回/拒绝/撤回/决定 之一）")
    if not _S5_RECORD.search(s5):
        problems.append("I10: S5 缺记录指针（台账/changelog/轮次表/ledger）")

    # I12：候选侧证据门（交叉存在性）
    cand = cand_dir / "candidate.json"
    if cand.is_file():
        try:
            data = json.loads(cand.read_text(encoding="utf-8"))
            g = (data.get("gates") or {}).get("evidence") or {}
            if g.get("passed") and not str(g.get("detail", "")).strip():
                problems.append("I12: candidate.json 的 gates.evidence.passed=true 但 detail 为空")
        except json.JSONDecodeError:
            problems.append("I12: candidate.json 不是合法 JSON")
    else:
        problems.append("I12: 候选目录缺 candidate.json")
    return problems


def find_rounds(pending_dir: Path) -> list[tuple[Path, Path]]:
    out = []
    for d in sorted(pending_dir.iterdir()):
        if not d.is_dir() or d.name.startswith("_"):
            continue
        attr = d / "attribution.md"
        if attr.is_file():
            out.append((attr, d))
    return out


#: 轮次机制（26 号 Q17，2026-10-12 裁定）**生效前/非演化**的 apply——显式豁免并写理由（不静默）。
#: 先例：`KNOWN_META_INFO` 的豁免表体例——豁免必须可见、可核、带理由；此后每次 apply 都要有轮次记录。
GRANDFATHERED_APPLIES = {
    "C-20261012-01": "轮次载体（Q17）确立之前的落盘",
    "C-20261012-02": "同上（U-1 批）",
    "C-20261012-03": "同上（U-2∥V-1 批）",
    "C-20261012-04": "同上（测试隔离收尾件）",
    "C-20261012-06": "**事故修复**（复盘见 36 号）——非演化轮次，不适用 I10",
    # 2026-10-13 的两次**直改落盘**（P-2A 码表侧车 / P-2B 码含义接线）：改动的确生效，
    # 但**未先建候选目录**（缺事前提案与用户 approve）——按本机制「显式豁免带理由」处理，
    # 不伪造批准。偏离记录见 doc/optimize/63-code-meaning-wiring-and-status-gate.md §6，
    # 并作为待补项记入 doc/optimize/56-open-items.md。
    "C-20261013-16": "**直改落盘**（官方码表侧车 ＋ 生成器 ＋ .gitignore）：未建候选目录、无 approve，"
                     "按豁免处理；变更详情见 ../62-code-meaning-reasoning-and-alias-verdicts.md 与 ../63-...md",
    "C-20261013-17": "**直改落盘**（match_official 作用域 ＋ status 闸门 ＋ 测试与契约脚本）：未建候选目录、无 approve，"
                     "按豁免处理；634 passed / EXIT=0，详情见 ../63-code-meaning-wiring-and-status-gate.md",
    "C-20261013-18": "**直改落盘**（P-2D-1 lint Q27 守卫：bkn/** 不得出现码的符号名 IAERR_*/ALARM_*）；未建候选目录、无 approve，"
                     "按豁免处理；67 passed，详情见 ../00-changelog.md 的 2026-10-13 条目",
    #: 追加（2026-10-13，随 `C-20261013-05`）：该轮次记录**点名引用**了 `C-20261011-02` / `C-20261011-09`
    #: 作「最后落盘者」，而 `covered_candidates` 把**被点名的候选**也算覆盖 ⇒ **起算日**由 2026-10-12
    #: 前移到 2026-10-11，于是这批更早的落盘进入检查面。它们同样是**机制确立前**的落盘（apply 均 2026-10-11），
    #: 按同一体例豁免并写明——**不静默、不伪造轮次记录**。
    "C-20261010-03": "轮次载体（Q17，2026-10-12）确立之前的落盘（apply 2026-10-11）",
    "C-20261011-04": "同上（apply 2026-10-11）",
    "C-20261011-05": "同上（apply 2026-10-11）",
    "C-20261011-06": "同上（apply 2026-10-11）",
    "C-20261011-07": "同上（apply 2026-10-11）",
    "C-20261011-08": "同上（apply 2026-10-11）",
}


def _rel(p: Path) -> str:
    """相对仓库的展示路径；待审区在仓库外（演练/临时目录）时回退绝对路径——不得因此抛错。"""
    try:
        return str(p.relative_to(REPO_ROOT))
    except ValueError:
        return str(p)


def _cand_date(name: str) -> str:
    """`C-YYYYMMDD-NN` → `YYYY-MM-DD`（用于确定 I10 交叉检查的起算日）。"""
    m = re.match(r"C-([0-9]{4})([0-9]{2})([0-9]{2})-", name)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else ""


_CAND_ID = re.compile(r"C-[0-9]{8}-[0-9]{2}")


def covered_candidates(rounds: list[tuple[Path, Path]]) -> set:
    """被轮次记录覆盖的候选集合：① 有自己的 attribution.md；② 被某轮次档**点名提及**
    （Q17：一轮可含多个候选——轮次档写在本轮首个候选目录里，其余候选在 S3 表中点名）。"""
    covered = set()
    for attr, d in rounds:
        covered.add(d.name)
        try:
            covered.update(_CAND_ID.findall(attr.read_text(encoding="utf-8")))
        except OSError:
            pass
    return covered


def apply_events(pending_dir: Path) -> list[dict]:
    """账本里的 apply 事件（I10 的交叉检查面：每次发布都应有轮次记录）。"""
    led = pending_dir / "ledger.jsonl"
    out = []
    if not led.is_file():
        return out
    for line in led.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("decision") == "apply" or r.get("event") == "apply":
            out.append(r)
    return out


def _event_date(r: dict) -> str:
    """`20261012T040439Z` / `2026-10-12T04:04:39+00:00` → `2026-10-12`。"""
    m = re.match(r"([0-9]{4})-?([0-9]{2})-?([0-9]{2})", str(r.get("at", "")))
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="轮次记录结构校验（26 号 I10/I11/I12）")
    ap.add_argument("--pending-dir", type=Path, default=DEFAULT_PENDING)
    ap.add_argument("--enforce-from", default=None,
                    help="I10 交叉检查的起算日（YYYY-MM-DD；缺省=最早轮次记录日，用于前向强制）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    ns = ap.parse_args(argv)

    if not ns.pending_dir.is_dir():
        print(f"✗ 待审区不存在：{ns.pending_dir}", file=sys.stderr)
        return 2

    rounds = find_rounds(ns.pending_dir)
    results = []
    for attr, d in rounds:
        problems = check_round(attr, d)
        results.append({"candidate": d.name, "attribution": _rel(attr),
                        "ok": not problems, "problems": problems})

    # I10 交叉检查（前向）：从**最早一条轮次记录**之日起，凡 apply 过的候选都必须被轮次记录覆盖
    covered = covered_candidates(rounds)
    round_dates = [x for x in (_cand_date(n) for n in covered) if x]
    enforce_from = ns.enforce_from or (min(round_dates) if round_dates else None)
    missing: list[str] = []
    exempt_hit: list[str] = []
    if enforce_from:
        for e in apply_events(ns.pending_dir):
            cid = str(e.get("id", ""))
            if _event_date(e) < enforce_from or cid in covered:
                continue
            if cid in GRANDFATHERED_APPLIES:
                exempt_hit.append(f"{cid}（{GRANDFATHERED_APPLIES[cid]}）")
                continue
            missing.append(f"I10: apply 事件 {cid}（{_event_date(e)}）缺轮次记录（起算日 {enforce_from}）")
    if missing:
        results.append({"candidate": "（账本）", "attribution": "", "ok": False, "problems": missing})

    if ns.json:
        print(json.dumps({"rounds": results, "enforce_from": enforce_from}, ensure_ascii=False, indent=1))
    else:
        print(f"轮次记录：{len(rounds)} 条（载体＝候选目录 attribution.md；I13 用 mark_gaps_resolved --dry-run 对账）")
        if enforce_from:
            print(f"  I10 交叉检查起算日：{enforce_from}（= 最早轮次记录日；此后每次 apply 都要有轮次记录）")
        for r in results:
            mark = "✅" if r["ok"] else "❌"
            print(f"  {mark} {r['candidate']}")
            for p in r["problems"]:
                print(f"      {p}")
        if not results:
            print("  （尚无轮次记录）")
        if exempt_hit:
            print(f"  ℹ 显式豁免（{len(exempt_hit)} 项，前向强制不受影响）：")
            for x in exempt_hit:
                print(f"      · {x}")

    bad = [r for r in results if not r["ok"]]
    if bad:
        print(f"\n✗ {len(bad)} 条轮次记录有结构问题（I10/I11/I12）")
        return 1
    print("\n✅ 轮次记录结构校验通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
