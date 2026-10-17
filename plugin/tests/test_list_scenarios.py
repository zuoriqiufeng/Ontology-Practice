"""Tests for list_scenarios keyword handling."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from unittest.mock import MagicMock, patch
from plugin.tools import HANDLERS


class TestListScenariosKeywords(unittest.TestCase):

    _MOCK_SCENARIOS = [
        {"id": "data_migration", "name": "数据迁移场景", "keywords": ["数据迁移"], "file": "scenarios/data-migration.bkn"},
        {"id": "migration", "name": "跨平台迁移", "keywords": ["迁移"], "file": "scenarios/dual-active.bkn"},
        {"id": "bigdata", "name": "大数据采集分析", "keywords": ["大数据", "Kafka"], "file": "scenarios/bigdata-pipeline.bkn"},
    ]

    def _call(self, keywords):
        mock_resolver = MagicMock()
        mock_resolver.list_scenarios.return_value = self._MOCK_SCENARIOS
        mock_loader = MagicMock()
        mock_loader.process.side_effect = lambda data, _: __import__("json").dumps(data, ensure_ascii=False)
        with patch("plugin.tools._init"), \
             patch("plugin.tools._resolver", mock_resolver), \
             patch("plugin.tools._loader", mock_loader), \
             patch("plugin.tools.assess_confidence", return_value=("full", [])):
            return HANDLERS["list_scenarios"]({"keywords": keywords})

    def test_string_keyword_treated_as_single_term(self):
        raw = self._call("数据迁移")
        self.assertIn("数据迁移场景", raw)
        self.assertNotIn("跨平台迁移", raw)
        self.assertNotIn("大数据采集分析", raw)

    def test_list_keyword_filters_same_as_string(self):
        raw = self._call(["数据迁移"])
        self.assertIn("数据迁移场景", raw)
        self.assertNotIn("跨平台迁移", raw)
        self.assertNotIn("大数据采集分析", raw)

    def test_invalid_keyword_type_defaults_to_empty(self):
        raw = self._call(123)
        self.assertIn("数据迁移场景", raw)
        self.assertIn("跨平台迁移", raw)
        self.assertIn("大数据采集分析", raw)


if __name__ == "__main__":
    unittest.main()
