#!/usr/bin/env python3
"""check_tier.py — 89 号验收（机检）：tier_classify 对 5 类用例的判级断言。

用法: python3 scripts/check_tier.py；退出码 0=全过 / 1=有失败。
只读，不改任何文件。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from plugin.tier_router import tier_classify  # noqa: E402

CASES = [
    ("纯知识", "ORA-01555 和 ORA-08186 什么关系", "L0"),
    ("错误码", "Demo Product 报 -4062 是什么", "L0"),
    ("含锚点", "规则 7D0F3DE8 页面报 4062，帮我看下", "L1"),
    ("灰区",   "track 增量停滞一般怎么排查", "L0"),
    ("排障",   "重启一下增量任务", "L2"),
]


def main() -> int:
    fails = 0
    for name, q, expect in CASES:
        got = tier_classify(q)[0]
        ok = got == expect
        print("%s %s: %r -> %s (期望 %s)" % ("PASS" if ok else "FAIL", name, q, got, expect))
        fails += 0 if ok else 1
    # 结构在位检查：prompt_sections 守则含「意图分级」条款
    from plugin.prompt_sections import RULES as _RULES
    print("结构在位：prompt_sections 含意图分级 =", "意图分级" in _RULES)
    print("结果：" + ("全部通过" if fails == 0 else "%d 失败" % fails))
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())