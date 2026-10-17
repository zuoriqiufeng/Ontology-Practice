"""Tests for YAML frontmatter compatibility in BKNResolver.

P0-6: objects/*.bkn 将引入 frontmatter，必须先验证 resolver 解析不受影响：
- frontmatter 内容落入 `_head` section
- 不影响现有 section/table/kv 提取
- 不影响 `_register_actions`（frontmatter 不应被误注册为 Action）
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from plugin.resolver import BKNResolver


SAMPLE_WITH_FRONTMATTER = """---
name: 同步规则
id: syncrule
description: Demo Product的核心业务对象
aliases:
  - 规则
  - rule
source_doc:
  - docs/使用指引.docx
---

# Object: SyncRule (同步规则)

> BKN 本体: 业务对象

## 定义

同步规则是配置单元。

## 关键属性

| 属性名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| rule_uuid | string | 是 | 规则唯一标识 |
| status | enum | 是 | 规则状态 |

## Action: 创建同步规则

- capability: create_sync_rule
- object: syncrule
- implements: skill:demo_product-rule-manager
"""

SAMPLE_WITHOUT_FRONTMATTER = """# Object: SyncRule (同步规则)

## 定义

同步规则是配置单元。

## 关键属性

| 属性名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| rule_uuid | string | 是 | 规则唯一标识 |
"""


class TestFrontmatterCompatibility(unittest.TestCase):

    def _make_resolver(self, content: str) -> BKNResolver:
        tmp = tempfile.mkdtemp()
        Path(tmp, "test_obj.bkn").write_text(content, encoding="utf-8")
        return BKNResolver(bkn_root=tmp)

    def test_frontmatter_lands_in_head_section(self):
        r = self._make_resolver(SAMPLE_WITH_FRONTMATTER)
        data = r.cache["test_obj.bkn"]
        self.assertIn("_head", data)
        self.assertIn("name: 同步规则", data["_head"]["raw"])
        self.assertIn("aliases:", data["_head"]["raw"])

    def test_sections_parsed_normally_with_frontmatter(self):
        r = self._make_resolver(SAMPLE_WITH_FRONTMATTER)
        data = r.cache["test_obj.bkn"]
        # 正常 section 不受 frontmatter 影响
        self.assertIn("定义", data)
        self.assertIn("关键属性", data)
        self.assertIn("同步规则是配置单元", data["定义"]["raw"])

    def test_tables_extracted_with_frontmatter(self):
        r = self._make_resolver(SAMPLE_WITH_FRONTMATTER)
        data = r.cache["test_obj.bkn"]
        tables = data["关键属性"]["tables"]
        self.assertEqual(len(tables), 1)
        self.assertEqual(tables[0]["header"], ["属性名", "类型", "必填", "说明"])
        self.assertEqual(len(tables[0]["rows"]), 2)

    def test_frontmatter_yaml_lands_in_head_kv_harmlessly(self):
        """frontmatter 的 key: value 行会进入 _head.kv（kv 提取不要求加粗格式）。

        这是无害且有用的行为：_head section 不被任何 Tool 直接消费，
        aliases 等元数据反而可经 _head.kv/raw 被 resolver 读取（P0-6 利用此点）。
        关键是不影响其他 section 的解析与 Action 注册。
        """
        r = self._make_resolver(SAMPLE_WITH_FRONTMATTER)
        data = r.cache["test_obj.bkn"]
        head_kv = data["_head"]["kv"]
        self.assertEqual(head_kv.get("name"), "同步规则")
        self.assertEqual(head_kv.get("id"), "syncrule")
        # 其他 section 的 kv 不受 frontmatter 污染
        action_kv = data["Action: 创建同步规则"]["kv"]
        self.assertEqual(action_kv.get("capability"), "create_sync_rule")

    def test_action_registration_unaffected(self):
        """frontmatter 存在时 Action 段仍正常注册"""
        r = self._make_resolver(SAMPLE_WITH_FRONTMATTER)
        self.assertIn("create_sync_rule", r._operations)

    def test_frontmatter_not_misregistered_as_action(self):
        """frontmatter 中的 name/id 字段不得被误注册为 Action"""
        r = self._make_resolver(SAMPLE_WITH_FRONTMATTER)
        # _head 中没有 capability，不应产生任何以 frontmatter 字段命名的 operation
        for cap in r._operations:
            self.assertNotIn("aliases", cap)
            self.assertNotIn("source_doc", cap)

    def test_no_frontmatter_still_works(self):
        """无 frontmatter 的文件行为不变（回归）"""
        r = self._make_resolver(SAMPLE_WITHOUT_FRONTMATTER)
        data = r.cache["test_obj.bkn"]
        self.assertIn("定义", data)
        self.assertEqual(len(data["关键属性"]["tables"]), 1)


if __name__ == "__main__":
    unittest.main()
