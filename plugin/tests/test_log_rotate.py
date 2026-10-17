"""Tests for log_rotate (v1.7): size-triggered rotation with backup retention."""

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

from plugin.log_rotate import rotate_if_needed


class TestRotateIfNeeded(unittest.TestCase):

    def _make_file(self, tmp: str, name: str, size: int) -> Path:
        p = Path(tmp) / name
        p.write_text("x" * size, encoding="utf-8")
        return p

    def test_below_threshold_no_rotation(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._make_file(tmp, "t.jsonl", 100)
            self.assertFalse(rotate_if_needed(p, max_bytes=1000, backups=3))
            self.assertTrue(p.exists())
            self.assertFalse((Path(tmp) / "t.jsonl.1").exists())

    def test_above_threshold_rotates(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._make_file(tmp, "t.jsonl", 100)
            self.assertTrue(rotate_if_needed(p, max_bytes=50, backups=3))
            self.assertFalse(p.exists())  # 原文件已 rename
            self.assertTrue((Path(tmp) / "t.jsonl.1").exists())

    def test_backup_chain_shifts(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "t.jsonl"
            # 预置 .1 和 .2
            (Path(tmp) / "t.jsonl.1").write_text("old1", encoding="utf-8")
            (Path(tmp) / "t.jsonl.2").write_text("old2", encoding="utf-8")
            p.write_text("current" * 20, encoding="utf-8")

            rotate_if_needed(p, max_bytes=10, backups=3)
            self.assertEqual((Path(tmp) / "t.jsonl.1").read_text(), "current" * 20)
            self.assertEqual((Path(tmp) / "t.jsonl.2").read_text(), "old1")
            self.assertEqual((Path(tmp) / "t.jsonl.3").read_text(), "old2")

    def test_oldest_backup_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "t.jsonl"
            for i in range(1, 4):
                (Path(tmp) / f"t.jsonl.{i}").write_text(f"backup{i}", encoding="utf-8")
            p.write_text("current" * 20, encoding="utf-8")

            rotate_if_needed(p, max_bytes=10, backups=3)
            # .3 被删除，.2→.3, .1→.2, current→.1
            self.assertEqual((Path(tmp) / "t.jsonl.3").read_text(), "backup2")
            self.assertFalse((Path(tmp) / "t.jsonl.4").exists())

    def test_rotation_failure_silent(self):
        # 不存在的路径 + 无法创建的目录，不应抛异常
        p = Path("/nonexistent-dir-xyz/t.jsonl")
        self.assertFalse(rotate_if_needed(p, max_bytes=1, backups=3))

    def test_missing_file_no_rotation(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "missing.jsonl"
            self.assertFalse(rotate_if_needed(p, max_bytes=1, backups=3))


class TestWritePathIntegration(unittest.TestCase):
    """log_gap / log_usage 写入日期命名文件；写入前同日大小轮转触发"""

    def test_log_gap_rotates_when_oversized(self):
        from datetime import date
        from plugin import supplement
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "gap_log.jsonl"
            day = base.with_name(f"gap_log_{date.today().isoformat()}.jsonl")
            day.write_text("x" * 200, encoding="utf-8")
            with mock.patch.object(supplement, "GAP_LOG_PATH", base):
                from plugin.log_rotate import rotate_day_file
                from plugin.config import LOG_ROTATE_GAP_MAX_BYTES, LOG_ROTATE_BACKUPS
                # 直接调用轮转（模拟 log_gap 内部行为，用小阈值强制触发）
                rotate_day_file(base, max_bytes=100, backups=LOG_ROTATE_BACKUPS)
                # 再写入（落到轮转后的新当日文件）
                supplement.log_gap("test_tool", {"a": 1}, "partial", ["gap1"])
            self.assertTrue(
                (Path(tmp) / f"gap_log_{date.today().isoformat()}.jsonl.1").exists())
            content = day.read_text(encoding="utf-8")
            self.assertIn("test_tool", content)

    def test_log_usage_rotates_when_oversized(self):
        from datetime import date
        from plugin import usage_log
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "usage_log.jsonl"
            day = base.with_name(f"usage_log_{date.today().isoformat()}.jsonl")
            day.write_text("y" * 200, encoding="utf-8")
            with mock.patch.object(usage_log, "USAGE_LOG", base):
                from plugin.log_rotate import rotate_day_file
                rotate_day_file(base, max_bytes=100, backups=3)
                usage_log.log_usage("search_qdrant", chunk_mode="auto", hits=1)
            self.assertTrue(
                (Path(tmp) / f"usage_log_{date.today().isoformat()}.jsonl.1").exists())
            content = day.read_text(encoding="utf-8")
            self.assertIn("search_qdrant", content)


class TestDayRotation(unittest.TestCase):
    """2026-09-30 日期+大小双维轮转：文件名带日期 / 跨日开新文件 / retention 清理 / 读侧兼容"""

    def test_day_file_path_naming(self):
        from datetime import date
        from plugin.log_rotate import day_file_path
        base = Path("/x/usage_log.jsonl")
        self.assertEqual(day_file_path(base, "2026-09-30").name, "usage_log_2026-09-30.jsonl")
        self.assertEqual(day_file_path(base).name, f"usage_log_{date.today().isoformat()}.jsonl")
        # 非 .jsonl 后缀也成立
        self.assertEqual(day_file_path(Path("/x/a.log"), "2026-01-02").name, "a_2026-01-02.log")

    def test_cross_day_opens_new_file(self):
        from datetime import datetime
        from plugin.log_rotate import rotate_day_file
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "u.jsonl"
            d1 = rotate_day_file(base, max_bytes=1000, now=datetime(2026, 9, 29, 23, 59))
            d1.write_text("day1", encoding="utf-8")  # 模拟写入方追加（rotate_day_file 只返回路径）
            d2 = rotate_day_file(base, max_bytes=1000, now=datetime(2026, 9, 30, 0, 1))
            self.assertEqual(d1.name, "u_2026-09-29.jsonl")
            self.assertEqual(d2.name, "u_2026-09-30.jsonl")
            d2.write_text("day2", encoding="utf-8")
            self.assertTrue(d1.exists() and d2.exists())

    def test_same_day_size_rotation_suffix(self):
        from datetime import datetime
        from plugin.log_rotate import rotate_day_file
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "u.jsonl"
            now = datetime(2026, 9, 30, 10, 0)
            d = rotate_day_file(base, max_bytes=1000, now=now)
            d.write_text("x" * 200, encoding="utf-8")
            # 同日再次调用且已超限 → 当日文件轮转出 .1，返回路径仍为当日主文件
            rotate_day_file(base, max_bytes=100, now=now)
            self.assertTrue((Path(tmp) / "u_2026-09-30.jsonl.1").exists())
            self.assertEqual(d.name, "u_2026-09-30.jsonl")
            self.assertFalse(d.exists())  # 主文件已被改名，等待新写入

    def test_retention_prunes_old_days(self):
        from datetime import datetime
        from plugin.log_rotate import rotate_day_file
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "u.jsonl"
            (Path(tmp) / "u_2026-09-01.jsonl").write_text("old", encoding="utf-8")
            (Path(tmp) / "u_2026-09-01.jsonl.1").write_text("old-shard", encoding="utf-8")
            (Path(tmp) / "u_2026-09-28.jsonl").write_text("recent", encoding="utf-8")
            (Path(tmp) / "u.jsonl").write_text("legacy", encoding="utf-8")
            rotate_day_file(base, max_bytes=1000, retention_days=7,
                            now=datetime(2026, 9, 30, 10, 0))
            self.assertFalse((Path(tmp) / "u_2026-09-01.jsonl").exists())
            self.assertFalse((Path(tmp) / "u_2026-09-01.jsonl.1").exists())
            self.assertTrue((Path(tmp) / "u_2026-09-28.jsonl").exists())  # cutoff=09-23，保留
            self.assertTrue((Path(tmp) / "u.jsonl").exists())  # 旧命名不参与 retention 清理

    def test_iter_data_files_old_new_compatible(self):
        from plugin.log_rotate import iter_data_files, load_jsonl_entries
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "u.jsonl"
            (base).write_text('{"a": 1}\n', encoding="utf-8")
            (Path(tmp) / "u.jsonl.1").write_text('{"a": 2}\n', encoding="utf-8")
            (Path(tmp) / "u.jsonl.pre-observation.bak").write_text('{"bak": true}\n', encoding="utf-8")
            (Path(tmp) / "u_2026-09-29.jsonl").write_text('{"a": 3}\n', encoding="utf-8")
            (Path(tmp) / "u_2026-09-29.jsonl.1").write_text('{"a": 4}\n', encoding="utf-8")
            files = iter_data_files(base)
            names = [f.name for f in files]
            self.assertIn("u.jsonl", names)
            self.assertIn("u.jsonl.1", names)
            self.assertIn("u_2026-09-29.jsonl", names)
            self.assertIn("u_2026-09-29.jsonl.1", names)
            self.assertNotIn("u.jsonl.pre-observation.bak", names)  # .bak 不参与统计
            entries = load_jsonl_entries(base)
            self.assertEqual(sorted(e["a"] for e in entries), [1, 2, 3, 4])


if __name__ == "__main__":
    unittest.main()
