#!/usr/bin/env python3
"""mark_gaps_resolved.py — 按错误码把 gap_log.jsonl 中对应条目标记为 resolved

在错误码内容合入 BKN 后执行，完成 gap 反哺闭环的「清空」步骤。
保留原文件为 gap_log.jsonl.bak，输出替换原文件。

用法:
  python3 plugin/scripts/mark_gaps_resolved.py -4002 YAS-02276 ORA-00942 ...
  python3 plugin/scripts/mark_gaps_resolved.py --all-diagnose   # 标记所有 diagnose_error 条目
  python3 plugin/scripts/mark_gaps_resolved.py --dry-run ...    # 只统计不写入
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 2A: 与运行时同源——日志路径从 plugin/config.py 读取（env LOG_DIR 可覆盖）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import resolve_log_path  # noqa: E402
from log_rotate import iter_data_files  # noqa: E402

GAP_LOG = resolve_log_path("gap_log.jsonl")  # 逻辑基名（实际文件含日期）


def main():
    ap = argparse.ArgumentParser(description="标记 gap_log 条目为 resolved")
    ap.add_argument("codes", nargs="*", help="要标记的错误码（匹配 params.error_code）")
    ap.add_argument("--all-diagnose", action="store_true", help="标记所有 diagnose_error 条目")
    ap.add_argument("--dry-run", action="store_true", help="只统计不写入")
    args = ap.parse_args()

    files = iter_data_files(GAP_LOG)
    if not files:
        print("gap_log 数据文件不存在（新旧命名均未找到）")
        return 1

    total, marked = 0, 0
    written = []
    for f in files:  # 日期+大小双维命名后 gap 数据分散在多个文件，逐文件处理
        try:
            entries = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines()
                       if l.strip()]
        except OSError:
            continue
        file_marked = 0
        for e in entries:
            if e.get("resolved"):
                continue
            hit = False
            if args.all_diagnose and e.get("tool") == "diagnose_error":
                hit = True
            elif e.get("tool") == "diagnose_error":
                code = str(e.get("params", {}).get("error_code", ""))
                if code in args.codes:
                    hit = True
            if hit:
                e["resolved"] = True
                file_marked += 1
        total += len(entries)
        marked += file_marked
        if file_marked and not args.dry_run:
            bak = f.with_name(f.name + ".bak")
            bak.write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
            with open(f, "w", encoding="utf-8") as fh:
                for e in entries:
                    fh.write(json.dumps(e, ensure_ascii=False) + "\n")
            written.append(f.name)

    print(f"数据文件 {len(files)} 个, 总条目: {total}, 本次标记: {marked}")
    if args.dry_run:
        print("dry-run，未写入")
        return 0
    if written:
        print(f"已写入并备份原件: {', '.join(written)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
