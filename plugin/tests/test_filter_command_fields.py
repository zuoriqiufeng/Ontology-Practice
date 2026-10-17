"""Tests for _filter_command_fields safety net."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from plugin.tools import _filter_command_fields


class TestFilterCommandFields(unittest.TestCase):

    def test_removes_dangerous_keys(self):
        data = {
            "command": "rm -rf /",
            "script": "./run.sh",
            "cmd": "ls",
            "检查命令": "show tables",
            "执行命令": "./dumpredo",
            "执行步骤": "1) start; 2) stop",
            "safe_field": "keep me",
        }
        result = _filter_command_fields(data)
        self.assertNotIn("command", result)
        self.assertNotIn("script", result)
        self.assertNotIn("cmd", result)
        self.assertNotIn("检查命令", result)
        self.assertNotIn("执行命令", result)
        self.assertNotIn("执行步骤", result)
        self.assertIn("safe_field", result)
        self.assertEqual(result["safe_field"], "keep me")

    def test_preserves_legitimate_keys_containing_substrings(self):
        data = {
            "replication_script_status": "ok",
            "cmdline_options": "--verbose",
            "command_summary_note": "not a command",
            "description": "contains the word command inside",
        }
        result = _filter_command_fields(data)
        self.assertIn("replication_script_status", result)
        self.assertIn("cmdline_options", result)
        self.assertIn("command_summary_note", result)
        self.assertIn("description", result)

    def test_filters_nested_structures(self):
        data = {
            "level1": {
                "command": "nested command",
                "list": [
                    {"script": "nested script"},
                    {"safe": "keep"},
                ],
            },
        }
        result = _filter_command_fields(data)
        self.assertNotIn("command", result["level1"])
        self.assertNotIn("script", result["level1"]["list"][0])
        self.assertIn("safe", result["level1"]["list"][1])


if __name__ == "__main__":
    unittest.main()
