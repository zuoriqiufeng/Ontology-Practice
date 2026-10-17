"""Tests for usage_log (P3-1): write, stats, fault tolerance, gap_log isolation.

2026-09-30 起日志为日期命名（usage_log_YYYY-MM-DD.jsonl），USAGE_LOG/GAP_LOG_PATH 为
**逻辑基名**——测试 patch 基名，实际写入由 rotate_day_file 按日期派生，读取用 glob。
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from plugin import usage_log
from plugin.usage_log import log_usage


def _read_day_lines(tmpdir: Path, prefix: str = "usage_log") -> list[str]:
    """读 tmpdir 下某前缀的全部当日数据文件行（无分片场景，测试数据远小于轮转阈值）。"""
    lines: list[str] = []
    for f in sorted(Path(tmpdir).glob(f"{prefix}_*.jsonl")):
        lines.extend(l for l in f.read_text(encoding="utf-8").splitlines() if l.strip())
    return lines


class TestUsageLog(unittest.TestCase):

    def test_write_and_read_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(usage_log, "USAGE_LOG", Path(tmp) / "usage_log.jsonl"):
                log_usage("search_qdrant", chunk_mode="mini_first", hits=5, mode="single")
                log_usage("design_solution", confidence="partial")
            lines = _read_day_lines(Path(tmp))
            self.assertEqual(len(lines), 2)
            e1 = json.loads(lines[0])
            self.assertEqual(e1["tool"], "search_qdrant")
            self.assertEqual(e1["chunk_mode"], "mini_first")
            self.assertIn("ts", e1)
            e2 = json.loads(lines[1])
            self.assertEqual(e2["confidence"], "partial")

    def test_day_file_name_contains_date(self):
        """43 号轮转改造：文件名必须带日期，一眼可辨是哪天的日志。"""
        import datetime
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(usage_log, "USAGE_LOG", Path(tmp) / "usage_log.jsonl"):
                log_usage("t", a=1)
            expected = f"usage_log_{datetime.date.today().isoformat()}.jsonl"
            self.assertTrue((Path(tmp) / expected).exists(), f"缺少 {expected}")

    def test_write_failure_silent(self):
        """写入失败不影响主流程"""
        with mock.patch.object(usage_log, "USAGE_LOG", Path("/nonexistent-dir-xyz/log.jsonl")):
            log_usage("t", a=1)  # 不应抛异常

    def test_gap_log_untouched(self):
        """usage_log 独立于 gap_log：写 usage 前后 gap 数据文件集合与内容不变"""
        from plugin import supplement
        base = supplement.GAP_LOG_PATH

        def _gap_snapshot() -> dict:
            return {f.name: f.read_text(encoding="utf-8")
                    for f in sorted(base.parent.glob("gap_log*"))}

        before = _gap_snapshot()
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(usage_log, "USAGE_LOG", Path(tmp) / "u.jsonl"):
                log_usage("x", y=2)
        self.assertEqual(_gap_snapshot(), before)


class TestUsageStats(unittest.TestCase):

    def test_stats_aggregation(self):
        from plugin.scripts import usage_stats
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "usage_log.jsonl"
            entries = [
                {"tool": "search_qdrant", "ts": 1, "chunk_mode": "mini_first", "hits": 5},
                {"tool": "search_qdrant", "ts": 2, "chunk_mode": "auto", "hits": 0},
                {"tool": "search_qdrant", "ts": 3, "chunk_mode": "mini_first", "hits": 3},
                {"tool": "design_solution", "ts": 4, "confidence": "full"},
            ]
            target.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
            with mock.patch.object(usage_stats, "USAGE_LOG", target):
                import io
                buf = io.StringIO()
                old = sys.stdout
                sys.stdout = buf
                try:
                    usage_stats.main([])
                finally:
                    sys.stdout = old
                out = buf.getvalue()
        self.assertIn("search_qdrant: 3", out)
        self.assertIn("mini_first: 2", out)
        self.assertIn("零命中: 1", out)
        self.assertIn("full: 1", out)

    def test_stats_missing_file(self):
        from plugin.scripts import usage_stats
        with mock.patch.object(usage_stats, "USAGE_LOG", Path("/nonexistent-xyz.jsonl")):
            self.assertEqual(usage_stats.main([]), 0)


class TestHandlerInstrumentation(unittest.TestCase):

    def test_search_qdrant_logs_chunk_mode(self):
        from plugin.tools import HANDLERS
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(usage_log, "USAGE_LOG", Path(tmp) / "usage_log.jsonl"), \
                 mock.patch("plugin.tools.search_qdrant", return_value=[]):
                HANDLERS["search_qdrant"]({"query": "q", "chunk_mode": "auto"})
            e = json.loads(_read_day_lines(Path(tmp))[-1])
            self.assertEqual(e["chunk_mode"], "auto")
            self.assertEqual(e["mode"], "single")
            self.assertEqual(e["hits"], 0)
            # 21 号 P2 零命中治理：query 文本必须入日志，否则不知道「什么查询」零命中
            self.assertEqual(e["query"], "q")

    def test_wrap_tool_logs_args(self):
        """21 号 2B 后 gap_log 仅 partial 时写 params——full 路径的入参观测靠 usage 的 args 字段。"""
        from plugin.tools import HANDLERS, _init
        _init()
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(usage_log, "USAGE_LOG", Path(tmp) / "usage_log.jsonl"):
                # 批 U-0（2026-10-11）：Hermes 真实通道＝kwargs（entry.handler(args, **kwargs)）。
                # 旧版测试把 task_id 塞进 args——那恰好掩盖了「9 个 Tool 恒为 None」的缺陷。
                HANDLERS["get_prerequisites"]({"operation": "start_rule"},
                                              task_id="t-1", session_id="s-1")
            e = json.loads(_read_day_lines(Path(tmp))[-1])
            self.assertEqual(e["args"], {"operation": "start_rule"})  # args 内无会话字段
            self.assertEqual(e["task_id"], "t-1")  # 独立字段承载（压测流量无此字段 = 可分离）
            self.assertEqual(e["session_id"], "s-1")
            self.assertEqual(e["confidence"], "full")
            # 2A 指标字段齐全
            for k in ("duration_ms", "out_chars", "out_tokens_est"):
                self.assertIn(k, e)

    def test_no_task_id_field_when_absent(self):
        """裸调用（无 task_id）不应带该字段——据此与 Hermes 真实会话流量区分。"""
        from plugin.tools import HANDLERS, _init
        _init()
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(usage_log, "USAGE_LOG", Path(tmp) / "usage_log.jsonl"):
                HANDLERS["get_prerequisites"]({"operation": "start_rule"})
            e = json.loads(_read_day_lines(Path(tmp))[-1])
            self.assertNotIn("task_id", e)

    def test_log_args_truncates_and_skips_empty(self):
        from plugin.tools import _log_args
        snap = _log_args({"error_code": "X" * 200, "empty": "", "none": None,
                          "list": [], "task_id": "t", "keywords": ["双活"]})
        self.assertEqual(snap["error_code"], "X" * 80)  # 截断到 80
        self.assertNotIn("empty", snap)
        self.assertNotIn("none", snap)
        self.assertNotIn("list", snap)
        self.assertNotIn("task_id", snap)
        self.assertEqual(snap["keywords"], ["双活"])


if __name__ == "__main__":
    unittest.main()
