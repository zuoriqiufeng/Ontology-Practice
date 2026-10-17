"""批 C-20261012-19（44 号 §6 批 3）：usage_log 记录类别 record_type 与通用字段完整率。

根因（44 号 §6 批 3）：usage_log 有 6 个写入点、字段集各不相同——「args 35% /
confidence 47% / duration_ms 47%」是把三类**不同性质**的记录混在一起算的结果：
- call         工具调用级（_wrap / _log_exempt_call）→ 要求 args/confidence 齐全；
- call_detail  批量检索的查询明细（search_qdrant 自写两条）→ 天性没有 confidence；
- process      进程级事件（risk_guard 装配 / bkn_reload）→ 既无 args 也无 confidence。

本测试锁定四点：两条**真入口**写的记录必须是 call 且字段齐；process 事件必须是 process
且**不带 args**；call_detail 自写记录必须标注类别；聚合侧按类别分组统计正确。

日志路径 patch 照 test_trajectory.py 的 _ctx 范式（mock.patch.multiple 覆盖模块全局）。
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from plugin import loaded_version, risk_guard, usage_log  # noqa: E402
from plugin.tools import HANDLERS, _init  # noqa: E402

SCRIPTS = ROOT / "plugin" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
import usage_stats  # noqa: E402

TASK = "t-rt-0001"
SESSION = "s-rt-0001"

#: call 级记录必须齐的通用字段（confidence 是调用级判据，args 是本批的补齐项）
CALL_FIELDS = ("args", "confidence", "out_chars", "duration_ms", "task_id")


def _read_entries(tmpdir: Path) -> list[dict]:
    """读 tmpdir 下当日 usage_log 全部条目（基名被 patch 成 usage_log.jsonl，写入按日期派生）。"""
    entries: list[dict] = []
    for f in sorted(Path(tmpdir).glob("usage_log_*.jsonl")):
        entries.extend(json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip())
    return entries


def _by_tool(tmpdir: Path, tool: str) -> list[dict]:
    return [e for e in _read_entries(tmpdir) if e.get("tool") == tool]


class TestUsageRecordTypes(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        _init()

    def _ctx(self, tmpdir: Path):
        """把 usage_log 的逻辑基名指到 tmpdir（写入由 rotate_day_file 派生日期文件名）。"""
        return mock.patch.multiple(usage_log, USAGE_LOG=tmpdir / "usage_log.jsonl")

    def _run(self, tmpdir: Path, tool: str, args: dict):
        """真入口调用 + 只取该 tool 的 usage 条目（bkn_reload 进程事件可能同落一盘）。"""
        with self._ctx(tmpdir):
            HANDLERS[tool](args, task_id=TASK, session_id=SESSION)
        return _by_tool(tmpdir, tool)

    def test_wrap_path_writes_call_record_with_fields(self):
        """① _wrap 路径（get_prerequisites 真入口）→ record_type=call，通用字段齐全。"""
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            entries = self._run(tmpdir, "get_prerequisites", {"operation": "start_rule"})
            self.assertEqual(len(entries), 1, entries)
            e = entries[0]
            self.assertEqual(e["record_type"], "call")
            for k in CALL_FIELDS:
                self.assertIn(k, e)
            self.assertEqual(e["args"], {"operation": "start_rule"})   # 不含会话字段
            self.assertEqual(e["task_id"], TASK)
            self.assertEqual(e["session_id"], SESSION)

    def test_exempt_path_writes_call_record_with_args(self):
        """② 豁免路径（check_action_risk 真入口）→ record_type=call 且**含 args**。

        44 号 §6 批 3 之前，豁免三 Tool 正是 args 缺记的来源（_log_exempt_call 不写 args）。
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            entries = self._run(tmpdir, "check_action_risk",
                                {"action": "delete_sync_rule", "current_state": "RUNNING"})
            self.assertTrue(entries, "check_action_risk 未写 usage_log")
            e = entries[-1]
            self.assertEqual(e["record_type"], "call")
            self.assertEqual(e["args"], {"action": "delete_sync_rule",
                                         "current_state": "RUNNING"})
            for k in CALL_FIELDS:
                self.assertIn(k, e)

    def test_process_event_has_no_args(self):
        """③ 进程级事件 → record_type=process 且**不含** args/confidence。

        用 risk_guard._emit_assembly_event 直触发：装配事件每进程只写一条（_load_rules
        缓存守卫），直调是稳定的触发法；真入口路径已由 test_batch4_observability.py 覆盖。
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            with self._ctx(tmpdir):
                risk_guard._emit_assembly_event({"r1": {"source": "fallback"},
                                                 "r2": {"source": "graph"}}, error=None)
            entries = _by_tool(tmpdir, "risk_guard_assembly")
            self.assertEqual(len(entries), 1, entries)
            e = entries[0]
            self.assertEqual(e["record_type"], "process")
            self.assertNotIn("args", e)
            self.assertNotIn("confidence", e)
            self.assertEqual(e["rules_assembled"], 1)

    def test_bkn_reload_event_is_process(self):
        """③b 另一条进程级事件（loaded_version._emit_reload_event）→ record_type=process。"""
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            loaded_version.reset_for_tests()
            with self._ctx(tmpdir):
                loaded_version._emit_reload_event(
                    "bkn-old",
                    {"version_id": "bkn-new", "record_hash": "0123456789abcdef",
                     "trigger": "test"}, ms=1)
            entries = _by_tool(tmpdir, "bkn_reload")
            self.assertEqual(len(entries), 1, entries)
            self.assertEqual(entries[0]["record_type"], "process")
            self.assertNotIn("args", entries[0])

    def test_batch_detail_records_are_call_detail_with_args(self):
        """A3 覆盖：批量路径两条自写记录 → record_type=call_detail，且 args 由 handler 透传。

        Qdrant 在本环境不可用，故 mock 掉 plugin.tools.search_qdrant（返回空命中）——
        走的是**真 handler → 真 _search_qdrant_batch_inner**，只是向量检索本身被替身。
        明细项显式带 chunk_mode="auto"：默认 SEARCH_CHUNK_MODE 是 mini_first，那条路由
        走 _search_mini_first（真连库）——mock 只能盖住 auto/父扩展两条路由。
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            with self._ctx(tmpdir), \
                 mock.patch("plugin.tools.search_qdrant", return_value=[]):
                HANDLERS["search_qdrant"](
                    {"queries": [{"query": "q1", "chunk_mode": "auto"},
                                 {"query": "q2", "chunk_mode": "auto"}]},
                    task_id=TASK, session_id=SESSION)
            entries = _by_tool(tmpdir, "search_qdrant")
            details = [e for e in entries if e.get("record_type") == "call_detail"]
            calls = [e for e in entries if e.get("record_type") == "call"]
            self.assertEqual(len(details), 3, entries)      # 2 条明细 + 1 条聚合
            self.assertEqual(len(calls), 1, entries)        # 出口的 _log_exempt_call
            for e in details:
                self.assertEqual(e["task_id"], TASK)
                self.assertIn("args", e)                    # args 由 handler 透传
                self.assertNotIn("confidence", e)           # 明细级天性没有 confidence
            aggregate = [e for e in details if e.get("queries") == 2]
            self.assertEqual(len(aggregate), 1, details)

    def test_field_coverage_groups_and_call_gate(self):
        """④ 聚合侧：四类分组统计正确，call 是唯一要判 100% 的行。"""
        entries = [
            {"tool": "a", "record_type": "call", "args": {}, "confidence": "full",
             "out_chars": 1, "duration_ms": 2, "task_id": TASK},
            {"tool": "a", "record_type": "call", "args": {}, "confidence": "full"},  # 缺 3 字段
            {"tool": "b", "record_type": "call_detail", "args": {}, "out_chars": 1},
            {"tool": "risk_guard_assembly", "record_type": "process", "out_chars": 1},
            {"tool": "legacy_tool", "confidence": "full"},        # 无 record_type → legacy
        ]
        rows = {r["record_type"]: r for r in usage_stats.field_coverage(entries)}
        self.assertEqual(rows["call"]["n"], 2)
        self.assertEqual(rows["call"]["rate"]["args"], 100.0)
        self.assertEqual(rows["call"]["rate"]["confidence"], 100.0)
        self.assertEqual(rows["call"]["rate"]["duration_ms"], 50.0)
        self.assertEqual(rows["call"]["rate"]["task_id"], 50.0)
        self.assertEqual(rows["call_detail"]["n"], 1)
        self.assertEqual(rows["call_detail"]["rate"]["args"], 100.0)
        self.assertEqual(rows["call_detail"]["rate"]["confidence"], 0.0)
        self.assertEqual(rows["process"]["rate"]["args"], 0.0)
        self.assertEqual(rows["legacy"]["n"], 1)
        self.assertEqual(rows["legacy"]["rate"]["task_id"], 0.0)

    def test_report_prints_section_and_missing_args_line(self):
        """④b 报表真打印：新段存在 + 「调用级记录 N 条，其中 args 缺失 M 条」+ 既有段不变。"""
        entries = [
            {"tool": "a", "ts": 1, "record_type": "call", "args": {}, "confidence": "full",
             "out_chars": 1, "duration_ms": 2, "task_id": TASK},
            {"tool": "b", "ts": 2, "record_type": "call", "confidence": "full",
             "out_chars": 1, "duration_ms": 2, "task_id": TASK},     # 缺 args → 真漏记 1 条
            {"tool": "risk_guard_assembly", "ts": 3, "record_type": "process"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "usage_log.jsonl"
            target.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
            with mock.patch.object(usage_stats, "USAGE_LOG", target):
                buf = io.StringIO()
                old = sys.stdout
                sys.stdout = buf
                try:
                    usage_stats.main([])
                finally:
                    sys.stdout = old
        out = buf.getvalue()
        self.assertIn("== 字段完整率（按 record_type 分组）==", out)
        self.assertIn("调用级记录 2 条，其中 args 缺失 1 条", out)
        self.assertIn("call        n=2", out)
        # 只增段：既有段一个不少（语义未动）
        for seg in ("== tool 调用分布 ==", "== confidence 分布 ==",
                    "== 耗时 (n=2)", "== BKN 约束覆盖率（risk_guard 装配事件）=="):
            self.assertIn(seg, out)


if __name__ == "__main__":
    unittest.main()
