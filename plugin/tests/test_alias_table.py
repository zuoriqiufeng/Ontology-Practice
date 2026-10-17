"""别名机制 v2：aliases.yaml 数据表（43 号 §7 D11）。"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from plugin import resolver  # noqa: E402
from plugin.resolver import BKNResolver, _load_alias_table  # noqa: E402


class TestAliasTable(unittest.TestCase):

    def setUp(self):
        from plugin.config import BKN_ROOT
        self.root = BKN_ROOT

    def test_empty_table_is_safe(self):
        """空表（当前状态）→ 加载为 {}，行为与改造前一致。"""
        tbl = _load_alias_table()
        self.assertIsInstance(tbl, dict)
        self.assertEqual(tbl, {})

    def test_yaml_wins_over_constants(self):
        """同一别名同时出现在 constants 与 yaml → yaml 胜出（不静默继承）。"""
        old = resolver._ALIAS_TABLE
        try:
            resolver._ALIAS_TABLE = {"同步卡住": ("data_mismatch", "symptom")}
            r = BKNResolver(bkn_root=self.root)
            self.assertEqual(r.resolve_synonym("同步卡住"), "data_mismatch")
        finally:
            resolver._ALIAS_TABLE = old

    def test_yaml_alias_resolves_via_pipeline(self):
        old = resolver._ALIAS_TABLE
        try:
            resolver._ALIAS_TABLE = {"数据对不上号": ("data_mismatch", "symptom")}
            r = BKNResolver(bkn_root=self.root)
            self.assertEqual(r.resolve_mention("数据对不上号")[1], "alias")
        finally:
            resolver._ALIAS_TABLE = old


if __name__ == "__main__":
    unittest.main()
