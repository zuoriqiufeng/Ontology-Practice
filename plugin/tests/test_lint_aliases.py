"""aliases.yaml 机检：悬空别名 / 可生成变体 / 缺 provenance（别名机制 v2）。"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from plugin.scripts.lint_bkn import _validate_alias_entries  # noqa: E402

CANON = {"incremental_stuck", "connection_error", "-4014"}
PROV = {"source": "real-session", "date": "2026-10-18", "evidence": "synonym_miss x2"}


class TestAliasLint(unittest.TestCase):

    def test_good_entry_passes(self):
        entries = [{"alias": "同步卡住很久", "canonical": "incremental_stuck",
                    "provenance": PROV, "scope": "symptom"}]
        self.assertEqual(_validate_alias_entries(entries, CANON), [])

    def test_ghost_canonical_rejected(self):
        entries = [{"alias": "某个说法", "canonical": "no_such_id", "provenance": PROV}]
        errs = _validate_alias_entries(entries, CANON)
        self.assertEqual(len(errs), 1)
        self.assertIn("幽灵别名", errs[0])

    def test_generated_form_rejected(self):
        entries = [{"alias": "-4014", "canonical": "-4014", "provenance": PROV}]
        errs = _validate_alias_entries(entries, CANON)
        self.assertEqual(len(errs), 1)
        self.assertIn("可生成变体", errs[0])

    def test_missing_provenance_rejected(self):
        entries = [{"alias": "某个说法", "canonical": "incremental_stuck"}]
        errs = _validate_alias_entries(entries, CANON)
        self.assertEqual(len(errs), 1)
        self.assertIn("provenance", errs[0])

    def test_empty_table_passes(self):
        self.assertEqual(_validate_alias_entries([], CANON), [])


if __name__ == "__main__":
    unittest.main()
