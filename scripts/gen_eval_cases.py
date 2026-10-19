#!/usr/bin/env python3
"""gen_eval_cases.py — 从本体/侧车内容生成 P0 评测用例（确定性、可复跑）。

产出：evals/cases/ontology_qa_50.jsonl
  20 条症状用例（SYMPTOM_ALIASES → diagnose_db_link）
  10 条错误码用例（plugin/error_codes.yaml → diagnose_error）
  5 条关系用例（relations/*.bkn 的源对象 → resolve_relation）
  5 条操作用例（actions/*.bkn 的动作名 → resolve_operation）
  5 条兼容性用例（固定库对 → check_compatibility）

判据字段 expect: 任一 token 命中即算「证据落地」。
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from plugin.constants import SYMPTOM_ALIASES  # noqa: E402

OUT = ROOT / "evals" / "cases" / "ontology_qa_50.jsonl"


def symptom_cases(n: int = 20) -> list:
    rows = []
    # 跨全集等距取样（避免只取到字符序最前的拉丁别名）
    ordered = sorted(SYMPTOM_ALIASES)
    stride = max(1, len(ordered) // max(n, 1))
    picked = ordered[::stride][:n]
    for alias in picked:
        rows.append({
            "id": "sym-%02d" % (len(rows) + 1),
            "category": "symptom",
            "question": "出现「%s」时该怎么排查？" % alias,
            "tool": "diagnose_db_link",
            "args": {"symptom": alias},
            "expect": [alias],
        })
    return rows


def code_cases(n: int = 10) -> list:
    import yaml
    data = yaml.safe_load((ROOT / "plugin" / "error_codes.yaml").read_text(encoding="utf-8"))
    seen = set()
    rows = []
    for item in data.get("codes") or []:
        code = str(item.get("code") or "").strip()
        if not code or code in seen:
            continue
        seen.add(code)
        rows.append({
            "id": "code-%02d" % (len(rows) + 1),
            "category": "error_code",
            "question": "错误码 %s 是什么含义、该怎么处理？" % code,
            "tool": "diagnose_error",
            "args": {"error_code": code},
            "expect": [code, "-" + code],
        })
        if len(rows) >= n:
            break
    return rows




def relation_cases(n: int = 5) -> list:
    import glob
    sources = []
    for f in sorted(glob.glob(str(ROOT / "bkn" / "relations" / "*.bkn"))):
        for ln in open(f, encoding="utf-8"):
            m = re.match(r"- \*\*源对象\*\*: (.+)", ln.strip())
            if m:
                src = m.group(1).strip()
                if src not in sources:
                    sources.append(src)
    rows = []
    for src in sources[:n]:
        rows.append({
            "id": "rel-%02d" % (len(rows) + 1),
            "category": "relation",
            "question": "「%s」和谁相连、有哪些关系？" % src,
            "tool": "resolve_relation",
            "args": {"source_entity": src},
            "expect": [src],
        })
    return rows


def operation_cases(n: int = 5) -> list:
    import glob
    names = []
    for f in sorted(glob.glob(str(ROOT / "bkn" / "actions" / "*.bkn"))):
        for ln in open(f, encoding="utf-8"):
            if ln.startswith("## Action: "):
                name = ln[len("## Action: "):].strip()
                if name and name not in names:
                    names.append(name)
    rows = []
    for name in names[:n]:
        rows.append({
            "id": "op-%02d" % (len(rows) + 1),
            "category": "operation",
            "question": "「%s」这个操作由哪个 Skill 提供、要什么参数？" % name,
            "tool": "resolve_operation",
            "args": {"operation": name},
            "expect": [name, "capability"],
        })
    return rows


def compatibility_cases() -> list:
    pairs = [("oracle", "mysql"), ("mysql", "postgresql"), ("db2", "oracle"),
             ("sqlserver", "mysql"), ("dm", "oracle")]
    rows = []
    for src, dst in pairs:
        rows.append({
            "id": "cmp-%02d" % (len(rows) + 1),
            "category": "compatibility",
            "question": "%s 到 %s 的同步是否支持？有什么风险？" % (src, dst),
            "tool": "check_compatibility",
            "args": {"source": src, "target": dst},
            "expect": ["supported"],
        })
    return rows


def main() -> int:
    cases = symptom_cases(20) + code_cases(10) + relation_cases(5) + operation_cases(5) + compatibility_cases()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        for c in cases:
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")
    print("写入 %d 条用例 → %s" % (len(cases), OUT.relative_to(ROOT)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
