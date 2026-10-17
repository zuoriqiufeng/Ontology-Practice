"""Tests for 21 号 2C: schema enum 与机器可读常量的一致性（防「改一处漏一处」）。

背景：2C 之前存在 6 处双登记，其中 relation_type enum（26 值）与 RELATION_TYPES（24 值）
已实际脱节（connects_to 入图却不可查）。本文件把「schema ↔ 常量」的一致性锁进测试。
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from plugin.schemas import SCHEMAS
from plugin.relations import RelationTraverser
from plugin.constants import SCENARIO_HINTS, SYMPTOM_ALIASES


def _schema(name: str) -> dict:
    return next(s for s in SCHEMAS if s["name"] == name)


# resolve_relation 的三个虚拟出口：语义出口而非图边类型，不在 RELATION_TYPES
#: **虚拟出口**：不是关系类型，而是求值/诊断的专用出口——
#: diagnosis_path（O-域单跳）· process_chain（进程链）· closure（边语义闭包，C-20261013-04 接线）·
#: **impact（影响面，68 号 E-1）** · all（全量分组）。
#: `impact` 与 `closure` 同类：它**不新增边**，而是把本体已声明的 5 条承载边
#: （feeds/reads_from/runs_on/registered_on/supervises，见 fault_mechanism.necessary_criteria 第 2 条）
#: 预设成一次双向展开。**新增任何虚拟出口都必须登记在这里**——本守卫就是为此而设（68 号 E-1 实测被它拦下）。
_VIRTUAL_RELATION_TYPES = {"diagnosis_path", "process_chain", "closure", "impact", "all"}


class TestRelationTypeConsistency(unittest.TestCase):

    def setUp(self):
        enum = _schema("resolve_relation")["parameters"]["properties"]["relation_type"]["enum"]
        self.enum = set(enum)
        self.relation_types = set(RelationTraverser.RELATION_TYPES)

    def test_enum_matches_relation_types(self):
        """schema enum \ 虚拟出口 == RELATION_TYPES（双向，缺一边即失败）。"""
        self.assertEqual(self.enum - _VIRTUAL_RELATION_TYPES, self.relation_types,
                         "schema enum 与 RelationTraverser.RELATION_TYPES 脱节"
                         "（21 号 2C 前 connects_to 即因此入图不可查）")

    def test_virtual_exits_present(self):
        """五个虚拟出口必须在 enum 里（含 68 号 E-1 的 impact）。"""
        self.assertTrue(_VIRTUAL_RELATION_TYPES <= self.enum)


class TestScenarioHintConsistency(unittest.TestCase):

    def test_enum_is_scenario_hints(self):
        """design_solution 的 scenario_hint enum 从 constants.SCENARIO_HINTS 派生。"""
        enum = _schema("design_solution")["parameters"]["properties"]["scenario_hint"]["enum"]
        self.assertEqual(list(enum), list(SCENARIO_HINTS))

    def test_hint_names_match_routing_rules(self):
        """hint 的中文场景名必须能对上 resolver 路由规则的场景名（auto 除外）。"""
        from plugin.resolver import _SCENARIO_ROUTING_RULES
        rule_scenarios = {r["scenario"] for r in _SCENARIO_ROUTING_RULES}
        for hint, name in SCENARIO_HINTS.items():
            if name:  # auto 的空串表示自动匹配，无固定场景名
                self.assertIn(name, rule_scenarios,
                              f"SCENARIO_HINTS['{hint}']='{name}' 在 _SCENARIO_ROUTING_RULES 无对应场景")


class TestSymptomDescriptionConsistency(unittest.TestCase):

    def test_symptom_ids_covered(self):
        """diagnose_db_link 的 symptom 描述覆盖 SYMPTOM_ALIASES 全部规范 ID。"""
        desc = _schema("diagnose_db_link")["parameters"]["properties"]["symptom"]["description"]
        canonical = set(SYMPTOM_ALIASES.values())
        for sid in canonical:
            self.assertIn(sid, desc,
                          f"规范症状 ID '{sid}' 未出现在 schema 描述（21 号 2C 前即滞后：5/9）")


if __name__ == "__main__":
    unittest.main()
