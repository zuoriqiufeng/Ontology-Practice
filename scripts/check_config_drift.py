#!/usr/bin/env python3
"""91 号：config 三方漂移只读检查（提醒，不阻断）。

比对 plugin/config.py 常量、plugin/config.yaml 键、41-config_reference 文档键，输出疑似漂移。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
py = (ROOT / "plugin/config.py").read_text(encoding="utf-8")
consts = set(re.findall(r"^([A-Z_]+) =", py, re.M))
yml = (ROOT / "plugin/config.yaml").read_text(encoding="utf-8")
keys = set(re.findall(r"^  ([a-z_]+):", yml, re.M))
dp = ROOT.joinpath("doc", "build", "demo_product-bkn", "41-config_reference.md")
doc = dp.read_text(encoding="utf-8") if dp.is_file() else ""
doc_keys = set(re.findall(r"`([A-Za-z_][A-Za-z0-9_.]*)`", doc))


def main() -> int:
    missing = [k for k in sorted(keys) if k.upper() not in consts and k not in doc]
    miss2 = [c for c in sorted(consts) if c not in yml and c not in doc]
    print("config.py consts", len(consts), "| yaml keys", len(keys), "| doc keys", len(doc_keys))
    print("yaml 键在 config.py/41 均未命中:", missing[:20])
    print("常量未在 yaml/41 提及:", miss2[:20])
    print("提示：启发式提醒，不判失败。")
    return 0


if __name__ == "__main__":
    sys.exit(main())