#!/usr/bin/env python3
"""92 号：文档-代码一致性机检（只读提醒）。

检查：① plugin/*.py 是否都在 30-modules.md；② 是否残留「13 Tool」旧口径；
③ 关键机制词（tier/detail/plugin_fingerprint/cache.mini_first）是否在对应文档。
退出码 0=通过；有漂移退出 1（gate ①e 只提醒，不阻断）。
"""
import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(ROOT, "doc", "build", "demo_product-bkn")


def read(name):
    p = os.path.join(DOC, name)
    return open(p, encoding="utf-8").read() if os.path.exists(p) else ""


def main() -> int:
    mods = read("30-modules.md")
    arch = read("01-architecture.md")
    tools_doc = read("31-tools.md")
    cfg_doc = read("41-config_reference.md")
    missing = []
    for f in sorted(glob.glob(os.path.join(ROOT, "plugin", "*.py"))):
        name = os.path.basename(f)
        if name == "__init__.py":
            continue
        if name not in mods:
            missing.append(name)
    bad_tool = sum(s.count("13 个 Tool") + s.count("13 Tool") for s in (mods, arch, tools_doc, cfg_doc))
    kw = {
        "tier": ("意图分级" in mods and "tier" in tools_doc),
        "detail": ("detail" in tools_doc),
        "plugin_fingerprint": ("plugin_fingerprint" in mods or "plugin_fingerprint" in arch),
        "cache.mini_first": ("mini_first" in cfg_doc),
    }
    print("模块未在 30-modules:", missing)
    print("残留 13 Tool 口径:", bad_tool)
    print("关键机制词:", kw)
    ok = (not missing) and bad_tool == 0 and all(kw.values())
    print("结果:", "通过" if ok else "有漂移（人工复核）")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())