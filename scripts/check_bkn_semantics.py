#!/usr/bin/env python3
"""91 号：本体语义覆盖机检（只读、启发式）。

检查：① .bkn 内 id 是否重复；② 关系端点(source/target/from/to)引用的 id 是否存在；
③ 输出疑似问题清单。只提醒，退出码 0=无问题 / 1=有疑似问题。
"""
import glob
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = glob.glob(str(ROOT / "bkn" / "**" / "*.bkn"), recursive=True)


def _lines():
    for f in FILES:
        for ln in open(f, encoding="utf-8", errors="ignore"):
            yield f, ln


def main() -> int:
    ids = []
    for _f, ln in _lines():
        m = re.match(r"^\s*id:\s*([^\s#]+)", ln)
        if m:
            ids.append(m.group(1))
    dup = [k for k, v in Counter(ids).items() if v > 1]
    defined = set(ids)
    ref_re = re.compile(r"^\s*(?:source|target|from|to)\s*:\s*([^\s#]+)")
    dangling = []
    for f, ln in _lines():
        m = ref_re.match(ln)
        if not m:
            continue
        ref = m.group(1)
        if ref in defined or ":" in ref:
            continue
        dangling.append((Path(f).name, ref))
    print("bkn files", len(FILES), "| ids", len(ids), "| dup", dup[:10])
    print("疑似悬空引用", len(dangling), dangling[:10])
    ok = not dup and not dangling
    print("结果：" + ("通过" if ok else "有疑似问题（人工复核）"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())