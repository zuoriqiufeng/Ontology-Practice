#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_doc_links.py — 只读死链门禁（87 号优化计划 · 批2＝阶段2 文档治理 · O-18 方案 A）

用途与规则（与 AGENT.md R-1 对齐，87 号 O-18「方案 A：索引件豁免 + 只读死链门禁」）：
  * 遍历 doc/**/*.md，提取 markdown 相对链接（[...](target)）。
  * **只**把「相对链接的目标 在磁盘上不存在」判为 DEAD。唯一判死标准 = 目标文件/目录不存在。
  * 两类范围**不计死链**（其相对指向天然允许「目标在 _archived 内」或「为取证而复述死链」）：
      - doc/_archived/** ：冻结归档快照，其旧链接是历史记录，不在现行集；
      - doc/audit/**     ：只读审计/取证报告，会**复述**被审计的死链作为证据；
  * 三处索引入口（doc/README.md、build 的 00-index、optimize/00-index.md）的条目表允许指向现存文件的相对链接，目标存在即不算死链。
  * 外链（http/https）、锚点（#…）、mailto/data、以及目标含空白（多为正文/代码块误读）不判。
  * 退出码：0 = 无死链；1 = 有死链。纯标准库，无外来依赖。
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOC_ROOT = REPO / "doc"

_SKIP_PREFIX = ("http://", "https://", "#", "mailto:", "data:")
_SKIP_SUBTREE = ("_archived", "audit")
# 相对链接目标不含空白；含空白的多半是正文/代码块里的误读，不算链接
_LINK_RE = re.compile(r"\]\s*\(([^)\s]+)\)")


def iter_md():
    for p in sorted(DOC_ROOT.rglob("*.md")):
        rel = p.relative_to(DOC_ROOT).parts
        if rel[0] in _SKIP_SUBTREE:
            continue
        yield p


def main() -> int:
    dead = []
    files_scanned = 0
    links_checked = 0

    for path in iter_md():
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        files_scanned += 1
        for target in _LINK_RE.findall(text):
            if target.startswith(_SKIP_PREFIX):
                continue
            path_part = target.split("#", 1)[0].strip()
            if not path_part:
                continue
            links_checked += 1
            resolved = (path.parent / path_part).resolve()
            if not resolved.exists():
                dead.append((path.relative_to(DOC_ROOT).as_posix(), target))

    print("== check_doc_links.py（87 号 O-18 · 只读死链门禁）==")
    print(f"扫描现行 docs 文件数 : {files_scanned}")
    print(f"检查相对链接数       : {links_checked}")
    print(f"DEAD 死链数          : {len(dead)}（不含 doc/_archived/ 冻结归档与 doc/audit/ 审计取证）")
    if dead:
        print("下列相对链接目标在磁盘上不存在（DEAD）：")
        for rel, tgt in dead:
            print(f"  - {rel}  ->  {tgt}")
    else:
        print("现行文档集无死链（目标=0）。")
    return 1 if dead else 0


if __name__ == "__main__":
    sys.exit(main())
