#!/usr/bin/env python3
"""extract_docx.py — 从 `doc/projectdoc/` 的 .docx 抽取可读文本（61 号批 P-1）

**为什么需要**：`doc/projectdoc/` 那 10 份官方文档是 .docx（二进制 zip），
本体抽取要的是**按章可定位的纯文本**——**必须能只抽目标章**，因为
`Demo Product 9.1.5 用户指导手册.docx` 有 14.5 MB / 257 个标题，全量展开既慢又刷屏。

**抽什么**：`word/document.xml` 的**正文顺序**——`w:p`（段落，读 `w:pPr/w:pStyle` 判标题层级）
与 `w:tbl`（表格，行内以竖线连接）。两处**都必须按文档顺序处理软换行**：

  · 段落内的 `w:br` / `w:cr` 是官方文档的换行方式（"检查命令 / 修改命令"写在同一段落里），
    只取 `w:t` 会把这些命令**串成一串**（`sysctl ...tcp_memsysctl ...tcp_rmem`）；
  · 表格单元格内的多个段落同理，以 ` ; ` 分隔而非直接拼接。

**为什么要递归**：段落与表格常被包在容器节点（`w:sdt` / `w:sdtContent` / `mc:AlternateContent`）里，
只遍历 `body` 的直接子元素会**整篇漏空**。

用法:
  python3 scripts/extract_docx.py --list
  python3 scripts/extract_docx.py --doc "Demo Product文件输出原理.docx" --toc
  python3 scripts/extract_docx.py --doc "Demo Product 9.1.5 用户指导手册.docx" --chapter "3.5.6"
  python3 scripts/extract_docx.py --doc "Demo Product文件输出原理.docx" --all --out /tmp/f.txt

退出码：0 成功；1 文档不存在 / 读不出；2 参数错；3 指定章节未找到。
"""

import argparse
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCDIR = os.path.join(HERE, "doc", "projectdoc")
LF = chr(10)
TAB = chr(9)

# 标题层级：本仓文档混用 `Heading N` 与纯数字样式（`2` / `3` / `4`）两种写法。
_HEADING_RE = re.compile(r"^(?:Heading\s*)?([1-9])$")


def _level(style):
    """样式名 → 标题层级（1-9）；不是标题返回 0。"""
    if not style:
        return 0
    m = _HEADING_RE.match(style.strip())
    return int(m.group(1)) if m else 0


def _para_text(p):
    """段落文本——按文档顺序处理 `w:t` / `w:br` / `w:cr` / `w:tab`。"""
    parts = []
    for node in p.iter():
        if node.tag == W + "t":
            parts.append(node.text or "")
        elif node.tag in (W + "br", W + "cr"):
            parts.append(LF)
        elif node.tag == W + "tab":
            parts.append(TAB)
    return "".join(parts).strip()


def _table_text(tbl):
    """表格 → 每行一个字符串；单元格内多个段落以 ` ; ` 分隔（不能直接拼接）。"""
    rows = []
    for tr in tbl.findall(W + "tr"):
        cells = []
        for tc in tr.findall(W + "tc"):
            cell = " ; ".join(
                x.replace(LF, " ; ")
                for x in (_para_text(pp) for pp in tc.iter(W + "p"))
                if x
            )
            cells.append(cell)
        rows.append(" | ".join(cells))
    return [r for r in rows if r.strip(" |")]


def blocks(path):
    """按正文顺序产出 (level, text)。level>0 表示标题。"""
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml")
    except Exception as exc:  # 坏包 / 缺 document.xml
        raise SystemExit("读不出 %s: %s" % (path, exc))
    root = ET.fromstring(xml)
    body = root.find(W + "body")
    if body is None:
        raise SystemExit("没有 body: %s" % path)
    out = []

    def walk(node):
        for el in node:
            if el.tag == W + "p":
                st = el.find(W + "pPr/" + W + "pStyle")
                lv = _level(st.get(W + "val") if st is not None else "")
                txt = _para_text(el)
                if txt:
                    for i, one in enumerate(txt.split(LF)):
                        if one.strip():
                            out.append((lv if i == 0 else 0, one.strip()))
            elif el.tag == W + "tbl":
                for r in _table_text(el):
                    out.append((0, "[表] " + r))
            else:
                walk(el)

    walk(body)
    return out


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--list", action="store_true", help="列出 doc/projectdoc 下的 .docx")
    ap.add_argument("--doc", help="文档名（相对 doc/projectdoc/）")
    ap.add_argument("--toc", action="store_true", help="只输出标题骨架")
    ap.add_argument("--chapter", help="从匹配该前缀的标题抽到下一个同级或更高级标题")
    ap.add_argument("--all", action="store_true", help="输出全部正文")
    ap.add_argument("--max-lines", type=int, default=0, help="截断行数（0=不限）")
    ap.add_argument("--out", help="写入文件（默认 stdout）")
    args = ap.parse_args()

    if args.list:
        if not os.path.isdir(DOCDIR):
            print("没有目录: %s" % DOCDIR)
            return 1
        for n in sorted(os.listdir(DOCDIR)):
            if n.lower().endswith(".docx"):
                pp = os.path.join(DOCDIR, n)
                print("%8.1f MB  %s" % (os.path.getsize(pp) / 1048576.0, n))
        return 0

    if not args.doc:
        ap.print_help()
        return 2
    path = os.path.join(DOCDIR, args.doc)
    if not os.path.isfile(path):
        print("找不到: %s" % path)
        return 1

    bs = blocks(path)
    key = (args.chapter or "").replace(" ", "")
    lines = []
    if args.toc:
        lines = ["%s%s" % ("  " * (lv - 1), t) for lv, t in bs if lv]
    elif args.chapter:
        start = base = None
        for i, (lv, t) in enumerate(bs):
            if lv and t.replace(" ", "").startswith(key):
                start, base = i, lv
                break
        if start is None:
            print("未找到章节: %s" % args.chapter)
            return 3
        for j, (lv, t) in enumerate(bs[start:]):
            if j and lv and lv <= base:
                break
            lines.append(("%s%s" % ("  " * (lv - 1), t)) if lv else t)
    else:
        lines = [(("%s%s" % ("  " * (lv - 1), t)) if lv else t) for lv, t in bs]

    if args.max_lines:
        lines = lines[: args.max_lines]
    text = LF.join(lines) + LF
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print("写出 %d 行 → %s" % (len(lines), args.out))
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
