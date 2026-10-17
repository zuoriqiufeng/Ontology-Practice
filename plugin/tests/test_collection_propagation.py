"""Tests for 21 号 2E: collection 透传到 BM25 / 精确索引 / 精度保护（防跨集合污染）。

背景：`search_qdrant` 的 collection 参数（批 6-3 引入）只穿过了 dense 路径，
同函数内的 BM25+RRF、precision guard、精确索引全部回落到默认主集合；批量模式更是
完全丢弃 collection。实测后果：diagnose_db_link 返回的知识片段有 33% 来自主集合
（该返回日志模式库）；含精确项的查询触发 guard 时 5/5 全打错集合。
本文件用 spy 锁住「集合作用域」这一不变量。
"""

import sys
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from plugin import bm25, supplement, tools

CUSTOM = "log_patterns_collection"


class _Spy:
    """记录 bm25_search / get_bm25_index 收到的 collection 参数。"""

    def __init__(self, hits=None):
        self.searches: list = []
        self.indexes: list = []
        self._hits = hits if hits is not None else []

    def __enter__(self):
        self._s = mock.patch.object(bm25, "bm25_search", side_effect=self._search)
        self._i = mock.patch.object(bm25, "get_bm25_index", side_effect=self._index)
        self._s.start()
        self._i.start()
        return self

    def _search(self, query, top_k=5, collection=None):
        self.searches.append(collection)
        return list(self._hits)

    def _index(self, collection=None):
        self.indexes.append(collection)
        return None  # None → 调用方提前返回，不影响参数断言

    def __exit__(self, *exc):
        self._i.stop()
        self._s.stop()
        return False


def _mock_client(content="这是一段足够长的命中内容用于通过有效性校验"):
    """构造返回单个有效 dense 命中的 mock Qdrant client。"""
    point = MagicMock()
    point.payload = {"content": content, "document_id": "doc-1"}
    point.score = 0.9
    point.id = "d1"
    client = MagicMock()
    client.query_points.return_value.points = [point]
    return client


def _patch_qdrant(client=None):
    """统一 patch：client/model/维度校验（dense 走 mock，不打真 Qdrant）。"""
    client = client or _mock_client()
    return (
        patch.object(supplement, "_get_qdrant_client", return_value=client),
        patch.object(supplement, "_get_embedding_model", return_value=MagicMock()),
        patch.object(supplement, "_validate_qdrant_dimension"),
    )


class TestSearchQdrantCollectionScope(unittest.TestCase):

    def test_bm25_rrf_uses_requested_collection(self):
        """BM25 RRF 支路必须打调用方指定集合（原 L1006 漏传 = 跨集合污染主因）。"""
        p1, p2, p3 = _patch_qdrant()
        with p1, p2, p3, \
             patch.object(supplement, "_precision_guard_fallback", return_value=None), \
             _Spy() as spy:
            supplement.search_qdrant("q", top_k=5, hybrid=True, collection=CUSTOM)
        self.assertEqual(spy.searches, [CUSTOM],
                         f"BM25 RRF 应打 {CUSTOM}，实际 {spy.searches}（None = 主集合）")

    def test_precision_guard_gets_collection(self):
        """precision guard 调用点必须传 collection（否则其内部 exact 索引 + BM25 全打主集合）。"""
        p1, p2, p3 = _patch_qdrant()
        with p1, p2, p3, \
             patch.object(supplement, "_precision_guard_fallback",
                          return_value=None) as guard:
            supplement.search_qdrant("q", top_k=5, hybrid=True, collection=CUSTOM)
        self.assertEqual(guard.call_args.kwargs.get("collection"), CUSTOM)

    def test_default_collection_still_scoped_to_main(self):
        """默认路径（未指定 collection）行为不变：内部一律落主集合。"""
        p1, p2, p3 = _patch_qdrant()
        with p1, p2, p3, \
             patch.object(supplement, "_precision_guard_fallback", return_value=None), \
             _Spy() as spy:
            supplement.search_qdrant("q", top_k=5, hybrid=True)
        self.assertEqual(spy.searches, [supplement.QDRANT_COLLECTION])


class TestChunkLevelCollectionScope(unittest.TestCase):

    def test_chunk_level_bm25_and_guard_use_target_collection(self):
        p1, p2, p3 = _patch_qdrant()
        with p1, p2, p3, \
             patch.object(supplement, "_precision_guard_fallback",
                          return_value=None) as guard, \
             _Spy() as spy:
            supplement._search_chunk_level("q", 5, ["mini"], collection=CUSTOM)
        self.assertEqual(spy.searches, [CUSTOM])
        self.assertEqual(guard.call_args.kwargs.get("collection"), CUSTOM,
                         "chunk_level 的 guard 也必须按集合走")


class TestPrecisionGuardInternals(unittest.TestCase):

    def test_guard_forwards_collection_to_exact_and_bm25(self):
        with _Spy() as spy:
            supplement._precision_guard_fallback(
                "-4002", [{"id": "d", "content": "这段内容里没有精确项但足够长以通过校验",
                          "score": 0.9}],
                top_k=3, collection=CUSTOM)
        self.assertTrue(spy.searches, "guard 应调用 BM25")
        self.assertTrue(all(c == CUSTOM for c in spy.searches),
                        f"guard 的 BM25 必须打 {CUSTOM}，实际 {spy.searches}")
        self.assertTrue(all(c == CUSTOM for c in spy.indexes),
                        f"guard 的精确索引必须按 {CUSTOM} 查，实际 {spy.indexes}")

    def test_search_content_exact_signature_has_collection(self):
        import inspect
        sig = inspect.signature(supplement._search_content_exact)
        self.assertIn("collection", sig.parameters)
        with _Spy() as spy:
            supplement._search_content_exact(["-4002"], top_k=3, collection=CUSTOM)
        self.assertEqual(spy.indexes, [CUSTOM])


class TestGuardEmptyResultKeepsDense(unittest.TestCase):

    def test_empty_guard_does_not_discard_dense(self):
        """精确项全局无匹配时 guard 返回 []——不得因此丢掉正确的 dense 命中。

        （原实现 `if pg_hits is not None: return pg_hits` 会直接返回空列表。）
        """
        p1, p2, p3 = _patch_qdrant()
        with p1, p2, p3, \
             patch.object(supplement, "_precision_guard_fallback", return_value=[]), \
             patch.object(bm25, "bm25_search", return_value=[]):
            hits = supplement.search_qdrant("q -9999", top_k=5, hybrid=True, collection=CUSTOM)
        self.assertTrue(hits, "guard 空结果时不应返回空列表")
        self.assertEqual(hits[0]["id"], "d1")


class TestBatchCollectionSupport(unittest.TestCase):

    def test_batch_passes_batch_level_collection(self):
        with patch.object(tools, "_search_mini_first", return_value=[]) as mini:
            tools._search_qdrant_batch_inner(
                [{"query": "q1", "chunk_mode": "mini_first"}],
                collection=CUSTOM)
        self.assertEqual(mini.call_args.kwargs.get("collection"), CUSTOM,
                         "批量模式必须把批次级 collection 透传到路由")

    def test_batch_per_item_collection_overrides(self):
        with patch.object(tools, "_search_mini_first", return_value=[]) as mini:
            tools._search_qdrant_batch_inner(
                [{"query": "q1", "chunk_mode": "mini_first", "collection": "other_coll"}],
                collection=CUSTOM)
        self.assertEqual(mini.call_args.kwargs.get("collection"), "other_coll")

    def test_batch_handler_forwards_args_collection(self):
        """handler 入口的 collection 要落到批量内部函数（此前完全丢弃）。"""
        with patch.object(tools, "_search_qdrant_batch_inner",
                          return_value='{"results": []}') as inner:
            tools.HANDLERS["search_qdrant"]({"queries": [{"query": "q"}], "collection": CUSTOM})
        self.assertEqual(inner.call_args.kwargs.get("collection"), CUSTOM)


class TestSynthesizeSupplementSearch(unittest.TestCase):

    def test_diagnose_supplement_search_is_collection_scoped(self):
        """synthesize 的「补充检索」（片段不足时触发）必须带 collection。

        这是 diagnose_db_link 跨集合污染的直接来源：registry 各源经 ctx 打对了集合，
        唯独这条补充检索回落主集合。
        """
        fake_dim = {"name": "常见原因", "phase": "qdrant", "snippets": []}
        with patch.object(supplement, "search_qdrant", return_value=[]) as sq, \
             patch.object(supplement, "_resolve_collection", return_value=CUSTOM), \
             patch.object(supplement, "_DIAGNOSIS_REGISTRY") as reg:
            reg.synthesize.return_value = [MagicMock(to_dict=lambda: fake_dim)]
            supplement.synthesize_diagnosis_knowledge(
                symptom="incremental_stuck", db_type="oracle",
                sources=["store:log_patterns_collection#日志模式"])
        self.assertTrue(sq.called, "片段不足应触发补充检索")
        self.assertEqual(sq.call_args.kwargs.get("collection"), CUSTOM,
                         "补充检索必须打 BKN 指引的集合，而非默认主集合")


if __name__ == "__main__":
    unittest.main()
