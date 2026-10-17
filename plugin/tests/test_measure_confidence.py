"""门禁工具 measure_confidence 的 compare/summarize 语义测试（22 号批 4-3）。

钉住三件事：
① 稳定用例 out_chars 下降 >10% → 判劣化（既有回归能力未放松）；
② **语料驱动用例**（`corpus_sensitive`，输出随 Qdrant 语料增长）大幅变化 → 不判劣化、只列数字；
③ 用例集与基线不一致 → 告警（对比有效性受损）。

（import 副作用：measure_confidence 模块体会设 LOG_DIR 为临时目录——按下面方式还原。）
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCRIPTS = ROOT / "plugin" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

_prev_log_dir = os.environ.get("LOG_DIR")
import measure_confidence as mc  # noqa: E402
if _prev_log_dir is not None:  # 还原模块导入副作用，避免污染同会话其它测试
    os.environ["LOG_DIR"] = _prev_log_dir


def _rec(cid, tool="get_prerequisites", out=100, conf="full", cs=False):
    r = {"case_id": cid, "tool": tool, "out_chars": out, "confidence": conf, "gaps": []}
    if cs:
        r["corpus_sensitive"] = True
    return r


def _payload(records, label="x"):
    return {
        "schema": 1, "label": label, "cases": len(records),
        "env": {"qdrant_reachable": True},
        "summary": mc.summarize(records),
        "records": records,
    }


class TestMeasureConfidenceCompare(unittest.TestCase):

    def test_stable_case_drop_is_regression(self):
        """稳定用例 out_chars 下降 >10% → 判劣化（回归能力未放松）。"""
        base = _payload([_rec("get_prerequisites|{\"operation\": \"start_rule\"}", out=1000)])
        cur = _payload([_rec("get_prerequisites|{\"operation\": \"start_rule\"}", out=700)])
        regression, notes = mc.compare(base, cur)
        self.assertTrue(regression, notes)
        self.assertTrue(any("✗ 劣化" in n for n in notes), notes)

    def test_corpus_sensitive_change_is_not_regression(self):
        """语料驱动用例大幅下降 → 不判劣化，但数字仍列出（22 号批 4-3）。"""
        base = _payload([_rec("diagnose_db_link|{\"symptom\": \"x\"}", tool="diagnose_db_link",
                              out=20000, cs=True)])
        cur = _payload([_rec("diagnose_db_link|{\"symptom\": \"x\"}", tool="diagnose_db_link",
                             out=2000, cs=True)])
        regression, notes = mc.compare(base, cur)
        self.assertFalse(regression, notes)
        joined = "\n".join(notes)
        self.assertIn("语料驱动用例 1 例", joined)
        self.assertIn("不判劣化", joined)

    def test_case_set_mismatch_warns(self):
        """用例集不一致（基线独有/本次独有）→ 告警。"""
        base = _payload([_rec("a|{}"), _rec("b|{}")])
        cur = _payload([_rec("a|{}"), _rec("c|{}")])
        regression, notes = mc.compare(base, cur)
        self.assertFalse(regression, notes)
        self.assertTrue(any("用例集与基线不一致" in n for n in notes), notes)

    def test_summarize_excludes_corpus_from_main_metrics(self):
        """主口径不含语料驱动用例；语料块单列。"""
        records = [
            _rec("a|{}", out=100), _rec("b|{}", out=200),
            _rec("db|{}", tool="diagnose_db_link", out=90000, cs=True),
        ]
        s = mc.summarize(records)
        self.assertEqual(s["total"], 2)
        self.assertEqual(s["out_chars"]["max"], 200)      # 语料值 90000 未进主聚合
        self.assertEqual(s["corpus_sensitive"]["n"], 1)
        self.assertEqual(s["corpus_sensitive"]["out_chars"]["max"], 90000)

    def test_flat_payloads_report_compared_count(self):
        """全持平 → 报「N 例（非语料驱动）全部持平」（计数动态，不写死 40）。"""
        base = _payload([_rec("a|{}"), _rec("db|{}", tool="diagnose_db_link", cs=True)])
        cur = _payload([_rec("a|{}"), _rec("db|{}", tool="diagnose_db_link", cs=True)])
        regression, notes = mc.compare(base, cur)
        self.assertFalse(regression, notes)
        self.assertTrue(any("1 例（非语料驱动）全部持平" in n for n in notes), notes)


if __name__ == "__main__":
    unittest.main()
