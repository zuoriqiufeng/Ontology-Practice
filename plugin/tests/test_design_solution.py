"""Tests for design_solution handler."""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from plugin.tools import HANDLERS


class TestDesignSolution(unittest.TestCase):

    def _call(self, **kwargs):
        raw = HANDLERS["design_solution"](kwargs)
        return json.loads(raw)

    def test_auto_hint_matches_migration(self):
        data = self._call(source="Oracle", target="MySQL")
        self.assertEqual(data["scenario"], "跨平台迁移")

    def test_migration_hint(self):
        data = self._call(source="Oracle", target="MySQL", scenario_hint="migration")
        self.assertEqual(data["scenario"], "跨平台迁移")

    def test_dual_active_hint_for_same_db(self):
        data = self._call(source="Oracle", target="Oracle", scenario_hint="dual_active")
        self.assertEqual(data["scenario"], "数据库双活")

    def test_bigdata_hint(self):
        data = self._call(source="Oracle", target="Kafka", scenario_hint="bigdata")
        self.assertEqual(data["scenario"], "大数据采集分析")

    def test_disaster_recovery_hint(self):
        data = self._call(source="Oracle", target="MySQL", scenario_hint="disaster_recovery")
        self.assertEqual(data["scenario"], "两地三中心")

    def test_unknown_hint_falls_back_to_auto(self):
        data = self._call(source="Oracle", target="MySQL", scenario_hint="not_a_real_hint")
        # 未映射 hint 回退自动匹配，应为跨平台迁移
        self.assertEqual(data["scenario"], "跨平台迁移")


if __name__ == "__main__":
    unittest.main()
