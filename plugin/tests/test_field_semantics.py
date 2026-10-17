"""字段语义表结构与约束（30 号 W0-7；29 号 §4.3）

强制三件事：
1. 每个字段有 name / source / status，且 status 取值合法；
2. `confirmed` 必须有 evidence（有出处的断言不得空口）；
3. `unknown_unit` / `pending_field` 必须有 `needed`——写清"现场要确认什么"。
   这条是防"把缺口静默留下"：本表的全部价值就在于把未知**显式标注**出来。

另有一条 26 号零元信息的守卫：本表是 Tool 层值数据，**不得被 bkn/** 引用**。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TABLE = ROOT / "plugin" / "field_semantics.yaml"
VALID_STATUS = {"confirmed", "unknown_unit", "pending_field"}


class TestFieldSemantics(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.data = yaml.safe_load(TABLE.read_text(encoding="utf-8"))
        cls.fields = cls.data.get("fields") or []

    def test_fields_have_required_keys(self):
        bad = []
        for i, f in enumerate(self.fields):
            f = f or {}
            for k in ("name", "source", "status"):
                if not str(f.get(k, "")).strip():
                    bad.append(f"fields[{i}]: 缺 {k}")
            if f.get("status") not in VALID_STATUS:
                bad.append(f"fields[{i}] ({f.get('name')}): status 非法 {f.get('status')!r}")
        self.assertEqual(bad, [], bad)

    def test_confirmed_fields_carry_evidence(self):
        bad = [f.get("name") for f in self.fields
               if (f or {}).get("status") == "confirmed" and not (f or {}).get("evidence")]
        self.assertEqual(bad, [], f"以下 confirmed 字段无 evidence: {bad}")

    def test_unresolved_fields_declare_what_is_needed(self):
        """unknown_unit / pending_field 必须写清现场要确认什么（防静默留缺口）。"""
        bad = [f.get("name") for f in self.fields
               if (f or {}).get("status") in {"unknown_unit", "pending_field"}
               and not str((f or {}).get("needed", "")).strip()]
        self.assertEqual(bad, [], f"以下字段未写 needed（现场要确认什么）: {bad}")

    def test_at_least_one_unresolved_field_recorded(self):
        """哨兵：D2 案例的字段必须留在表里——把它们删掉等于把问题藏起来。"""
        names = {str((f or {}).get("name", "")) for f in self.fields}
        for must in ("delay", "max_delay", "dml_fail", "stage", "state_time", "last_op"):
            self.assertIn(must, names, f"字段 {must!r} 不应从语义表中消失（D2 案例的待确认项）")

    def test_table_is_not_referenced_by_bkn(self):
        """26 号零元信息：Tool 层值数据不得被 bkn/** 引用。"""
        offenders = []
        for path in (ROOT / "bkn").rglob("*"):
            if path.is_file() and "field_semantics" in path.read_text(encoding="utf-8", errors="ignore"):
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [], f"bkn/ 引用了 Tool 层值数据: {offenders}")

    def test_sources_are_declared(self):
        """fields 引用的 source 必须在顶層 sources 里声明。"""
        declared = set((self.data.get("sources") or {}))
        bad = sorted({str((f or {}).get("source")) for f in self.fields} - declared)
        self.assertEqual(bad, [], f"fields 引用了未声明的 source: {bad}")


if __name__ == "__main__":
    unittest.main()
