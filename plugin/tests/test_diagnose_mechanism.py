"""diagnose_mechanism 出口（54 号 · 裁 2＝C）的机检。

四条硬约束：
1. **契约形状**：§4.5 的五段 ＋ `silence_note` 齐备；
2. **承重（A 类）**：改 `mechanisms.yaml` 的判据 ⇒ 输出**必须变**（证明它真读判据侧车，不是装饰）；
3. **Q27 守卫**：只给码、无观测时**不得** `confirmed`，且必须给出「需要消息文本」的缺口；
4. **hard_cap 守卫**：只有**一条软证据**命中 ⇒ 状态**必须**是 `unknown`（不许 confirmed）。

另有 1 条**对照**：两条**独立来源的 hard** 命中时，`confirmed` 必须**可达**（否则规则退化成恒 unknown，与「从来不确认」无法区分）。

C-20261013-15 补五条守卫（四个实现层缺口）：只提**字段名**不得 confirmed（weak 不计 hard）／
根类**不独立出证**故不得进 candidates／structural 判据接 L2 可达性且**只作证据**／
判据显式给 counter_patterns 时须产出 excluded／来源归属须用通配匹配。

依据: doc/optimize/54-m4-output-contract.md · 29 号 §4.4/§4.5 · Q27
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from plugin import tools as T  # noqa: E402

MECH = ROOT / "plugin" / "mechanisms.yaml"
SEGS = ("candidates", "chain_note", "next_actions", "evidence_gaps",
        "fact_vs_inference", "silence_note")


class _InjectMech:
    """临时换掉 mechanisms.yaml 的语义（含清 module 级缓存），退出即还原。"""

    def __init__(self, mutate):
        self.mutate = mutate

    def __enter__(self):
        self.saved = T._MECH_CACHE
        sem = yaml.safe_load(MECH.read_text(encoding="utf-8")) or {}
        self.mutate(sem)
        T._MECH_CACHE = sem
        return self

    def __exit__(self, *a):
        T._MECH_CACHE = self.saved
        return False


class TestDiagnoseMechanism(unittest.TestCase):

    OBS_SOFT = "[案例A] SvcManager service [track:1033] online, but process not found"

    def setUp(self):
        T._init()

    def out(self, args):
        r = T.diagnose_mechanism(args)
        return r if isinstance(r, str) else str(r)

    def test_contract_shape(self):
        """§4.5 的五段 ＋ 沉默端必须齐备。"""
        out = self.out({"entry": "incremental_stuck"})
        for seg in SEGS:
            self.assertIn(seg, out, "缺输出段：" + seg)

    def test_criteria_are_load_bearing(self):
        """A 类承重：改掉 patterns ⇒ 输出必须变、命中必须消失。"""
        args = {"entry": "dimension:state_machine", "observations": [self.OBS_SOFT]}
        before = self.out(args)
        self.assertIn("online, but process not found", before,
                      "基线应命中控制面/数据面分裂的日志模式")

        def drop(sem):
            for m in sem.get("mechanisms") or []:
                for c in m.get("criterion") or []:
                    if c.get("patterns"):
                        c["patterns"] = ["故意改掉的模式"]

        with _InjectMech(drop):
            after = self.out(args)
        self.assertNotEqual(before, after,
                            "改掉 patterns 后输出未变 ⇒ 出口没在读判据（装饰）")
        self.assertNotIn("判据命中原文", after, "改掉 patterns 后不应再有命中")

    def test_q27_code_only_never_confirms(self):
        """只给码（无消息文本）⇒ 不得 confirmed，且须给出「需要消息文本」。"""
        out = self.out({"entry": "-4073"})
        self.assertNotIn("→ confirmed", out, "只给码、无观测时不得 confirmed")
        self.assertIn("消息文本", out, "应给出「需要日志消息文本」的证据缺口")

    def test_soft_only_stays_unknown(self):
        """只有一条软证据命中 ⇒ 按 hard_cap 只能 unknown（**且确实命中了**，不是没匹上）。"""
        out = self.out({"entry": "dimension:state_machine", "observations": [self.OBS_SOFT]})
        self.assertNotIn("→ confirmed", out, "纯软证据不得 confirmed（hard_cap）")
        self.assertIn("→ unknown", out)
        self.assertIn("判据命中原文", out, "本用例要求**确实命中**（否则退化成空跑）")
        self.assertIn("软证据", out, "应给出 hard_cap 的理由")

    def test_pattern_placeholder_is_wildcard(self):
        """判据里的 <pid> / <uuid> 占位必须能匹配**真实日志行**（否则判据是装饰）。"""
        obs = "[案例A] SvcManager service [track:1042] online, but process not found"
        out = self.out({"entry": "dimension:state_machine", "observations": [obs]})
        self.assertIn("判据命中原文", out, "含 <pid> 占位的模式应能匹配真实日志行")
        self.assertNotIn("本次无命中", out)

    def test_two_independent_hard_sources_can_confirm(self):
        """对照：两条**独立来源**的 hard 命中时 confirmed 必须可达。

        （C-20261013-15 起改走**真实日志文本**的 hard 判据：原用例靠 field_condition 的
        **字段名出现**取 hard，而那正是被修掉的假阳性——见 test_field_name_only_never_confirms。）
        """
        obs = ["[机器A] fullsync point 与交接点不一致",
               "[机器B] query binlog spot 指向旧变更"]
        out = self.out({"entry": "dimension:log_readable", "observations": obs})
        self.assertIn("→ confirmed", out, "两条独立 hard 命中时应可达 confirmed")

    def test_field_name_only_never_confirms(self):
        """C-20261013-15 守卫：只提**字段名**、不给值 ⇒ 不得 confirmed（weak 不计 hard）。

        修前实测：两条观测各提一句 state_time / last_op / delay（**不给任何值**）即判 confirmed
        ——condition 未求值却按声明的 evidence_strength=hard 计入。
        """
        obs = ["[源A] state_time / last_op / delay 这三个字段我都看过了",
               "[源B] 同一台机器再看一遍 state_time last_op delay"]
        out = self.out({"entry": "incremental_stuck", "observations": obs})
        self.assertNotIn("→ confirmed", out, "字段名出现不是 hard 证据，不得 confirmed")
        self.assertIn("weak", out, "弱命中应如实标注 weak=True")

    def test_root_class_never_in_candidates(self):
        """C-20261013-15 守卫：根类（声明「不独立出证」）不得作为候选出现。"""
        out = self.out({"entry": "-4073"})
        self.assertNotIn("fault_mechanism,unknown", out, "根类不得进 candidates")
        self.assertIn("不独立出证", out, "应说明根类为何缺席")

    def test_structural_evidence_is_reported(self):
        """C-20261013-15：根类的 structural 判据须接 L2 可达性，且**只作证据**。"""
        out = self.out({"entry": "process:iatrack"})
        self.assertIn("structural_evidence", out, "结构式判据应报出本体侧可达性证据")
        self.assertIn("path_exists", out)
        self.assertNotIn("fault_mechanism,unknown", out, "structural 是证据，不得把根类变候选")

    def test_counter_patterns_produce_excluded(self):
        """C-20261013-15：判据显式给 counter_patterns 且命中 ⇒ excluded（留档，不静默丢弃）。"""
        obs = ["[现场] jps 输出含 iatrack 1042", "[现场] 进程清单里 iatrack 在"]
        out = self.out({"entry": "incremental_stuck", "observations": obs})
        self.assertIn("excluded", out, "counter_patterns 命中应产出 excluded")
        self.assertIn("counter_check 成立", out)

    def test_placeholder_patterns_attribute_sources(self):
        """C-20261013-15：来源归属须用通配匹配——否则 <pid> 类模式永远归不到来源。"""
        obs = ["[主机A] Killed process 1234 (java)",
               "[主机B] SocketException: Connection reset"]
        out = self.out({"entry": "dimension:resource", "observations": obs})
        self.assertIn("→ confirmed", out, "含占位的 hard 模式跨两来源时应可达 confirmed")


if __name__ == "__main__":
    unittest.main()
