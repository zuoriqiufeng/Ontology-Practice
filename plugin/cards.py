"""cards.py — 本体卡片编译器（P1：摘要优先交付形态）

把本体的一小块（对象/维度/风险/关系）编译成一页 ≤limit 字符的卡片：
  `# <target> ｜ <file>` + 段头与正文前若干行 + 抽出的 `skill:` 指针。

用途（同一份代码三处复用）：
  1) `@bkn:<id>` 按需展开（context reference）；
  2) 请求级注入（llm_request middleware）；
  3) `bkn_ask` 的 `detail=ref` 兜底。
"""
from __future__ import annotations

import re
from pathlib import Path

_HERE = Path(__file__).resolve().parent
BKN_ROOT = (_HERE / "bkn") if (_HERE / "bkn").exists() else (_HERE.parent / "bkn")

_DIRS = {
    "object": "objects",
    "entity": "objects",
    "dimension": "objects",
    "risk": "risks",
    "relation": "relations",
    "action": "actions",
}
_SKILL = re.compile(r"skill:([A-Za-z0-9_\-]+)")


def build_card(kind: str, target: str, limit: int = 600) -> str:
    """编译一页卡片；找不到时返回可读的短提示（不抛异常）。"""
    kind = (kind or "object").strip().lower()
    target = (target or "").strip()
    if not target:
        return "未找到（目标为空）"
    pats = [
        re.compile(r"^##[ \t]+[^:]+:[ \t]*" + re.escape(target) + r"[ \t]*$", re.I),
        re.compile(r"^id:[ \t]*" + re.escape(target) + r"[ \t]*$", re.I),
    ]
    folder = _DIRS.get(kind, "objects")
    d = BKN_ROOT / folder
    if not d.is_dir():
        return "本体目录不存在：%s" % d
    for f in sorted(d.glob("*.bkn")):
        try:
            lines = f.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for i, ln in enumerate(lines):
            if any(p.match(ln.strip()) for p in pats):
                return _render(lines, i, f, target, limit)
    return "未找到「%s」的 %s 卡片（可先在 bkn/%s 下登记）" % (target, kind, folder)


def _render(lines, start: int, f: Path, target: str, limit: int) -> str:
    out = ["# %s ｜ %s" % (target, f.name)]
    for ln in lines[start:start + 24]:
        s = ln.rstrip()
        if not s or s.startswith("|--"):
            continue
        out.append(s)
        if sum(len(x) for x in out) >= limit:
            break
    text = "\n".join(out)
    skills = sorted({m.group(1) for m in _SKILL.finditer(text)})
    if skills:
        text += "\nSkills：" + ", ".join(skills)
    return text[:limit]
