"""批 U-0：`task_id`/`session_id` 穿透的端到端通道测试（25 号 §2 / §5 I7）。

Hermes 的调用形态＝`entry.handler(args, **kwargs)`，kwargs 携带 task_id/session_id；
缺陷时期 `_wrap` 按 `args.get("task_id")` 取 → 9 个走 `_wrap` 的 Tool 恒为 None，
唯一读对通道的 search_qdrant 又没把会话标识写进日志（22 号 §1.2#10b）。

本测试用**真实调用形态**驱动全部 13 个 handler：usage_log 的**工具调用**行必须带非空会话字段
（进程级事件 `risk_guard_assembly` / `bkn_reload` 不带，不在此列）；
未登记码的 gap_log 条目也必须带 task_id；裸调用（无 kwargs）保持旧形状（真假流量分离器）。
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

from plugin import supplement, usage_log  # noqa: E402
from plugin.tools import HANDLERS, _init  # noqa: E402

TASK = "t-e2e-0001"
SESSION = "s-e2e-0001"

#: 13 个 handler 的最小可用入参（错误分支也必须记日志——豁免 Tool 的盲区之一）
CASES = {
    "query_product": {"aspect": "overview"},
    "explain_architecture": {"topic": "all"},
    "design_solution": {"scenario_hint": "auto", "source": "oracle", "target": "mysql"},
    "check_compatibility": {"source": "oracle", "target": "mysql"},
    "list_scenarios": {},
    "diagnose_error": {"error_code": "-4073"},   # 裸码 → 诚实兜底（非 full）→ 同时覆盖 gap 通道
    "get_prerequisites": {"operation": "start_rule"},
    "resolve_relation": {"relation_type": "suspected_in",
                         "source_entity": "symptom:incremental_stuck"},
    "resolve_operation": {"operation": "start_rule"},
    "search_qdrant": {"query": "e2e", "top_k": 1},
    "diagnose_db_link": {"symptom": "e2e 冒烟", "db_type": "oracle"},
    "check_action_risk": {"action": "restart_rule", "current_state": "RUNNING"},
    "diagnose_mechanism": {"entry": "incremental_stuck"},
}


def _read_lines(dirpath: Path, prefix: str) -> list[str]:
    lines: list[str] = []
    for f in sorted(dirpath.glob(f"{prefix}_*.jsonl")):
        lines.extend(l for l in f.read_text(encoding="utf-8").splitlines() if l.strip())
    return lines


class TestU0Channel(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        _init()

    def test_all_handlers_carry_session(self):
        """I7：13 个 handler 以 Hermes 形态调用 → usage_log 的**工具调用**行带非空 task_id/session_id。"""
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            with mock.patch.object(usage_log, "USAGE_LOG", tmpdir / "usage_log.jsonl"), \
                 mock.patch("plugin.tools.search_qdrant", return_value=[]), \
                 mock.patch("plugin.supplement.search_qdrant", return_value=[]):
                for name in sorted(CASES):
                    HANDLERS[name](dict(CASES[name]), task_id=TASK, session_id=SESSION)
            entries = [json.loads(l) for l in _read_lines(tmpdir, "usage_log")]
            logged = {e.get("tool") for e in entries}
            missing = sorted(n for n in CASES if n not in logged)
            self.assertEqual(missing, [], f"这些 handler 没写 usage_log：{missing}")
            # 只查**工具调用**行：`risk_guard_assembly` / `bkn_reload` 是**进程级事件**
            # （risk_guard.py:517 / loaded_version.py:87），本就不带会话字段；全量套件里它们
            # 多由更早的测试触发 ⇒ 原「逐条检查」实际依赖执行顺序（单独跑本文件即红）。
            calls = [e for e in entries if e.get("tool") in CASES]
            bad = [(e.get("tool"), e.get("task_id"), e.get("session_id")) for e in calls
                   if e.get("task_id") != TASK or e.get("session_id") != SESSION]
            self.assertEqual(bad, [], f"会话字段缺失/不符：{bad}")

    def test_bare_call_has_no_session_fields(self):
        """压测/裸脚本调用（无 kwargs）仍不带会话字段——真假流量的分离器。"""
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            with mock.patch.object(usage_log, "USAGE_LOG", tmpdir / "usage_log.jsonl"):
                HANDLERS["get_prerequisites"]({"operation": "start_rule"})
            e = json.loads(_read_lines(tmpdir, "usage_log")[-1])
            self.assertNotIn("task_id", e)
            self.assertNotIn("session_id", e)

    def test_gap_log_carries_task_id(self):
        """非 full 调用的 gap_log 条目带 task_id（会话内缺口聚合的前提）；裸调用不写字段。

        用「参数缺失」（空 args → partial）构造非 full：C-20261011-04 之后**未登记码也返回 full**
        （诊断候选一让裸码给出 needs/retrieval_guide，40/40），故不能再用未登记码。
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            with mock.patch.object(supplement, "GAP_LOG_PATH", tmpdir / "gap_log.jsonl"):
                HANDLERS["diagnose_error"]({}, task_id=TASK, session_id=SESSION)
            entries = [json.loads(l) for l in _read_lines(tmpdir, "gap_log")]
            self.assertTrue(entries, "空参数调用应产生 gap 记录（partial）")
            self.assertTrue(all(e.get("task_id") == TASK for e in entries), entries)
            with mock.patch.object(supplement, "GAP_LOG_PATH", tmpdir / "gap2.jsonl"):
                HANDLERS["diagnose_error"]({})
            e2 = [json.loads(l) for l in _read_lines(tmpdir, "gap2")]
            self.assertTrue(e2 and all("task_id" not in x for x in e2), e2)


if __name__ == "__main__":
    unittest.main()
