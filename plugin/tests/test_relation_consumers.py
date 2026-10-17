"""关系类型 × 消费者矩阵一致性（22 号批 3-1，不变量 I3）

强制两件事：
1. `plugin/relation_consumers.yaml` 的键集与 `RelationTraverser.RELATION_TYPES` **完全相等**
   —— 双向：不漏登记（新边必须有消费者交代），也不许幽灵键（删边后矩阵要跟着删）。
2. `python_consumers` 为空的类型必须写 `no_python_consumer_note`
   —— 对位 26 号 `uses_tool` 的处置先例：无消费者要么移除，要么显式说明为何保留。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from plugin.relations import RelationTraverser  # noqa: E402

MATRIX_PATH = ROOT / "plugin" / "relation_consumers.yaml"


class TestRelationConsumers(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.matrix = yaml.safe_load(MATRIX_PATH.read_text(encoding="utf-8"))
        cls.types = cls.matrix.get("types") or {}
        cls.declared = set(cls.types)
        cls.whitelist = set(RelationTraverser.RELATION_TYPES)

    def test_matrix_covers_every_relation_type(self):
        """不漏登记：白名单里每种类型都必须在矩阵中出现。"""
        missing = sorted(self.whitelist - self.declared)
        self.assertEqual(missing, [], f"以下关系类型未在消费者矩阵中登记: {missing}")

    def test_matrix_has_no_ghost_keys(self):
        """不许幽灵键：矩阵里的键必须是白名单成员。"""
        ghosts = sorted(self.declared - self.whitelist)
        self.assertEqual(ghosts, [], f"消费者矩阵含非白名单的幽灵键: {ghosts}")

    def test_agent_only_types_carry_a_note(self):
        """无 Python 消费者的类型必须写明保留理由（不得静默留下）。"""
        offenders = [
            t for t, spec in sorted(self.types.items())
            if not (spec or {}).get("python_consumers")
            and not str((spec or {}).get("no_python_consumer_note", "")).strip()
        ]
        self.assertEqual(offenders, [],
                         f"以下类型无 Python 消费者却未写 no_python_consumer_note: {offenders}")

    def test_class_field_matches_consumer_presence(self):
        """`class` 标注与 `python_consumers` 是否为空必须一致。"""
        offenders = []
        for t, spec in sorted(self.types.items()):
            spec = spec or {}
            has = bool(spec.get("python_consumers"))
            declared = spec.get("class")
            if has and declared != "python":
                offenders.append(f"{t}: 有消费者但 class={declared!r}")
            if not has and declared != "agent_only":
                offenders.append(f"{t}: 无消费者但 class={declared!r}")
        self.assertEqual(offenders, [], offenders)

    def test_declared_consumers_point_at_real_files(self):
        """消费者条目里的文件路径必须存在（防止改了文件名后矩阵静默失准）。"""
        bad = []
        for t, spec in sorted(self.types.items()):
            for entry in (spec or {}).get("python_consumers") or []:
                rel = str(entry).split(" ")[0].split("—")[0].strip()
                if ":" in rel:
                    rel = rel.split(":")[0]
                if rel and not (ROOT / rel).exists():
                    bad.append(f"{t}: {rel}")
        self.assertEqual(bad, [], f"矩阵引用了不存在的文件: {bad}")

    def test_at_least_one_python_consumed_type(self):
        """哨兵：断言矩阵不是空壳（防止误删内容后测试仍然"通过"）。"""
        python_types = [t for t, s in self.types.items()
                        if (s or {}).get("python_consumers")]
        self.assertGreaterEqual(len(python_types), 5,
                                f"Python 消费类类型过少（{len(python_types)}），矩阵可能被误改")


if __name__ == "__main__":
    unittest.main()
