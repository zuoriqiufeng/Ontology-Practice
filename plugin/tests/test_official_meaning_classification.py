"""官方含义分类与「只给码」闸门（63／64 号）。

守五件事：

1. **闸门（统一）**：`get_risk(码)` 无消息文本时——`status=统一` 的码据官方含义给维度。
2. **单源（64 号 Step A）**：`status=单源` 的码**也给维度**，但 `evidence` **必须**标注
   「单源（厂商文档，未经现场验证）」——给能力，同时给不确定度。
3. **冲突码不选边**：`区分` / `待现场复核` 一律 `unknown` ＋ 把冲突写出来。
4. **过泛词已挡（64 号 Step C）**：`match_official_deny` 让「装载停滞 / 服务重启 / 等待超时」
   在**官方路径**上不成立（现场路径不受影响，走 `match`）。
5. **现场路径不变**：`match` 一个字未动；裸码不点进程（32 号契约）。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import plugin.tools as T  # noqa: E402

#: status=统一 → 官方含义与仓内说法**确为同一件事**
GATE_CASES = {
    "-4002": "dimension:log_readable",      # IAERR_LOG_SEQ 无法查找指定序号的redolog
    "-4016": "dimension:connectivity",      # IAERR_OFFLINE 节点离线，通常为 iahelper 程序异常
    "-4071": "dimension:state_machine",     # IAERR_RULE_IS_RUNNING 规则是运行状态，不能再次启动此规则
}

#: status=单源（64 号 Step A）→ 给维度，但 evidence 必须标注单源
SINGLE_SOURCE_CASES = {
    "-4231": "dimension:resource",          # 机器节点CPU占用超过阈值
    "-4224": "dimension:connectivity",      # 节点离线
    "-4027": "dimension:permission",        # 节点口令认证失败
    "-4072": "dimension:state_machine",     # track是运行或者停止状态，不能进行相应操作
}

#: status=区分 / 待现场复核 → 必须 unknown ＋ 冲突说明
CONFLICT_CASES = ["-4046", "-4031", "-4073"]

#: **不在表中** ⇒ unknown
UNTRUSTED_CODES = ["-9999"]

#: Step C：过泛词已由 match_official_deny 挡下 ⇒ **不得**给维度
DENIED_CODES = ["-4241", "-4043", "-4032", "-4051", "-4009"]


class TestBareCodeGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        T._init()

    def test_unified_codes_get_dimension(self):
        for code, expect in GATE_CASES.items():
            got = T._resolver.get_risk(code)
            self.assertIn(expect, got.get("dimensions", []),
                          code + " 裸码应据官方含义给出 " + expect + "，实得 " + str(got.get("dimensions")))
            self.assertEqual(got.get("meaning_source"), "code")
            self.assertEqual(got.get("conflicts"), [], code + " 不应有冲突")
            self.assertTrue(got.get("diagnosed_skills") or got.get("needs"),
                            code + " 应给出 Skill 路由或 needs")

    def test_single_source_codes_disclose_the_source(self):
        """64 号 Step A：单源代码给维度，但**必须**标注单源未经现场验证。"""
        for code, expect in SINGLE_SOURCE_CASES.items():
            got = T._resolver.get_risk(code)
            self.assertIn(expect, got.get("dimensions", []),
                          code + " 应据官方含义给出 " + expect + "，实得 " + str(got.get("dimensions")))
            self.assertEqual(got.get("meaning_source"), "code")
            self.assertEqual(got.get("conflicts"), [], code + " 不应有冲突")
            ev = (got.get("meaning") or {}).get("evidence", "")
            self.assertIn("单源", ev, code + " 的 evidence 未标注单源：" + ev)

    def test_conflicting_codes_stay_unknown_and_say_why(self):
        for code in CONFLICT_CASES:
            got = T._resolver.get_risk(code)
            self.assertEqual(got.get("dimensions"), ["dimension:unknown"],
                             code + " 属区分/待复核，不得给维度（实得 " + str(got.get("dimensions")) + "）")
            self.assertTrue(got.get("conflicts"), code + " 必须把冲突写出来（conflicts 为空）")
            self.assertIn("官方含义", got["conflicts"][0], code + " 的冲突说明应含官方含义")
            self.assertTrue(got.get("needs"), code + " 必须说明还缺什么")

    def test_untrusted_codes_stay_unknown(self):
        for code in UNTRUSTED_CODES:
            got = T._resolver.get_risk(code)
            self.assertEqual(got.get("dimensions"), ["dimension:unknown"],
                             code + " 不在表中 ⇒ 不得据含义给维度")
            self.assertEqual(got.get("conflicts"), [])

    def test_overbroad_words_are_denied(self):
        """64 号 Step C：装载停滞 / 服务重启 / 等待超时 等过泛词在官方路径上不得成立。"""
        for code in DENIED_CODES:
            got = T._resolver.get_risk(code)
            self.assertEqual(got.get("dimensions"), ["dimension:unknown"],
                             code + " 命中过泛词，应被 deny 挡下（实得 " + str(got.get("dimensions")) + "）")

    def test_denied_codes_land_on_the_right_dimension(self):
        """deny 之后这两个码应落到**正确的**维度，而不是原来的误判维度。"""
        self.assertIn("dimension:consistency", T._resolver.get_risk("-4067").get("dimensions", []),
                      "装载错误过多超过阈值 ⇒ 主体是装载错误（consistency）")
        self.assertIn("dimension:resource", T._resolver.get_risk("-4058").get("dimensions", []),
                      "规则装载停滞导致达到磁盘使用限额阈值 ⇒ resource")

    def test_bare_code_never_pins_process(self):
        """32 号契约不变：裸码不给嫌疑进程（那需要 log_source）。"""
        for code in list(GATE_CASES) + list(SINGLE_SOURCE_CASES) + CONFLICT_CASES:
            self.assertEqual(T._resolver.get_risk(code).get("suspected_process"), [],
                             code + " 裸码不得给嫌疑进程")

    def test_message_path_is_unchanged(self):
        """现场消息文本仍走 match 词表——行为与 63 号之前一致。"""
        got = T._resolver.get_risk("-4073", message="规则 ABNORMAL，归档被清理，位点不连续")
        self.assertEqual(got.get("meaning_source"), "message")
        self.assertEqual(got.get("dimensions"), ["dimension:log_readable"])
        self.assertEqual(got.get("conflicts"), [])


if __name__ == "__main__":
    unittest.main()
