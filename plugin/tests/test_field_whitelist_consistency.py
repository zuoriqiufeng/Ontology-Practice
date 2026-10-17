"""字段名 ↔ 白名单一致性（22 号批 3-2，不变量 I4）

**为什么需要**：`ContextLoader` 的完整性保护是按 **key 名** 匹配的（`_FULL_CONTENT_KEYS`
+ `_is_protected` 祖先链）。实测教训（`plugin/CLAUDE.md` v3.10 经验 #3）：
同一段文本叫 `raw` 被完整保留、叫 `prerequisites` 就被截到 80——"保护的是 key 名，不是内容"。

因此任何被 `assess_confidence` 当作**必需字段**的 key，若不在白名单里，其长值会被
`_fmt_scalar` 静默截到 80 字符、或被 `_enforce_budget` 第 2 轮整键删除。

本测试强制：`REQUIRED_FIELDS` 的字段名要么受白名单保护，要么**在 KNOWN_UNPROTECTED 里
显式登记**（含风险评估与处置）。新增未登记的必需字段 → 失败。

**反-永久豁免**：`test_registry_is_not_stale` 断言注册表里的 key 尚未被白名单覆盖——
一旦有人补进白名单，注册表条目必须删除，防止豁免变成永久遗留。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from plugin.context_loader import ToonFormatter  # noqa: E402
from plugin.supplement import REQUIRED_FIELDS  # noqa: E402

#: 未受白名单保护、但**暂未修**的必需字段（22 号批 3-2 实测登记）
#: 每个条目：key -> (风险等级, 说明)
#:   风险等级：verified_truncated（已实测会截断，已立候选）/ short_now（当前值短，暂无可见影响）
#: **修好一个就删一条**（test_registry_is_not_stale 会强制）。
KNOWN_UNPROTECTED = {
    # `delegated_to` 曾标 verified_truncated（C-20261010-01）；该候选已 apply 并将其加入
    # `_FULL_CONTENT_KEYS` → 受保护，故按 test_registry_is_not_stale 的要求从此表移除。
    "compatibility": (
        "short_now",
        "dict 容器；其子字段 version_notes 等为值委托（23 号下延），当前无 >80 的实际值。"
        "**容器型字段不宜按 key 逐个豁免**——建议随 C-20261010-01 一并评估",
    ),
    "scenarios": (
        "short_now",
        "list of dict；走 ToonFormatter 的对象数组路径（取公共字段、不走 _fmt_scalar 截断）",
    ),
    "supported": ("short_now", "bool"),
    "error_code": ("short_now", "短标识（如 -4073）"),
    "operation": ("short_now", "短标识（如 start_rule）"),
    "capability": ("short_now", "短标识（如 create_rule）"),
    "scenario": ("short_now", "场景中文名（如 跨平台迁移）"),
    "source": ("short_now", "图节点标识（如 syncrule）"),
    "retrieval_guide": ("short_now", "33 字符常量 store:log_patterns_collection#错误码"),
    # 22 号批 4-2（2026-10-12）：三个豁免 Tool 的必需字段（本次新增判定，随候选 C-20261012-05）
    "hits": ("short_now",
             "list of dict（命中数组）；走 ToonFormatter 对象数组路径、非 _fmt_scalar；"
             "且本字段只用于置信度判定（0 命中 → partial）"),
    "results": ("short_now",
                "list of dict（批量检索结果数组）；同上走对象数组路径"),
    "coverage": ("short_now",
                 "dict（维度覆盖度报告，批 4-2 用作 any-of 判定键）；容器型，"
                 "维度名/计数均为短值"),
    "knowledge_context": (
        "short_now",
        "dict 容器（诊断知识上下文）；子字段 analysis_framework/skill_capabilities 为"
        "Skill 下延内容，当前值受 ToonFormatter 白名单与预算截断约束——"
        "**容器型字段不宜按 key 逐个豁免**（与 compatibility 同注）",
    ),
    "action": ("short_now", "短标识（如 delete_sync_rule/register_db）"),
    "mode": ("short_now", "短标识（single/parallel_batch/report_only/reset）"),
}

#: 精确截断阈值（与 plugin/context_loader.py::_fmt_scalar 一致）
SCALAR_TRUNCATE_AT = 80


def _required_field_names() -> set:
    names = set()
    for spec in REQUIRED_FIELDS.values():
        for item in spec:
            if isinstance(item, tuple):  # any-of 语义（如 query_product 的 (raw, delegated_to)）
                names.update(item)
            else:
                names.add(item)
    return names


class TestFieldWhitelistConsistency(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.required = _required_field_names()
        cls.whitelist = set(ToonFormatter._FULL_CONTENT_KEYS)
        cls.unprotected = {n for n in cls.required if n not in cls.whitelist}

    def test_new_unprotected_required_fields_must_be_registered(self):
        """新增未受保护的必需字段必须先评估截断风险并登记。"""
        new = sorted(self.unprotected - set(KNOWN_UNPROTECTED))
        self.assertEqual(
            new, [],
            f"以下必需字段未受 _FULL_CONTENT_KEYS 保护，也未在 KNOWN_UNPROTECTED 登记：{new}。\n"
            f"处置二选一：① 加入 _FULL_CONTENT_KEYS（走 28 号待审区，属运行时行为变更）；"
            f"② 在 KNOWN_UNPROTECTED 登记风险评估。",
        )

    def test_registry_is_not_stale(self):
        """反-永久豁免：已受保护的字段必须从注册表删除。"""
        stale = sorted(set(KNOWN_UNPROTECTED) & self.whitelist)
        self.assertEqual(
            stale, [],
            f"以下字段已受白名单保护，请从 KNOWN_UNPROTECTED 删除对应条目：{stale}",
        )

    def test_registry_entries_carry_risk_and_reason(self):
        """注册表每个条目必须是 (风险等级, 说明) 且说明非空。"""
        bad = []
        for key, meta in KNOWN_UNPROTECTED.items():
            if not (isinstance(meta, tuple) and len(meta) == 2):
                bad.append(f"{key}: 应为 (风险等级, 说明)")
                continue
            level, reason = meta
            if level not in {"verified_truncated", "short_now"}:
                bad.append(f"{key}: 风险等级非法 {level!r}")
            if not str(reason).strip():
                bad.append(f"{key}: 说明为空")
        self.assertEqual(bad, [], bad)

    def test_verified_truncated_entries_have_a_candidate(self):
        """标为 verified_truncated 的必须有候选 id（防止"记了不改"）。"""
        bad = [
            k for k, (level, reason) in KNOWN_UNPROTECTED.items()
            if level == "verified_truncated" and "C-" not in str(reason)
        ]
        self.assertEqual(bad, [], f"以下字段已实测截断但未指向候选: {bad}")

    def test_whitelist_itself_is_nonempty_and_sane(self):
        """哨兵：白名单与必需字段集合都不应为空（防误改后测试空转）。"""
        self.assertGreater(len(self.whitelist), 10)
        self.assertGreater(len(self.required), 5)
        self.assertEqual(len(self.whitelist), len({k for k in self.whitelist}),
                         "白名单含重复项")


if __name__ == "__main__":
    unittest.main()
