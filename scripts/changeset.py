#!/usr/bin/env python3
"""changeset.py — 版本 ↔ 记录的机械对账（27 号批 V-4）

**问题**：版本号住在 `bkn-version.json`，改动记录住在 `90-history/bkn-changelog.md`，
两头没有机械联系——"这一版对应哪条记录""这条记录是哪个版本"只能靠人记，
26 号 I13 的"缺口闭合数对账"也就没有键。

**约定（本批落地）**：changelog 里每条**发布**对应的条目内，写一行**版本锚行**（机读、唯一）：

```text
- **版本**：bkn-YYYYMMDD-N
```

锚行**该行只出现这一个版本号**（其后可跟一句简短说明，如 `（含 … 两次落盘）`）——
校验是"该行恰好能解析出一个版本号"，不是"整行必须光秃秃"。

**两种检查形态**（刻意分开）：

| 形态 | 跑到哪 | 为什么 |
|---|---|---|
| `--check`（门禁形态） | 已有锚行合法 / 唯一 / 不倒挂；`changeset_ref` 若指向候选，**候选须存在** | **不要求"当前版本必须有锚行"**，也不要求候选已 `applied`——`pending_apply` 落盘时会自动升版，且**复验门跑在候选 status 改写之前**；若门禁要求这两条，任何改 `.bkn` 的候选都会"升版 → 门禁红 → 回滚"。与 I14 的死锁同类（见 27 号 §3） |
| `--check --strict`（发布收尾） | 额外要求**当前版本**有锚行、且 `changeset_ref` 的候选 `status=applied` | 只有发布动作结束时才该满足；`pending_apply` 跑的是 `gate.sh --fast`，用的是上面那条 |

用法:
  python3 scripts/changeset.py --check              # I15（门禁形态）
  python3 scripts/changeset.py --check --strict     # 发布收尾（含当前版本）
  python3 scripts/changeset.py --show [版本号]       # 某版本的记录条目 + 涉及文件

退出码: 0 通过 / 1 不一致（供 gate.sh 用）

依据: doc/optimize/27-ontology-versioning-release.md §3 批 V-4 / §4 验收 / §7.1
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
CHANGELOG = REPO_ROOT / "doc" / "build" / "demo_product-bkn" / "90-history" / "bkn-changelog.md"
PENDING_DIR = REPO_ROOT / "doc" / "optimize" / "pending"

#: 版本锚行的前缀（机读约定的唯一入口，改动须同步 27 号 §2.2 与 changelog 头部说明）
ANCHOR_PREFIX = "- **版本**："

#: 合法版本号（显式字符类：本项目避免 \\d 一类简写，见 26 号边界约定）
VERSION_RE = re.compile(r"^bkn-[0-9]{8}-[0-9]+$")
#: 锚行内**查找**版本号用（容忍其后跟说明文字），要求恰好命中一个
VERSION_IN_LINE = re.compile(r"bkn-[0-9]{8}-[0-9]+")
#: 候选项 id（changelog 文本里引用候选时用它找来源）
CANDIDATE_RE = re.compile(r"C-[0-9]{8}-[0-9]+")
#: `bkn-version.json` 的 changeset_ref 形如「候选人 C-YYYYMMDD-NN」
_CANDIDATE_IN_REF = re.compile(r"(C-[0-9]{8}-[0-9]+)")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_version() -> dict | None:
    f = REPO_ROOT / "bkn-version.json"
    if not f.is_file():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def find_anchors() -> list[dict]:
    """返回 [{version, lineno, entry, entry_lineno}]；entry = 锚行所属的 `##` 条目标题。"""
    if not CHANGELOG.is_file():
        return []
    out: list[dict] = []
    entry, entry_lineno = "", 0
    for lineno, line in enumerate(CHANGELOG.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("## "):
            entry, entry_lineno = stripped[3:].strip(), lineno
        elif stripped.startswith(ANCHOR_PREFIX):
            tail = stripped[len(ANCHOR_PREFIX):].strip()
            found = VERSION_IN_LINE.findall(tail)
            out.append({
                # 恰好一个版本号才合法；0 个或多个 → version 留空，由 --check 报错（raw 保留原文）
                "version": found[0] if len(found) == 1 else "",
                "found": found, "raw": tail,
                "lineno": lineno, "entry": entry, "entry_lineno": entry_lineno,
            })
    return out


def _vkey(version: str) -> tuple[str, int] | None:
    """版本号排序键：`bkn-YYYYMMDD-N` → (日期, 序号)。非法返回 None。"""
    if not VERSION_RE.match(version):
        return None
    date, n = version[len("bkn-"):].split("-")
    return date, int(n)


def cmd_check(strict: bool) -> int:
    problems: list[str] = []
    current = read_version()
    cur_id = str((current or {}).get("version_id", ""))

    anchors = find_anchors()
    seen: dict[str, int] = {}
    for a in anchors:
        if not a["version"]:
            problems.append(f"changelog:{a['lineno']} 版本锚行须**恰好含一个版本号**，"
                            f"实得 {len(a['found'])} 个：{a['raw']!r}（应为 bkn-YYYYMMDD-N）")
            continue
        vid = a["version"]
        if vid in seen:
            problems.append(f"changelog:{a['lineno']} 版本锚行重复：{vid}"
                            f"（首次出现在 changelog:{seen[vid]}）")
        else:
            seen[vid] = a["lineno"]
        if cur_id and _vkey(cur_id) and _vkey(vid) > _vkey(cur_id):
            problems.append(f"changelog:{a['lineno']} 锚行版本 {vid} **晚于**当前版本 "
                            f"{cur_id}——版本倒挂")

    if strict:
        if not cur_id:
            problems.append("bkn-version.json 缺失或不可解析——无法对账")
        elif cur_id not in seen:
            problems.append(f"当前版本 {cur_id} 在 changelog 中**没有版本锚行**"
                            f"（发布收尾须写：{ANCHOR_PREFIX}{cur_id}）")

    ref = str((current or {}).get("changeset_ref", ""))
    m = _CANDIDATE_IN_REF.search(ref)
    if m:
        cid = m.group(1)
        cpath = PENDING_DIR / cid / "candidate.json"
        if not cpath.is_file():
            problems.append(f"changeset_ref 指向候选 {cid}，但候选目录不存在：{cpath}")
        elif strict:
            # `status=applied` 只在 strict 要求：apply 的复验门跑在本检查**之前**，
            # 那一刻候选还是 pending（status 是复验通过后才写的）——门禁形态若要求
            # applied，任何候选都会"落盘 → 门禁红 → 回滚"（与 I14 同类死锁）。
            try:
                status = json.loads(cpath.read_text(encoding="utf-8")).get("status")
            except json.JSONDecodeError:
                status = None
            if status != "applied":
                problems.append(f"changeset_ref 指向候选 {cid}，但其 status={status!r}"
                                f"（发布收尾应已是 'applied'）")

    if problems:
        print("✗ changeset 对账未通过（I15）：", file=sys.stderr)
        for p in problems:
            print(f"    {p}", file=sys.stderr)
        return 1
    mode = "strict" if strict else "门禁形态"
    print(f"✓ changeset 对账通过（{mode}）：锚行 {len(anchors)} 条"
          f"{'，当前版本 ' + cur_id if cur_id else ''}")
    return 0


def _candidate_files(cid: str) -> tuple[list[tuple[str, str]], list[str], str]:
    """返回 ([(相对路径, 变更类型)], patch 文件, 说明)。变更类型 = 新增/修改/无变化。"""
    cand = PENDING_DIR / cid
    if not cand.is_dir():
        return [], [], f"候选目录不存在：{cand}"
    # 复用 apply 时的同一套 payload 语义（含 `.pre-apply` 排除）——定义只能有一处
    sys.path.insert(0, str(SCRIPTS_DIR))
    import pending_apply as pa  # noqa: PLC0415

    copies, patches = pa.collect_payload(cand)
    payload = cand / "payload"
    prev_manifest: dict = {}
    prev_file = payload / ".pre-apply" / "bkn-version.json"
    note = ""
    if prev_file.is_file():
        try:
            prev_manifest = json.loads(prev_file.read_text(encoding="utf-8")).get("files") or {}
        except json.JSONDecodeError:
            note = f"（{prev_file.name} 不可解析，无法判定变更类型）"
    else:
        note = "（无 pre-apply 版本清单——该候选落盘于 V-4 之前，只列它碰过的文件）"

    rows: list[tuple[str, str]] = []
    for f in sorted(copies, key=lambda p: str(p.relative_to(payload))):
        rel = str(f.relative_to(payload))
        digest = _sha256(f)
        if not prev_manifest:
            kind = "涉及"
        elif rel not in prev_manifest:
            kind = "新增"
        elif prev_manifest[rel] != digest:
            kind = "修改"
        else:
            kind = "无变化"
        rows.append((rel, kind))
    return rows, [str(p.relative_to(payload)) for p in patches], note


def cmd_show(version: str | None) -> int:
    current = read_version()
    vid = "" if (version or "") == "current" else str(version or "")
    vid = vid or str((current or {}).get("version_id", ""))
    if not vid:
        print("✗ 未指定版本且 bkn-version.json 不可用", file=sys.stderr)
        return 2

    anchors = [a for a in find_anchors() if a.get("version") == vid]
    print(f"版本：{vid}")
    if current and vid == current.get("version_id"):
        print(f"  released_at : {current.get('released_at')}")
        print(f"  version_hash: {current.get('version_hash')}")
        print(f"  label       : {current.get('label') or '—'}")
    if anchors:
        a = anchors[0]
        print(f"  changelog   : 第 {a['entry_lineno']} 行条目标题：{a['entry']}（锚行在第 {a['lineno']} 行）")
    else:
        print("  changelog   : **无版本锚行**（发布收尾补齐；--check --strict 会报）")

    # 来源：本版本的 changeset_ref（若指当前版本）或条目文本里的候选 id
    ref = str((current or {}).get("changeset_ref", "")) if vid == (current or {}).get("version_id") else ""
    text = ""
    if anchors:
        lines = CHANGELOG.read_text(encoding="utf-8").splitlines()
        start = anchors[0]["entry_lineno"] - 1
        end = anchors[0]["lineno"]
        text = "\n".join(lines[start:end])
    cands: list[str] = []
    for blob in (ref, text):
        for m in CANDIDATE_RE.finditer(blob):
            if m.group(0) not in cands:
                cands.append(m.group(0))

    if not cands:
        print("  涉及文件    : **无可考来源**（该版本不是由待审区候选落盘产生的——"
              "如首版由 `bkn_version.py --write` 直接生成）")
        return 0

    for cid in cands:
        rows, patches, note = _candidate_files(cid)
        print(f"  来源候选    : {cid} {note}")
        for rel, kind in rows:
            print(f"    {kind}: {rel}")
        for p in patches:
            print(f"    patch（需人工 git apply）: {p}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="版本 ↔ changelog 对账（27 号批 V-4）")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true", help="I15 对账（配 --strict 含当前版本）")
    g.add_argument("--show", nargs="?", const="current", metavar="版本号",
                   help="打印某版本的记录条目与涉及文件（默认当前版本）")
    ap.add_argument("--strict", action="store_true", help="--check 时要求当前版本必须有锚行")
    ns = ap.parse_args(argv)
    if ns.check:
        return cmd_check(ns.strict)
    return cmd_show(ns.show)


if __name__ == "__main__":
    raise SystemExit(main())
