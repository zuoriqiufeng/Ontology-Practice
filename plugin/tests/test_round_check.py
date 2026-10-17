"""round_check.py 的测试（26 号 I10/I11/I12；Q17 载体）。

正例＝最小完整轮次记录；反例覆盖：缺段 / 证据为空 / 证据不可定位 / S2 必答为空 /
账本 apply 无轮次记录（含显式豁免路径）。
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import round_check as rc  # noqa: E402

GOOD = """# 归因表

## S1 · 问题图（现象 → 证据）

| # | 现象 | 证据（可复核引用） | 影响面 | 初判落点 | 不确定度 |
|---|------|-------------------|--------|----------|----------|
| P1 | 现象 A | `plugin/tools.py:108` 处的豁免注释 | 3 Tool | Tool 契约 | 低 |

## S2 · 归因表（证据 → 落点）

| 项 | 填写 |
|----|------|
| **选中的问题** | P1 |
| **三层问句（必答）** | 工具弱 |
| **落点**（五类之一） | **Tool 契约** |
| **当前限制是什么** | 无埋点 |
| **为什么导致观察到的现象** | 观测空白 |
| **什么证据能证伪它** | 若日志里已有该事件则不成立 |

## S3 · 候选补丁

见同目录 `candidate.json` 与 `payload/`。

## S4 · 三重门禁

① 结构 lint 0 error；② 回归 pytest 全绿；③ 证据＝可复现档（测试）。

## S5 · 发布与记录

人工审批 → 落盘 applied；台账一行。
"""


def _mk(cand_dir: Path, attr: str = GOOD, cand: dict | None = None):
    cand_dir.mkdir(parents=True, exist_ok=True)
    (cand_dir / "attribution.md").write_text(attr, encoding="utf-8")
    (cand_dir / "candidate.json").write_text(
        json.dumps(cand if cand is not None else
                   {"id": cand_dir.name, "gates": {"evidence": {"passed": True, "detail": "测试"}}},
                   ensure_ascii=False), encoding="utf-8")


class TestRoundCheck(unittest.TestCase):

    def test_good_round_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "C-20261012-90"
            _mk(d)
            self.assertEqual(rc.check_round(d / "attribution.md", d), [])

    def test_missing_section_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "C-20261012-90"
            _mk(d, GOOD.replace("## S5", "## S6"))
            problems = rc.check_round(d / "attribution.md", d)
            self.assertTrue(any("缺 S5" in p for p in problems), problems)

    def test_empty_evidence_cell_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "C-20261012-90"
            _mk(d, GOOD.replace("| `plugin/tools.py:108` 处的豁免注释 |", "| |"))
            problems = rc.check_round(d / "attribution.md", d)
            self.assertTrue(any("证据为空" in p for p in problems), problems)

    def test_unlocatable_evidence_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "C-20261012-90"
            _mk(d, GOOD.replace("| `plugin/tools.py:108` 处的豁免注释 |", "| 感觉不太好 |"))
            problems = rc.check_round(d / "attribution.md", d)
            self.assertTrue(any("不可定位" in p for p in problems), problems)

    def test_empty_s2_answer_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "C-20261012-90"
            _mk(d, GOOD.replace("| **什么证据能证伪它** | 若日志里已有该事件则不成立 |",
                                "| **什么证据能证伪它** | |"))
            problems = rc.check_round(d / "attribution.md", d)
            self.assertTrue(any("证伪" in p for p in problems), problems)

    def test_apply_without_round_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            pending = Path(tmp)
            d = pending / "C-20261012-90"
            _mk(d)
            (pending / "ledger.jsonl").write_text(
                json.dumps({"id": "C-20261012-90", "at": "20261012T010000Z", "decision": "apply"}) + "\n"
                + json.dumps({"id": "C-20261012-91", "at": "20261012T020000Z", "decision": "apply"}) + "\n",
                encoding="utf-8")
            self.assertEqual(rc.main(["--pending-dir", str(pending)]), 1)

    def test_apply_covered_by_round_mention_passes(self):
        """Q17：一轮可含多候选——被轮次档点名（S3 表）的后继候选不再单独要 attribution.md。"""
        with tempfile.TemporaryDirectory() as tmp:
            pending = Path(tmp)
            _mk(pending / "C-20261012-90",
                GOOD.replace("见同目录 `candidate.json` 与 `payload/`。",
                             "本轮两个候选：C-20261012-90（同目录 `candidate.json`）与 C-20261012-91"
                             "（见 `../C-20261012-91/candidate.json`）。"))
            # C-20261012-91 无 attribution.md，但在 C-90 的轮次档里被点名
            (pending / "C-20261012-91").mkdir()
            (pending / "C-20261012-91" / "candidate.json").write_text(
                json.dumps({"id": "C-20261012-91", "gates": {"evidence": {"passed": True, "detail": "x"}}}),
                encoding="utf-8")
            (pending / "ledger.jsonl").write_text(
                json.dumps({"id": "C-20261012-91", "at": "20261012T020000Z", "decision": "apply"}) + "\n",
                encoding="utf-8")
            self.assertEqual(rc.main(["--pending-dir", str(pending)]), 0)

    def test_grandfathered_apply_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            pending = Path(tmp)
            _mk(pending / "C-20261012-90")
            gid = next(iter(rc.GRANDFATHERED_APPLIES))
            (pending / "ledger.jsonl").write_text(
                json.dumps({"id": gid, "at": "20261012T010000Z", "decision": "apply"}) + "\n",
                encoding="utf-8")
            self.assertEqual(rc.main(["--pending-dir", str(pending)]), 0)


if __name__ == "__main__":
    unittest.main()
