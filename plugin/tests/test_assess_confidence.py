"""Tests for assess_confidence / _deep_check behavior.

21 号 2B 校准后的契约：
- full = BKN 对其职责（语义/骨架/指针）已完整——值委托改革后「骨架+指针」即完整交付；
- 已删除「无 enrichment 一律 partial」通用骨架规则（defer 模式下 enrichment 永不发生，
  曾使 9 Tool 100% partial，见 21 号 §1.1）；
- REQUIRED_FIELDS 支持 any-of 元组；字段长度下限 4（只拦近乎空，不再误伤短标识符）；
- diagnose_error 按 25 号 stub 契约校验（error_code + retrieval_guide）。
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from plugin.supplement import assess_confidence, _deep_check


class TestDeepCheck(unittest.TestCase):

    def test_no_skeleton_gap_anymore(self):
        """21 号 2B: 骨架通用规则已删——BKN-only 结果不再追加骨架缺口。"""
        result = {
            "raw": "这是一段足够长的 BKN 内容，" * 30,
            "tables": [],
            "kv": {"key": "value"},
        }
        gaps = _deep_check(result, "query_product")
        self.assertFalse(
            any("基础骨架" in g for g in gaps),
            f"骨架通用规则应已删除，实际 gaps={gaps}",
        )

    def test_enrichment_still_not_required(self):
        """enrichment/fallback_hint 不再影响判定（规则已删，两态一致）。"""
        result = {"raw": "BKN 骨架", "enrichment": {"snippets": ["Qdrant 补充片段"]}}
        gaps = _deep_check(result, "query_product")
        self.assertEqual(gaps, [])

    def test_design_solution_risk_threshold_is_3(self):
        """21 号 2B: min_risk_count 默认 5→3（BKN 单场景 risks_of 实测上限 3）。"""
        from plugin.config import SEARCH_MIN_RISK_COUNT
        self.assertEqual(SEARCH_MIN_RISK_COUNT, 3)

    def test_design_solution_relations_missing_keyword(self):
        """relations 缺关键词仍判缺口（具体检查保留）。"""
        result = {"relations": {"a": {"requires": ["b"]}}}
        gaps = _deep_check(result, "design_solution")
        self.assertTrue(any("constrains" in g for g in gaps))


class TestAssessConfidence(unittest.TestCase):

    def test_query_product_bkn_only_is_full(self):
        """值委托改革后，本体内容完整即 full（旧契约判 partial）。"""
        result = {
            "raw": "产品概述内容" * 50,
            "tables": [],
            "kv": {},
        }
        confidence, gaps = assess_confidence(result, {"aspect": "overview"}, "query_product")
        self.assertEqual(confidence, "full", f"gaps={gaps}")
        self.assertEqual(gaps, [])

    def test_query_product_delegated_aspect_is_full(self):
        """21 号 2B any-of：值委托 aspect 返回 delegated_to 指针即完整，不再要 raw。"""
        result = {
            "aspect": "competitors",
            "delegated_to": ["skill:demo_product-product-knowledge/references/product.md"],
            "note": "「竞品对比」不在本体层（23 号：值数据下延）",
        }
        confidence, gaps = assess_confidence(result, {"aspect": "competitors"}, "query_product")
        self.assertEqual(confidence, "full", f"gaps={gaps}")

    def test_diagnose_error_stub_is_full(self):
        """25 号 stub 契约：error_code + retrieval_guide 齐即 full，不再要 diagnosis 全文。"""
        result = {
            "error_code": "-4073",
            "retrieval_guide": "完整定义与修复步骤查 store:log_patterns_collection#错误码",
            "suspected_process": ["process:iatrack"],
            "dimensions": [],
            "aliases": [],
            "unknown_rule": "未登记错误码 → dimension:unknown（search_qdrant 兜底）+ gap_log 记录",
        }
        confidence, gaps = assess_confidence(result, {"error_code": "-4073"}, "diagnose_error")
        self.assertEqual(confidence, "full", f"gaps={gaps}")

    def test_diagnose_error_unknown_code_is_partial(self):
        """未登记错误码（无 retrieval_guide）仍判 partial，触发 Qdrant 兜底。"""
        result = {
            "error_code": "-99999",
            "diagnosis": "未在 BKN 中找到该错误码的诊断信息",
        }
        confidence, gaps = assess_confidence(result, {"error_code": "-99999"}, "diagnose_error")
        self.assertEqual(confidence, "partial")
        self.assertTrue(any("retrieval_guide" in g for g in gaps))

    def test_short_identifiers_not_flagged(self):
        """21 号 2B: 长度下限 10→4，error_code('-4073')/operation('failover') 不再误报。"""
        result = {
            "operation": "failover",
            "prerequisites": "前置条件完整清单，含负责 Skill 指针",
        }
        confidence, gaps = assess_confidence(result, {"operation": "failover"}, "get_prerequisites")
        self.assertEqual(confidence, "full", f"gaps={gaps}")

    def test_empty_required_field_still_partial(self):
        """真缺字段仍判 partial——校准不放松真实缺口。"""
        result = {
            "operation": "failover",
            "prerequisites": "",
        }
        confidence, gaps = assess_confidence(result, {"operation": "failover"}, "get_prerequisites")
        self.assertEqual(confidence, "partial")
        self.assertTrue(any("prerequisites" in g for g in gaps))

    def test_check_compatibility_is_full(self):
        """supported + delegated_to 齐即 full（23 号值委托契约）。"""
        result = {
            "supported": True,
            "source": "Oracle",
            "target": "OceanBase",
            "delegated_to": ["skill:demo_product-migration-designer/references/compatibility.md"],
        }
        confidence, gaps = assess_confidence(
            result, {"source": "Oracle", "target": "OceanBase"}, "check_compatibility"
        )
        self.assertEqual(confidence, "full", f"gaps={gaps}")

    def test_list_scenarios_is_full(self):
        """场景骨架列表是本 Tool 的完整契约（详情由 design_solution/Skill 承载）。"""
        result = {
            "scenarios": [
                {"id": "migration", "name": "数据迁移", "keywords": ["迁移"], "file": "scenarios/migration.bkn"}
            ] * 5,
        }
        confidence, gaps = assess_confidence(result, {}, "list_scenarios")
        self.assertEqual(confidence, "full", f"gaps={gaps}")

    def test_empty_result_is_none(self):
        confidence, gaps = assess_confidence({}, {}, "query_product")
        self.assertEqual(confidence, "none")
        self.assertTrue(gaps)


if __name__ == "__main__":
    unittest.main()
