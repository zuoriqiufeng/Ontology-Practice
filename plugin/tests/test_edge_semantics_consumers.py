"""lint 第 36 项「声明的键必须有消费者」的**反向注入负例**（74 号批 S-4・R-A，C-20261015-04）。

纪律（`11 号规则 9`）：**新增机检必须同批带负例**——「零违规通过」无法区分
「检查有效」与「检查没接上」（对照驱动 G-22）。

本件三组断言：
1. **存量零违规**：对真实 `plugin/edge_semantics.yaml` 跑机检，断言不报「无消费者」；
2. **反向注入（顶层键）**：注入一个凭空捏造的键 `phantom_axiom` ⇒ 机检**必然报 error 并指名它**；
3. **反向注入（walk_policy 字段）**：给 `walk_policy` 注入 `phantom_field` ⇒ 同样被检出。

第 1 组证明「检查没接上时会红」（存量真值），第 2/3 组证明「注入违规会红」（检查有效）——
两者合起来才是负例纪律要的闭环。

依据: 74 号 §4.1#5 / §5 批 S-4；11 号规则 17；plugin/edge_semantics.yaml。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "plugin" / "scripts"))

import lint_bkn  # noqa: E402
from plugin.relations import RelationTraverser  # noqa: E402


class TestEdgeSemanticsConsumers(unittest.TestCase):
    """声明 → 消费：无消费者的声明必须在门禁① 被拦下。"""

    def _errors(self):
        linter = lint_bkn.Linter(ROOT / "bkn")
        linter._check_edge_semantics_consumers()
        return [e for e in linter.errors if "edge_semantics" in e]

    def test_repo_has_no_declaration_without_consumer(self):
        """存量真值：当前 11 个可声明键全部有消费者（本项当前应零命中）。"""
        self.assertEqual(self._errors(), [])

    def test_phantom_top_level_key_is_caught(self):
        real = RelationTraverser.edge_semantics()
        injected = dict(real)
        injected["phantom_axiom"] = ["nobody_reads_me"]
        RelationTraverser._SEMANTICS = injected
        try:
            errs = self._errors()
        finally:
            RelationTraverser._SEMANTICS = real
        self.assertTrue(
            any("phantom_axiom" in e for e in errs),
            f"注入的顶层键未被检出（负例失效）：{errs}")

    def test_phantom_walk_policy_field_is_caught(self):
        real = RelationTraverser.edge_semantics()
        injected = dict(real)
        walk = dict(real.get("walk_policy") or {})
        walk["phantom_field"] = 1
        injected["walk_policy"] = walk
        RelationTraverser._SEMANTICS = injected
        try:
            errs = self._errors()
        finally:
            RelationTraverser._SEMANTICS = real
        self.assertTrue(
            any("walk_policy.phantom_field" in e for e in errs),
            f"注入的 walk_policy 字段未被检出（负例失效）：{errs}")


if __name__ == "__main__":
    unittest.main()
