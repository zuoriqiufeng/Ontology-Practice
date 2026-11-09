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
    # L0 纯知识
    ("纯知识", "ORA-01555 和 ORA-08186 什么关系", "L0"),
    ("错误码", "Demo Product 报 -4062 是什么", "L0"),
    ("灰区", "track 增量停滞一般怎么排查", "L0"),
    # 90 修订：变更词遇疑问型不得升 L2
    ("知识-执行失败", "增量任务执行失败怎么排查", "L0"),
    ("知识-SQL慢", "SQL 执行缓慢是什么原因", "L0"),
    ("知识-删表影响", "删表会影响其他库吗", "L0"),
    ("知识-删除权限", "删除一个同步任务需要什么权限", "L0"),
    ("知识-启动原因", "服务启动失败的常见原因有哪些", "L0"),
    ("知识-启用步骤", "启用增量同步的步骤", "L0"),
    # L2 真变更/排障
    ("排障-重启", "重启一下增量任务", "L2"),
    ("排障-删规则", "把规则删了", "L2"),
    ("排障-停用启用", "把这条规则停用再启用", "L2"),
    ("排障-启停", "请帮我把服务启停一下", "L2"),
    ("排障-改配置", "修改 oracle 配置", "L2"),
    ("排障-执行恢复", "执行一次恢复", "L2"),
    # L1 锚点/只读查证
    ("含锚点", "规则 7D0F3DE8 页面报 4062，帮我看下", "L1"),
    ("含IP", "192.0.2.1 同步连不上", "L1"),
    ("含时间", "今天 14 点增量停了，查下日志", "L1"),
    ("查看型", "帮我看下机器现在内存", "L1"),
    ("变更+查看", "查一下逻辑备份导出失败", "L1"),
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
