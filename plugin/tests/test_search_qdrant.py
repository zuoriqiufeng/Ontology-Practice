"""Tests for search_qdrant handler: command-field filtering, schema contract,
session isolation, and batch clamp."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from plugin.tools import HANDLERS
from plugin.schemas import SCHEMAS
from plugin.supplement import (
    _track_dimension,
    get_dimension_coverage,
    reset_dimension_coverage,
)


class TestSearchQdrantHandler(unittest.TestCase):

    @patch("plugin.tools.search_qdrant")
    def test_default_path_filters_command_fields(self, mock_search):
        mock_search.return_value = [
            {
                "content": "正常内容",
                "score": 0.9,
                "source": "doc-1",
                "command": "rm -rf /",
                "script": "./run.sh",
            }
        ]
        raw = HANDLERS["search_qdrant"]({
            "query": "Oracle MySQL 字符集",
            "chunk_mode": "auto",
        })
        result = json.loads(raw)
        hits = result.get("hits", [])
        self.assertEqual(len(hits), 1)
        self.assertNotIn("command", hits[0])
        self.assertNotIn("script", hits[0])
        self.assertEqual(hits[0]["content"], "正常内容")

    def test_search_qdrant_collection_passthrough(self):
        """批 6-3：search_qdrant() 的 collection 参数透传到 query_points（诊断方向层）。"""
        from plugin.supplement import search_qdrant
        mock_client = MagicMock()
        mock_points = MagicMock()
        mock_points.points = []
        mock_client.query_points.return_value = mock_points
        with patch("plugin.supplement._get_qdrant_client", return_value=mock_client), \
             patch("plugin.supplement._get_embedding_model", return_value=MagicMock()), \
             patch("plugin.supplement._validate_qdrant_dimension"):
            search_qdrant("测试查询", top_k=3, collection="store:log_patterns_collection")
            _, kwargs = mock_client.query_points.call_args
            self.assertEqual(kwargs.get("collection_name"), "store:log_patterns_collection")

    def test_search_qdrant_collection_default_main(self):
        """批 6-3：collection=None 默认主集合（向后兼容）。"""
        from plugin.supplement import search_qdrant
        from plugin.config import QDRANT_COLLECTION
        mock_client = MagicMock()
        mock_points = MagicMock()
        mock_points.points = []
        mock_client.query_points.return_value = mock_points
        with patch("plugin.supplement._get_qdrant_client", return_value=mock_client), \
             patch("plugin.supplement._get_embedding_model", return_value=MagicMock()), \
             patch("plugin.supplement._validate_qdrant_dimension"):
            search_qdrant("测试查询", top_k=3)
            _, kwargs = mock_client.query_points.call_args
            self.assertEqual(kwargs.get("collection_name"), QDRANT_COLLECTION)

    def test_custom_collection_filters_command_fields(self):
        with patch("plugin.supplement._get_embedding_model") as mock_model_fn, \
             patch("plugin.supplement._get_qdrant_client") as mock_client_fn:
            mock_model = MagicMock()
            mock_model.encode.return_value = MagicMock(tolist=lambda: [0.1] * 1024)
            mock_model_fn.return_value = mock_model

            point = MagicMock()
            point.payload = {
                "content": "自定义集合内容" * 5,
                "document_id": "custom-doc",
                "command": "DROP TABLE test",
            }
            point.score = 0.85
            point.id = "p1"

            mock_client = MagicMock()
            mock_client.query_points.return_value.points = [point]
            mock_client_fn.return_value = mock_client

            raw = HANDLERS["search_qdrant"]({
                "query": "test",
                "collection": "custom_collection",
            })
            result = json.loads(raw)
            hits = result.get("hits", [])
            self.assertEqual(len(hits), 1)
            self.assertNotIn("command", hits[0])
            self.assertEqual(hits[0]["content"], "自定义集合内容" * 5)


class TestSearchQdrantSchema(unittest.TestCase):

    def test_schema_has_queries_param(self):
        schema = next(s for s in SCHEMAS if s["name"] == "search_qdrant")
        props = schema["parameters"]["properties"]
        self.assertIn("queries", props)
        self.assertEqual(props["queries"]["type"], "array")
        self.assertEqual(schema["parameters"]["required"], [])


class TestSessionDimIsolation(unittest.TestCase):

    def tearDown(self):
        reset_dimension_coverage("t1")
        reset_dimension_coverage("t2")

    def test_session_dim_isolation(self):
        _track_dimension("字符集/类型映射", 3, task_id="t1")
        _track_dimension("增量/日志解析", 2, task_id="t2")

        cov1 = get_dimension_coverage("design_solution", task_id="t1")
        cov2 = get_dimension_coverage("design_solution", task_id="t2")

        self.assertIn("字符集/类型映射", cov1["covered_dims"])
        self.assertNotIn("增量/日志解析", cov1["covered_dims"])
        self.assertIn("增量/日志解析", cov2["covered_dims"])
        self.assertNotIn("字符集/类型映射", cov2["covered_dims"])

        reset_dimension_coverage("t1")
        cov1_after = get_dimension_coverage("design_solution", task_id="t1")
        cov2_after = get_dimension_coverage("design_solution", task_id="t2")
        self.assertEqual(cov1_after["covered_count"], 0)
        self.assertEqual(cov2_after["covered_count"], 1)

    def test_report_and_reset_modes(self):
        from plugin import tools
        _track_dimension("字符集/类型映射", 1, task_id="tr")
        out = json.loads(tools.search_qdrant_handler(
            {"dimension": "__report__"}, task_id="tr"))
        self.assertEqual(out["mode"], "report_only")
        self.assertEqual(out["coverage"]["covered_count"], 1)
        out = json.loads(tools.search_qdrant_handler(
            {"dimension": "__reset__"}, task_id="tr"))
        self.assertEqual(out["mode"], "reset")
        out = json.loads(tools.search_qdrant_handler(
            {"dimension": "__report__"}, task_id="tr"))
        self.assertEqual(out["coverage"]["covered_count"], 0)


class TestBatchMode(unittest.TestCase):

    def test_batch_clamp(self):
        from plugin import tools
        queries = [{"query": f"q{i}", "dimension": f"d{i}"} for i in range(15)]
        with mock.patch.object(tools, "search_qdrant", return_value=[]):
            out = json.loads(tools.search_qdrant_handler({"queries": queries}))
        self.assertEqual(out["query_count"], 10)
        self.assertTrue(out.get("truncated"))
        self.assertEqual(out["mode"], "parallel_batch")

    def test_batch_mode_routing(self):
        from plugin import tools
        with mock.patch.object(tools, "search_qdrant", return_value=[]) as m:
            out_batch = json.loads(tools.search_qdrant_handler(
                {"queries": [{"query": "x", "dimension": "d1", "chunk_mode": "auto"}]}
            ))
            self.assertEqual(out_batch["mode"], "parallel_batch")
            out_single = json.loads(tools.search_qdrant_handler(
                {"query": "y", "dimension": "d2", "chunk_mode": "auto"}
            ))
            self.assertNotEqual(out_single.get("mode"), "parallel_batch")
            self.assertIn("hits", out_single)
        self.assertTrue(m.called)


if __name__ == "__main__":
    unittest.main()
