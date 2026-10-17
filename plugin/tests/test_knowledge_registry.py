"""Tests for plugin/knowledge_registry.py."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from plugin.knowledge_registry import (
    BknRiskContextSource,
    BknSectionSource,
    DimensionResult,
    KnowledgeRegistry,
    KnowledgeSource,
    QdrantSearchSource,
)


class _StaticSource(KnowledgeSource):
    """测试用的固定返回 source。"""

    def __init__(self, name: str, priority: int, result: DimensionResult | None):
        self._name = name
        self._priority = priority
        self._result = result

    @property
    def name(self) -> str:
        return self._name

    @property
    def priority(self) -> int:
        return self._priority

    @property
    def source_type(self) -> str:
        return "test"

    def fetch(self, ctx: dict) -> DimensionResult | None:
        return self._result


class TestKnowledgeRegistry(unittest.TestCase):

    def test_empty_registry_returns_empty_list(self):
        registry = KnowledgeRegistry()
        self.assertEqual(registry.synthesize({}), [])

    def test_sources_are_executed_in_priority_order(self):
        calls = []

        class RecordingSource(KnowledgeSource):
            def __init__(self, name, priority):
                self._name = name
                self._priority = priority

            @property
            def name(self):
                return self._name

            @property
            def priority(self):
                return self._priority

            @property
            def source_type(self):
                return "test"

            def fetch(self, ctx):
                calls.append(self._name)
                return DimensionResult(name=self._name, phase="test", snippets=[{"content": self._name}])

        registry = KnowledgeRegistry([
            RecordingSource("mid", 5),
            RecordingSource("first", 1),
            RecordingSource("last", 10),
        ])
        results = registry.synthesize({})
        self.assertEqual(calls, ["first", "mid", "last"])
        self.assertEqual([r.name for r in results], ["first", "mid", "last"])

    def test_empty_results_are_not_included(self):
        registry = KnowledgeRegistry([
            _StaticSource("has-content", 1, DimensionResult("has-content", "test", [{"content": "x"}])),
            _StaticSource("no-content", 2, None),
            _StaticSource("empty-snippets", 3, DimensionResult("empty-snippets", "test", [])),
        ])
        results = registry.synthesize({})
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "has-content")

    def test_register_and_chain(self):
        registry = KnowledgeRegistry()
        registry.register(_StaticSource("a", 1, DimensionResult("a", "test", [{"content": "a"}])))
        registry.register(_StaticSource("b", 2, DimensionResult("b", "test", [{"content": "b"}])))
        results = registry.synthesize({})
        self.assertEqual([r.name for r in results], ["a", "b"])

    def test_source_exception_does_not_block_others(self):
        class FailingSource(KnowledgeSource):
            @property
            def name(self):
                return "failing"

            @property
            def priority(self):
                return 1

            @property
            def source_type(self):
                return "test"

            def fetch(self, ctx):
                raise RuntimeError("boom")

        registry = KnowledgeRegistry([
            FailingSource(),
            _StaticSource("ok", 2, DimensionResult("ok", "test", [{"content": "ok"}])),
        ])
        results = registry.synthesize({})
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "ok")


class TestBknSectionSource(unittest.TestCase):

    def test_returns_none_when_parent_missing(self):
        source = BknSectionSource("分析思路", "analysis_framework", "skill_map")
        self.assertIsNone(source.fetch({}))

    def test_returns_none_when_key_missing(self):
        source = BknSectionSource("分析思路", "analysis_framework", "skill_map")
        self.assertIsNone(source.fetch({"skill_map": {}}))

    def test_returns_none_when_text_empty(self):
        source = BknSectionSource("分析思路", "analysis_framework", "skill_map")
        self.assertIsNone(source.fetch({"skill_map": {"analysis_framework": "   "}}))

    def test_extracts_text_without_parent(self):
        source = BknSectionSource("Direct", "direct_key", source_label="bkn:direct.bkn")
        result = source.fetch({"direct_key": "  some content  "})
        self.assertIsNotNone(result)
        self.assertEqual(result.name, "Direct")
        self.assertEqual(result.phase, "bkn")
        self.assertEqual(result.snippets[0]["content"], "some content")
        self.assertEqual(result.snippets[0]["source"], "bkn:direct.bkn")
        self.assertEqual(result.snippets[0]["score"], 1.0)


class TestBknRiskContextSource(unittest.TestCase):

    def test_returns_none_when_no_context(self):
        source = BknRiskContextSource()
        self.assertIsNone(source.fetch({}))
        self.assertIsNone(source.fetch({"bkn_context": None}))

    def test_returns_none_when_context_empty(self):
        source = BknRiskContextSource()
        self.assertIsNone(source.fetch({"bkn_context": {}}))

    def test_builds_content_from_guidance_keys(self):
        """25 号：字段随锚点表删除更新为「指引字段」（原 6 属性字段已不存在）。"""
        source = BknRiskContextSource()
        ctx = {
            "bkn_context": {
                "retrieval_guide": "store:log_patterns_collection#错误码",
                "suspected_process": ["process:iatrack"],
                "aliases": ["日志解析异常"],
                "unknown_rule": "未登记错误码 → dimension:unknown + gap_log",
            }
        }
        result = source.fetch(ctx)
        self.assertIsNotNone(result)
        self.assertEqual(result.name, "错误码诊断指引")
        self.assertEqual(result.phase, "bkn")
        content = result.snippets[0]["content"]
        self.assertIn("完整定义检索源: store:log_patterns_collection#错误码", content)
        self.assertIn("嫌疑进程（suspected_in 边）: process:iatrack", content)
        self.assertIn("别名（归一用）: 日志解析异常", content)

    def test_legacy_six_field_context_returns_none(self):
        """旧 6 属性字段不再被消费（防回归：此前读旧字段导致该维度恒为 None）。"""
        source = BknRiskContextSource()
        ctx = {"bkn_context": {"risk_level": "CRITICAL", "trigger": "x", "handling": "y", "prohibitions": "z"}}
        self.assertIsNone(source.fetch(ctx))


class TestQdrantSearchSource(unittest.TestCase):

    def test_returns_none_when_query_empty(self):
        source = QdrantSearchSource("x", lambda ctx: "")
        self.assertIsNone(source.fetch({"search_fn": lambda *a, **k: []}))

    def test_returns_none_when_search_fn_missing(self):
        source = QdrantSearchSource("x", lambda ctx: "query")
        self.assertIsNone(source.fetch({}))

    def test_calls_search_and_track_functions(self):
        search_calls = []
        track_calls = []

        def fake_search(query, top_k=None, hybrid=True, collection=None):
            # 25 号接线：QdrantSearchSource 透传 ctx.collection（无则 None = 主集合）
            search_calls.append((query, top_k, hybrid, collection))
            return [{"content": f"hit for {query}", "score": 0.9, "source": "doc1"}]

        def fake_track(dim_name, count):
            track_calls.append((dim_name, count))

        source = QdrantSearchSource(
            "常见原因",
            lambda ctx: f"{ctx['symptom']} {ctx['db_type']} 原因",
            priority=10,
        )
        ctx = {
            "symptom": "data_mismatch",
            "db_type": "oracle",
            "search_fn": fake_search,
            "track_fn": fake_track,
            "top_k": 3,
            "hybrid": False,
        }
        result = source.fetch(ctx)
        self.assertIsNotNone(result)
        self.assertEqual(result.name, "常见原因")
        self.assertEqual(result.phase, "qdrant")
        self.assertEqual(search_calls, [("data_mismatch oracle 原因", 3, False, None)])
        self.assertEqual(track_calls, [("常见原因", 1)])

    def test_returns_none_when_search_returns_empty(self):
        source = QdrantSearchSource("x", lambda ctx: "query")
        self.assertIsNone(source.fetch({
            "search_fn": lambda *a, **k: [],
            "track_fn": lambda *a, **k: None,
        }))

    def test_swallows_search_exception(self):
        def failing_search(*a, **k):
            raise RuntimeError("qdrant down")

        source = QdrantSearchSource("x", lambda ctx: "query")
        self.assertIsNone(source.fetch({
            "search_fn": failing_search,
            "track_fn": lambda *a, **k: None,
        }))


class TestDimensionResult(unittest.TestCase):

    def test_to_dict(self):
        result = DimensionResult(
            name="分析思路",
            phase="bkn",
            snippets=[{"content": "先查字典"}],
        )
        self.assertEqual(result.to_dict(), {
            "name": "分析思路",
            "phase": "bkn",
            "snippets": [{"content": "先查字典"}],
        })


if __name__ == "__main__":
    unittest.main()
