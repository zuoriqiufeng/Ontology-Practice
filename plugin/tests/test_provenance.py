"""来源侧车结构与覆盖（24 号 D4 / 22 号批 2-4；不变量 I5）

强制三件事：
1. 每条 entry 有 `target` / `sources` / `checked_at`；`target` 形如 `constraint:xxx` 或 `state_machine:xxx`；
2. `sources` 非空时每条要有 `type` / `ref` / 合法 `strength`；
3. **`sources` 为空（unknown）时必须有 `needs`**——写清"要从哪取证"。
   这条是防"把缺口静默留下"：本文件的全部价值就是把未知**显式标注**出来。

覆盖一致性（每个 constraint ID 都有条目）由 `lint_bkn.py::_check_provenance_coverage` 强制——
本测试不重复它，只守结构与"不许静默留未知"。
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SIDECAR = ROOT / "plugin" / "provenance.yaml"
VALID_STRENGTH = {"strong", "medium", "medium+", "weak", "unknown"}
TARGET_RE = re.compile(r"^(?:constraint|state_machine):[A-Za-z0-9_]+$")


class TestProvenanceSidecar(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.data = yaml.safe_load(SIDECAR.read_text(encoding="utf-8")) or {}
        cls.entries = cls.data.get("entries") or []

    def test_entries_have_required_fields(self):
        bad = []
        for i, e in enumerate(self.entries):
            e = e or {}
            if not TARGET_RE.match(str(e.get("target", ""))):
                bad.append(f"entries[{i}]: target 非法 {e.get('target')!r}")
            if not str(e.get("checked_at", "")).strip():
                bad.append(f"entries[{i}] ({e.get('target')}): 缺 checked_at")
            if "sources" not in e:
                bad.append(f"entries[{i}] ({e.get('target')}): 缺 sources（无证据也要显式写空列表）")
        self.assertEqual(bad, [], bad)

    def test_sources_are_well_formed(self):
        bad = []
        for e in self.entries:
            for j, s in enumerate((e or {}).get("sources") or []):
                s = s or {}
                if not str(s.get("ref", "")).strip():
                    bad.append(f"{e.get('target')} sources[{j}]: 缺可定位的 ref")
                if not str(s.get("type", "")).startswith("S"):
                    bad.append(f"{e.get('target')} sources[{j}]: type 应为 S1–S7，得 {s.get('type')!r}")
                if s.get("strength") not in VALID_STRENGTH:
                    bad.append(f"{e.get('target')} sources[{j}]: strength 非法 {s.get('strength')!r}")
        self.assertEqual(bad, [], bad)

    def test_unknown_entries_declare_what_is_needed(self):
        """无来源的条目必须写清"要从哪取证"（防静默留缺口）。"""
        bad = [e.get("target") for e in self.entries
               if not (e or {}).get("sources")
               and not str((e or {}).get("needs", "")).strip()]
        self.assertEqual(bad, [], f"以下条目无来源却未写 needs: {bad}")

    def test_coverage_block_matches_entries(self):
        """coverage 块的数字必须与实际条目一致——防"报告与事实脱节"。"""
        cov = self.data.get("coverage") or {}
        if not cov:
            self.skipTest("无 coverage 块")
        constraints = [e for e in self.entries if str(e.get("target", "")).startswith("constraint:")]
        self.assertEqual(cov.get("constraints_total"), len(constraints),
                         "coverage.constraints_total 与 entries 实际条数不符")
        for key, want in (("constraints_strong", "strong"), ("constraints_medium", "medium")):
            actual = sum(1 for e in constraints
                         if any((s or {}).get("strength") == want for s in (e.get("sources") or [])))
            self.assertEqual(cov.get(key), actual, f"coverage.{key} 与实际不符（实际 {actual}）")

    def test_sidecar_is_not_referenced_by_bkn(self):
        """26 号零元信息：来源侧车是 Tool 层值数据，不得被 bkn/** 引用。"""
        offenders = []
        for p in (ROOT / "bkn").rglob("*"):
            if p.is_file() and "provenance" in p.read_text(encoding="utf-8", errors="ignore"):
                offenders.append(str(p.relative_to(ROOT)))
        self.assertEqual(offenders, [], f"bkn/ 引用了 Tool 层侧车: {offenders}")

    def test_has_entries(self):
        """哨兵：侧车不应为空壳。"""
        self.assertGreaterEqual(len(self.entries), 20, "侧车条目过少，可能被误改")


if __name__ == "__main__":
    unittest.main()
