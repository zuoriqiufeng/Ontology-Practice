#!/usr/bin/env python3
"""redact.py — 开源前的敏感命中扫描（只读、只出报告，不改文件）。

五类命中：① 产品名（i2stream / i2UP）② 厂商名（英方）③ 内网 IP ④ 邮箱 ⑤ 内部路径/工单/客户字样。
用法：python3 tools/redact.py --root . --report tools/redact-report.md
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

CATS = [
    ("产品名", re.compile(r"i2stream|i2up", re.IGNORECASE)),
    ("厂商名", re.compile(r"英方")),
    ("内网IP", re.compile(r"(?<![0-9])(?:10\.[0-9]{1,3}|192\.168|172\.(?:1[6-9]|2[0-9]|3[01]))\.[0-9]{1,3}\.[0-9]{1,3}")),
    ("邮箱", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("内部痕迹", re.compile(r"/hdd/demo|/root/\.hermes|<local-path>|BUG-[0-9]{4}|客户名称")),
]
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "node_modules", ".venv"}
WHITELIST = {"plugin/tests/test_ontology_use.py": "内部路径守卫断言（assertNotIn 内部路径），非泄漏"}
SKIP_EXT = {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".zip", ".gz", ".pyc"}


def _walk(root: Path):
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.suffix.lower() in SKIP_EXT:
            continue
        yield p


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--report", default="redact-report.md")
    a = ap.parse_args()
    root = Path(a.root).resolve()
    hits = {name: [] for name, _ in CATS}
    scanned = 0
    for p in _walk(root):
        rel = p.relative_to(root).as_posix()
        if rel in WHITELIST or rel.startswith("tools/redact"):
            continue  # 扫描器自身的词表不算命中
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        scanned += 1
        for name, rx in CATS:
            n = len(rx.findall(text))
            if n:
                hits[name].append((rel, n))
    lines = ["# 开源前敏感扫描报告", "", "- 根目录：`%s`" % root, "- 扫描文件：%d" % scanned, ""]
    total = 0
    for name, _ in CATS:
        rows = sorted(hits[name], key=lambda x: -x[1])
        total += sum(n for _, n in rows)
        lines.append("## %s（%d 个文件）" % (name, len(rows)))
        lines.append("")
        if not rows:
            lines.append("（无命中）")
        else:
            lines.append("| 文件 | 命中数 |")
            lines.append("|---|---|")
            for rel, n in rows[:60]:
                lines.append("| `%s` | %d |" % (rel, n))
            if len(rows) > 60:
                lines.append("| …（另有 %d 个文件） | |" % (len(rows) - 60))
        lines.append("")
    lines.append("## 已豁免（显式白名单）")
    lines.append("")
    for path, why in WHITELIST.items():
        lines.append("- `%s`：%s" % (path, why))
    lines.append("")
    lines.append("**合计命中：%d**" % total)
    out = Path(a.report)
    out.write_text(chr(10).join(lines) + chr(10), encoding="utf-8")
    print("扫描 %d 文件；报告写到 %s" % (scanned, out))
    for name, _ in CATS:
        print("  %-6s %d 文件" % (name, len(hits[name])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
