"""Tests for 21 号 2F/2G: bm25_search 回传载荷元数据 + content_cache/exact_index 全量化。

2F 修复前 `bm25_search` 只回传 `{id, bm25_score, content}`，导致：
- mini_first Phase1 无法按 chunk_level 分类（BM25 条目全被判成 other_hits）；
- 去重键 (source, chunk_id) 因 source 为空 + chunk_id 缺失而塌缩，静默丢结果；
- Phase4 只能交付 BM25 原始块（可能是 mini/image 原文），违背「只交付父 standard 块」。

2G 修复前 `_build_index` 的 content_cache/exact_index 基于**截断 1000** 的文本，
42 个文档的尾部错误码对精确匹配完全不可见（audit 2026-07-03 登记的 Low 项）。
"""

import sys
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from plugin import bm25


def _point(pid, payload):
    p = MagicMock()
    p.id = pid
    p.payload = payload
    return p


class TestBm25MetaCache(unittest.TestCase):

    def test_build_index_collects_meta(self):
        payload = {
            "content": "ORA-00942 表或视图不存在" * 3,
            "document_id": "doc-1", "chunk_id": 77, "chunk_level": "standard",
            "title": "错误码手册", "large_chunk_id": "lc-1", "section_type": "text",
            "blurb": "摘要", "parent_chunk_id": None, "parent_document_id": None,
            "pattern_id": "LP-0001", "severity": "high", "error_codes": ["-4074"],
        }
        client = MagicMock()
        client.scroll.side_effect = lambda **kw: ([_point("p1", payload)], None)
        idx = bm25._build_index(client, "coll")
        self.assertIsNotNone(idx)
        meta = idx._meta_cache["p1"]
        self.assertEqual(meta["chunk_level"], "standard")
        self.assertEqual(meta["chunk_id"], 77)
        self.assertEqual(meta["document_id"], "doc-1")
        self.assertEqual(meta["title"], "错误码手册")
        self.assertEqual(meta["pattern_id"], "LP-0001")
        self.assertEqual(meta["severity"], "high")
        # 值为 None 的字段不写入（保持 dict 紧凑）
        self.assertNotIn("parent_chunk_id", meta)

    def test_bm25_search_returns_meta_and_source(self):
        payload = {
            "content": "ORA-00942 表或视图不存在 " * 3,
            "document_id": "doc-1", "chunk_id": 77, "chunk_level": "mini",
            "title": "T", "parent_chunk_id": 900, "parent_document_id": "doc-1",
        }
        client = MagicMock()
        client.scroll.side_effect = lambda **kw: ([_point("p1", payload)], None)
        index = bm25._build_index(client, "coll")
        with mock.patch.object(bm25, "get_bm25_index", return_value=index):
            hits = bm25.bm25_search("ORA-00942", top_k=5, collection="coll")

        self.assertTrue(hits, "应命中文档")
        h = hits[0]
        # 关键：元数据随命中回传
        self.assertEqual(h["chunk_level"], "mini")
        self.assertEqual(h["chunk_id"], 77)
        self.assertEqual(h["parent_chunk_id"], 900)
        self.assertEqual(h["parent_document_id"], "doc-1")
        self.assertEqual(h["source"], "doc-1")  # source = document_id（不再是空串）
        self.assertIn("bm25_score", h)
        self.assertIn("content", h)

    def test_search_content_exact_returns_meta(self):
        """精确项路径同源回传元数据（此前 source 恒为 '[content_exact_match]' 字符串）。"""
        from plugin import supplement
        payload = {
            "content": "ORA-00942 表或视图不存在 " * 3,
            "document_id": "doc-9", "chunk_id": 5, "chunk_level": "standard",
        }
        client = MagicMock()
        client.scroll.side_effect = lambda **kw: ([_point("p9", payload)], None)
        with mock.patch.object(bm25, "get_bm25_index",
                               return_value=bm25._build_index(client, "coll")):
            hits = supplement._search_content_exact(["ORA-00942"], top_k=5, collection="coll")
        self.assertTrue(hits)
        h = hits[0]
        self.assertEqual(h["source"], "doc-9")
        self.assertEqual(h["chunk_level"], "standard")
        self.assertTrue(h.get("_exact_match"))


if __name__ == "__main__":
    unittest.main()


class TestFullContentCache(unittest.TestCase):
    """21 号 2G：content_cache / exact_index 全量化（索引文本仍截断 1000）。"""

    def test_content_cache_stores_full_content(self):
        """尾部错误码文档的 content_cache 必须是全量（修复前被 [:1000] 截掉）。"""
        long_head = "正文开头 " * 300            # ≈1200 字符，越过 1000 截断线
        tail_code = "尾部错误码 -4074 说明"
        payload = {"content": long_head + tail_code,
                   "document_id": "doc-tail", "chunk_id": 1, "chunk_level": "standard"}
        client = MagicMock()
        client.scroll.side_effect = lambda **kw: ([_point("p1", payload)], None)
        idx = bm25._build_index(client, "coll")
        self.assertGreater(len(idx._content_cache["p1"]), 1200,
                           "content_cache 应存全量 content")
        self.assertIn("-4074", idx._content_cache["p1"])

    def test_tail_error_code_reachable_via_exact(self):
        """截断缺口回归锁：错误码只出现在 1000 字符之后也必须能被精确匹配。"""
        long_head = "正文开头 " * 300
        payload = {"content": long_head + "尾部错误码 -4074 说明",
                   "document_id": "doc-tail", "chunk_id": 1, "chunk_level": "standard"}
        client = MagicMock()
        client.scroll.side_effect = lambda **kw: ([_point("p1", payload)], None)
        from plugin import supplement
        with mock.patch.object(bm25, "get_bm25_index",
                               return_value=bm25._build_index(client, "coll")):
            hits = supplement._search_content_exact(["-4074"], top_k=5, collection="coll")
        self.assertTrue(hits, "尾部错误码必须可被 exact 匹配（修复前 42 个文档不可达）")
        self.assertEqual(hits[0]["source"], "doc-tail")

    def test_index_text_still_truncated(self):
        """送 tokenize 的索引文本保持截断 1000（构建耗时的既定取舍，见 21 号 §8.8）。"""
        long_head = "正文开头 " * 300
        payload = {"content": long_head + "尾部 -4074",
                   "document_id": "doc-t", "chunk_id": 1, "chunk_level": "standard"}
        client = MagicMock()
        client.scroll.side_effect = lambda **kw: ([_point("p1", payload)], None)
        idx = bm25._build_index(client, "coll")
        # doc_lengths 反映的是索引文本（截断后）的 token 量，不应等于全量 token 量
        self.assertLess(idx.doc_lengths[0],
                        len(bm25.BM25Scorer.tokenize(long_head + "尾部 -4074")))
