"""Tests for v3.6 chunk-aware fields surviving ContextLoader processing.

P0-3: 验证 hit_mini/_parent/chunk_id 等新字段在 trim/toon 路径不被误裁或截断。
search_qdrant handler 绕过 ContextLoader，但 enrichment 注入走 _wrap() 的 Tool 会经过。
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from plugin.context_loader import ContextLoader, TrimFilter, ToonFormatter


def _chunk_result():
    """构造含 v3.6 chunk 字段的 Tool 返回结构"""
    return {
        "data": "ok",
        "enrichment": {
            "source": "qdrant",
            "hits": [
                {
                    "content": "标准块内容 " * 30,
                    "score": 0.91,
                    "source": "doc-1",
                    "chunk_id": "std-001",
                    "chunk_level": "standard",
                    "section_type": "text",
                    "large_chunk_id": "lc-001",
                    "title": "标题",
                    "hit_mini": [
                        {"index": 0, "text": "mini 子块文本 " * 20, "offset": [0, 120]},
                    ],
                    "_parent": {
                        "large_chunk_id": "lc-001",
                        "title": "大块标题",
                        "doc_summary": "",
                    },
                }
            ],
        },
    }


class TestTrimFilterChunkFields(unittest.TestCase):

    def setUp(self):
        self.f = TrimFilter()

    def test_chunk_id_not_trimmed(self):
        """chunk_id/large_chunk_id 不得被 TECHNICAL_PATTERNS 误裁"""
        data = {"chunk_id": "c1", "large_chunk_id": "lc1", "chunk_level": "mini"}
        out = self.f.trim(data)
        self.assertEqual(out["chunk_id"], "c1")
        self.assertEqual(out["large_chunk_id"], "lc1")
        self.assertEqual(out["chunk_level"], "mini")

    def test_hit_mini_and_parent_survive_trim(self):
        out = self.f.trim(_chunk_result())
        hit = out["enrichment"]["hits"][0]
        self.assertIn("hit_mini", hit)
        self.assertIn("_parent", hit)
        self.assertEqual(hit["hit_mini"][0]["index"], 0)
        self.assertEqual(hit["_parent"]["title"], "大块标题")

    def test_empty_parent_fields_dropped_but_structure_kept(self):
        """空字符串/None 字段会被裁剪——记录此行为，确认可接受"""
        out = self.f.trim({"_parent": {"large_chunk_id": "x", "title": "", "doc_summary": ""}})
        self.assertIn("_parent", out)
        self.assertNotIn("title", out["_parent"])  # 空值被裁，属预期


class TestToonFormatterChunkFields(unittest.TestCase):

    def setUp(self):
        self.t = ToonFormatter()

    def test_hit_mini_text_in_object_array_not_truncated(self):
        """对象数组经 _fmt_object_array 用 str() 直接输出，不经 _fmt_scalar，长文本不截断。

        注意: dict 标量值才走 _fmt_scalar 截断逻辑 (>80 字符且不在 _FULL_CONTENT_KEYS)。
        """
        hit = {"hit_mini": [{"index": 0, "text": "长文本" * 50, "offset": [0, 150]}]}
        out = self.t.format(hit, key="root")
        self.assertNotIn("...", out)
        self.assertIn("长文本" * 50, out)

    def test_dict_scalar_over_80_chars_truncated_unless_whitelisted(self):
        """dict 标量值 >80 字符且 key 不在白名单 → 截断；在白名单 → 保留"""
        out = self.t.format({"blurb": "短摘要" * 40}, key="root")  # blurb 不在白名单
        self.assertIn("...", out)

    def test_content_field_not_truncated(self):
        """content 在 _FULL_CONTENT_KEYS 白名单中，长文本完整保留"""
        hit = {"content": "内容" * 100}
        out = self.t.format(hit, key="root")
        self.assertNotIn("...", out)
        self.assertIn("内容" * 100, out)


class TestContextLoaderStrategies(unittest.TestCase):

    def setUp(self):
        self.loader = ContextLoader()

    def test_full_mode_keeps_chunk_fields(self):
        """full 模式 (trim+toon) 后 chunk 字段结构保留。

        回归: _fmt_dict 紧凑分支曾静默丢弃 dict/list 值（如 enrichment），
        本测试同时覆盖该修复。
        """
        out = self.loader.process(_chunk_result(), mode="full")
        self.assertIn("hit_mini", out)
        self.assertIn("enrichment", out)
        self.assertIn("chunk_level", out)
        self.assertIn("large_chunk_id", out)

    def test_trim_only_mode_keeps_chunk_fields(self):
        out = self.loader.process(_chunk_result(), mode="trim_only")
        self.assertIn("hit_mini", out)
        self.assertIn("_parent", out)

    def test_raw_mode_json_intact(self):
        out = self.loader.process(_chunk_result(), mode="raw")
        parsed = json.loads(out)
        hit = parsed["enrichment"]["hits"][0]
        self.assertEqual(hit["chunk_id"], "std-001")
        self.assertEqual(hit["hit_mini"][0]["offset"], [0, 120])


if __name__ == "__main__":
    unittest.main()
