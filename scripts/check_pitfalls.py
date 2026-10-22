#!/usr/bin/env python3
"""check_pitfalls.py — 踩坑台账（doc/optimize/00-pitfalls.md）格式门禁。

只校验「能不能被稳定引用」：编号唯一且递增、七个列都有内容、反模式/正解非空。
不校验内容质量（那要靠人评审）。

用法:
    python3 scripts/check_pitfalls.py                # 校验默认台账
    python3 scripts/check_pitfalls.py --file X.md
台账不存在时打印跳过并返回 0（开源仓不含该文档）。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / "doc" / "optimize" / "00-pitfalls.md"
ID_RE = re.compile(r"^P-[0-9]{3}$")
COLUMNS = ["编号", "坑（症状）", "根因", "别再这么做", "该怎么做", "谁拦住了", "关联"]


def check(path: Path) -> list[str]:
    errors: list[str] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    if not any("硬规则" in l for l in lines[:20]):
        errors.append("缺少「六条硬规则」段（文件头必须列出可执行规则）")
    header_ok = False
    ids: list[str] = []
    seen: set[str] = set()
    for lineno, line in enumerate(lines, 1):
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]
        if cells[0] in ("编号",) and len(cells) >= 7:
            if [c.replace(" ", "") for c in cells[:7]] != [c.replace(" ", "") for c in COLUMNS]:
                errors.append(f"L{lineno}: 表头列不符，应为 {' | '.join(COLUMNS)}")
            header_ok = True
            continue
        if not ID_RE.match(cells[0]):
            continue
        if len(cells) < 7:
            errors.append(f"L{lineno}: {cells[0]} 列数不足（{len(cells)} < 7）")
            continue
        entry_id = cells[0]
        if entry_id in seen:
            errors.append(f"L{lineno}: 编号重复 {entry_id}")
        seen.add(entry_id)
        ids.append(entry_id)
        for idx, name in ((1, "坑（症状）"), (2, "根因"), (3, "别再这么做"), (4, "该怎么做")):
            if len(cells[idx]) < 4:
                errors.append(f"L{lineno}: {entry_id} 的「{name}」为空或过短")
    if not header_ok:
        errors.append("缺少台账表头")
    if not ids:
        errors.append("台账里没有任何 P-NNN 条目")
    if ids != sorted(ids):
        errors.append(f"编号未按序排列：{ids}（只增不改，新条目加在末尾）")
    return errors


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=str(DEFAULT))
    args = ap.parse_args()
    path = Path(args.file)
    if not path.exists():
        print(f"跳过：台账不存在（{path}）")
        return 0
    errors = check(path)
    if errors:
        print("踩坑台账校验失败：")
        for err in errors:
            print("  -", err)
        return 1
    count = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("| P-"))
    print(f"踩坑台账 OK（{count} 条）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
