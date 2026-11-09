#!/usr/bin/env python3
"""91 号：发布收尾检查——插件代码改动后必须重启常驻进程，本脚本指引并复核。

顺序：1) 重启常驻 Hermes/插件进程（reload.py 只作用短命进程）；
      2) 重启后跑 check_loaded_version，期望退出码 0（插件指纹+BKN hash 均一致）。
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    print("发布收尾：")
    print("  1) 重启常驻 Hermes/插件进程（仅 reload.py 不够，常驻进程需重启）")
    print("  2) 重启后执行本脚本复核（或直接跑下方 check_loaded_version）")
    r = subprocess.run([sys.executable, str(ROOT / "plugin/scripts/check_loaded_version.py")])
    print("check_loaded_version exit =", r.returncode)
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())