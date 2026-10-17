"""scan_gaps.py 的回归测试（就地首轮 S1-P2，2026-10-12）。

缺陷：无未解决缺口时**早退不重写报告** → `plugin/gaps_report.md` 与源数据矛盾
（实测：源数据 4/4 resolved，报告仍写「未解决 4」；报告是缺口分诊与第三期信号②的输入）。
修复口径：**任何情况下都重写**——「当前没有缺口」本身是要落盘的结论。
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCAN = ROOT / "plugin" / "scripts" / "scan_gaps.py"


def _entry(code: str, resolved: bool, ts: int) -> str:
    return json.dumps({"tool": "diagnose_error", "params": {"error_code": code},
                       "confidence": "partial", "gaps": ["缺少关键字段: retrieval_guide"],
                       "timestamp": ts, "resolved": resolved}, ensure_ascii=False)


class TestScanGaps(unittest.TestCase):

    def _run(self, log: Path, out: Path):
        return subprocess.run([sys.executable, str(SCAN), "--log", str(log), "--output", str(out)],
                              capture_output=True, text=True, cwd=str(ROOT), timeout=120)

    def test_zero_unresolved_rewrites_report(self):
        """全 resolved → 报告必须被重写为「未解决 0 条」（不得留下陈旧内容）。"""
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "gap_log_2026-10-12.jsonl"
            out = Path(tmp) / "report.md"
            log.write_text(_entry("-8888", True, 1) + "\n" + _entry("-7777", True, 2) + "\n",
                           encoding="utf-8")
            out.write_text("陈旧内容（未解决 4 条）\n", encoding="utf-8")
            r = self._run(log, out)
            self.assertEqual(r.returncode, 0, r.stderr[-500:])
            text = out.read_text(encoding="utf-8")
            self.assertIn("未解决 0 条", text)
            self.assertIn("共 0 条缺失", text)
            self.assertNotIn("陈旧内容", text)

    def test_unresolved_rows_are_listed(self):
        """有未解决缺口 → 报告含该条并计数正确。"""
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "gap_log_2026-10-12.jsonl"
            out = Path(tmp) / "report.md"
            log.write_text(_entry("-9999", False, 1) + "\n" + _entry("-8888", True, 2) + "\n",
                           encoding="utf-8")
            r = self._run(log, out)
            self.assertEqual(r.returncode, 0, r.stderr[-500:])
            text = out.read_text(encoding="utf-8")
            self.assertIn("未解决 1 条", text)
            self.assertIn("-9999", text)


# ── 归并去噪（44 号 §3.4-5，批 4）──────────────────────────────────────
# 缺陷（44 号 §3.4）：`get_prerequisites` 的固定提示语占 gap_log 的 98.7%（5258/5331），
# 报表没有信息量。修复口径：`_norm_gap` 归并去噪 + 「缺口簇 / 新形态」两段（**只增段**）。
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from plugin.scripts.scan_gaps import _norm_gap  # noqa: E402


def _gap(tool: str, gap: str, ts: int) -> str:
    """一条未解决缺口记录（行首必须是 `{"tool": `——带空格，来源过滤判据）。"""
    return json.dumps({"tool": tool, "params": {}, "confidence": "partial", "gaps": [gap],
                       "timestamp": ts, "user_supplied": None, "resolved": False},
                      ensure_ascii=False)


def _scan(log: Path, out: Path):
    return subprocess.run([sys.executable, str(SCAN), "--log", str(log), "--output", str(out)],
                          capture_output=True, text=True, cwd=str(ROOT), timeout=120)


class TestNormGap(unittest.TestCase):
    """`_norm_gap`：数字 / 引号值 / 空白三类归一 + 幂等 + 截断（44 号 §3.4-5）。"""

    def test_number_becomes_placeholder(self):
        self.assertEqual(_norm_gap("返回内容过短(48字符 < 50), 可能不充分"),
                         "返回内容过短(<N>字符 < <N>), 可能不充分")

    def test_percent_and_threshold_dropped(self):
        self.assertEqual(_norm_gap("覆盖率 98.7% 低于阈值 99%"), "覆盖率 <N> 低于阈值 <N>")

    def test_single_quoted_value_becomes_placeholder(self):
        self.assertEqual(_norm_gap("动作 'failover_to_standby' 未登记"), "动作 <VAL> 未登记")

    def test_double_quoted_value_becomes_placeholder(self):
        self.assertEqual(_norm_gap('状态 "STOPPED" 无对应约束'), "状态 <VAL> 无对应约束")

    def test_whitespace_collapsed_and_trimmed(self):
        self.assertEqual(_norm_gap("  缺少关键字段:\n\t retrieval_guide  "),
                         "缺少关键字段: retrieval_guide")

    def test_truncated_to_120(self):
        self.assertEqual(len(_norm_gap("缺" * 300)), 120)

    def test_idempotent(self):
        for raw in ("返回内容过短(48字符 < 50), 可能不充分",
                    "动作 'failover_to_standby' 未登记",
                    "  空白\n折叠\t的文案  ",
                    "BKN 仅提供基础骨架，建议查 Qdrant 补充详细参数/案例/版本信息"):
            once = _norm_gap(raw)
            self.assertEqual(_norm_gap(once), once, f"不幂等: {once!r}")


class TestGapClusters(unittest.TestCase):
    """归并去噪：3 条同骨架 + 1 条异构 → 簇数 2、最大簇计数 3（44 号 §3.4-5）。"""

    def test_three_same_skeleton_merge_into_one_cluster(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "gap_log_2026-10-12.jsonl"
            out = Path(tmp) / "report.md"
            log.write_text("\n".join([
                _gap("resolve_relation", "返回内容过短(48字符 < 50), 可能不充分", 1791791710),
                _gap("resolve_relation", "返回内容过短(47字符 < 50), 可能不充分", 1791791730),
                _gap("resolve_relation", "返回内容过短(40字符 < 50), 可能不充分", 1791794938),
                _gap("check_action_risk", "缺少关键字段: action", 1791810692),
            ]) + "\n", encoding="utf-8")
            r = _scan(log, out)
            self.assertEqual(r.returncode, 0, r.stderr[-500:])
            text = out.read_text(encoding="utf-8")
            # 总 4 条 → 簇数 2、最大簇计数 3（占比 3/4 = 75.0%）
            self.assertIn("总缺口数 4 · 簇数 2 · 最大簇占比 75.0%", text)
            self.assertIn("| 1 | 3 | `resolve_relation` | 返回内容过短(<N>字符 < <N>), 可能不充分 |", text)
            self.assertIn("| 2 | 1 | `check_action_risk` | 缺少关键字段: action |", text)


class TestHelpIsReadOnly(unittest.TestCase):
    """`--help` 只打印用法：不读日志、不写任何文件（既有纪律，批 4 保持）。"""

    def test_help_changes_no_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            log = work / "gap_log_2026-10-12.jsonl"
            log.write_text(_gap("resolve_relation", "返回内容过短(48字符 < 50), 可能不充分",
                                1791791710) + "\n", encoding="utf-8")
            before = sorted(str(p.relative_to(work)) for p in work.rglob("*"))
            r = subprocess.run([sys.executable, str(SCAN), "--help",
                                "--log", str(log), "--output", str(work / "report.md")],
                               capture_output=True, text=True, cwd=str(work), timeout=120)
            after = sorted(str(p.relative_to(work)) for p in work.rglob("*"))
            self.assertEqual(r.returncode, 0, r.stderr[-500:])
            self.assertIn("usage", r.stdout)
            self.assertEqual(before, after, "`--help` 改动了输出目录")
            self.assertFalse((work / "report.md").exists(), "`--help` 写了报告文件")
            # 未进入读日志/生成报告的主流程（否则会打印下列之一）
            self.assertNotIn("报告已生成", r.stdout)
            self.assertNotIn("gap_log 数据文件不存在", r.stdout)


if __name__ == "__main__":
    unittest.main()
