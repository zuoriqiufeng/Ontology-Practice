#!/usr/bin/env python3
"""92 号：config 三方漂移只读检查（提醒，不阻断）。

比对 plugin/config.py 常量、plugin/config.yaml 键（树形含嵌套）、41-config_reference 文档键。
常量按「yaml section 前缀 → 常量前缀」映射参与比对，减少 EMB_/SEARCH_CACHE_ 等误报。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
py = (ROOT / "plugin/config.py").read_text(encoding="utf-8")
consts = set(re.findall(r"^([A-Z_]+) =", py, re.M))
yml = (ROOT / "plugin/config.yaml").read_text(encoding="utf-8")
dp = ROOT.joinpath("doc", "build", "demo_product-bkn", "41-config_reference.md")
doc = dp.read_text(encoding="utf-8") if dp.is_file() else ""
doc_keys = set(re.findall(r"`([A-Za-z_][A-Za-z0-9_.]*)`", doc))

# yaml section -> 其下的常量前缀（用于覆盖判定）
SECTION_CONST = {
    "qdrant": ("QDRANT", "SEARCH"),
    "bkn": ("BKN",),
    "tools": ("TOOLS", "SEARCH_OUTPUT"),
    "embedding": ("EMB",),
    "search": ("SEARCH",),
    "risk_guard": ("RISK_GUARD",),
    "log_rotate": ("LOG_ROTATE",),
    "llm": ("DIAGNOSTIC_KEYWORD",),
}
ENV_ONLY_PREFIX = ("OBSERVABILITY", "EXACT_CODE_LOOKUP", "CODE_ROW", "ASK_ENRICH", "BKN_MCP_TOKEN")


def yaml_tree_keys(text):
    keys = set()
    section = None
    current = None
    for ln in text.splitlines():
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        indent = len(ln) - len(ln.lstrip())
        mm = re.match(r"([A-Za-z0-9_]+):", ln.strip())
        if not mm:
            continue
        if indent == 0:
            section = mm.group(1)
            current = None
        elif indent == 2:
            current = mm.group(1)
            keys.add(current)
            if section:
                keys.add(section + "." + current)
        elif indent >= 4 and current:
            keys.add(current + "." + mm.group(1))
    return keys


def is_env_only(c):
    return any(c.startswith(p) for p in ENV_ONLY_PREFIX)


def main() -> int:
    tree = yaml_tree_keys(yml)
    sections = {t.split(".")[0] for t in tree}
    consts_up = {c.upper() for c in consts}
    def covered(c):
        if c in yml or c in doc_keys:
            return True
        cflat = c.lower().replace("_", ".")
        if any(cflat == t.replace("_", ".") for t in tree):
            return True
        for sec in sections:
            for pref in SECTION_CONST.get(sec, ()):
                if c.startswith(pref):
                    return True
        return False
    missing = [k for k in sorted(tree) if k.replace(".", "_").upper() not in consts_up and k not in doc_keys]
    unknown = [c for c in sorted(consts_up) if not covered(c) and not is_env_only(c) and not c.startswith("_")]
    env_only = sorted(c for c in consts_up if is_env_only(c) and c not in yml)
    print("config.py consts", len(consts_up), "| yaml 树键", len(tree), "| doc keys", len(doc_keys))
    print("yaml 键未在 config.py/41 命中:", missing[:20])
    print("未知常量（非 env-only 且未覆盖）:", unknown[:20])
    print("真 env-only（白名单，预期）:", env_only[:20])
    print("提示：启发式提醒，不判失败。")
    return 0


if __name__ == "__main__":
    sys.exit(main())