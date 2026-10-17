#!/usr/bin/env python3
"""bkn_version.py — BKN 版本身份（27 号批 V-0；答"现场跑的是哪一版"）

**为什么需要**：27 号 §1 实测——`git tag` 0 个、无版本目录、无 active 指针、无 changeset，
"现场此刻跑的是哪一版"**无法回答**；`.reload_state.json` 只有 mtime，不能证明生效。

**设计（Q7/Q18 裁定）**：
- **文件级 sha256 清单**（不是全量单 hash）——能回答"这次改动碰了哪几个文件"（回滚与评审要用）；
- **落仓库根 `bkn-version.json`**——部署形态可能是软链或拷贝（`doc/build/demo_product-bkn/40-build.md:10-21`），
  版本文件必须**随部署走**；放 `bkn/` 内会与「零元信息」（它本身就是元信息）冲突，放 `logs/` 会被 `.gitignore` 忽略；
- 版本号 `bkn-YYYYMMDD-N`（N = 当日序号，从既有版本自增，无需外部状态）；
- **hash 算法单点定义在本文件**，25 号批 U-2（服务自证）复用，不各写一套。

用法:
  python3 scripts/bkn_version.py --write            # 生成/升级版本（读完当前内容 → 写 bkn-version.json）
  python3 scripts/bkn_version.py --check            # 校验当前 bkn/ 内容与版本清单是否一致（I14）
  python3 scripts/bkn_version.py --show             # 打印当前版本身份
  python3 scripts/bkn_version.py --diff A B         # 比对两份版本文件（改了哪几个文件）

退出码: 0 一致 / 1 不一致或缺失（供 gate.sh 用）

依据: doc/optimize/27-ontology-versioning-release.md §2.2 / §2.4
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BKN_DIR = REPO_ROOT / "bkn"
VERSION_FILE = REPO_ROOT / "bkn-version.json"

#: 纳入版本清单的后缀——本体内容 + 本体指引（`.md` 是规范件，虽不被 resolver 加载，
#: 但它们的变更同样属于"这一版是什么样"，故一并纳入）
INCLUDE_SUFFIXES = (".bkn", ".md")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect_files(root: Path | None = None) -> list[Path]:
    root = root or BKN_DIR
    return [p for p in sorted(root.rglob("*"))
            if p.is_file() and "templates" not in p.parts and p.suffix in INCLUDE_SUFFIXES]


def manifest_for(root: Path | None = None, prefix: str = "bkn") -> dict:
    """文件级清单：`<prefix>/相对路径 -> sha256`（27 号 §2.2 的**单一算法**）。

    - 默认 `root=bkn/`、`prefix="bkn"` → 与仓库根 `bkn-version.json` 的键空间一致；
    - V-1（服务自证）对**插件实际加载的 BKN_ROOT** 复用本函数（prefix 不变），
      两处 hash 才能直接比对——不得各写一套。

    **相对根**（不是绝对、不是相对 cwd）——同一份内容无论从哪调用都得到同一个 hash
    （`pending_apply._payload_hash` 踩过这个坑）。
    """
    root = root or BKN_DIR
    files = {}
    for p in collect_files(root):
        files[f"{prefix}/{p.relative_to(root)}"] = sha256_file(p)
    return files


def build_manifest() -> dict:
    """默认仓库 bkn/ 的清单（等价旧实现，逐字节不变）。"""
    return manifest_for(BKN_DIR, "bkn")


def version_hash(files: dict) -> str:
    """由文件清单归并出版本 hash（排序后逐个喂 相对路径 + 文件 sha256）。"""
    h = hashlib.sha256()
    for rel in sorted(files):
        h.update(rel.encode("utf-8"))
        h.update(files[rel].encode("utf-8"))
    return h.hexdigest()


def read_version() -> dict | None:
    if not VERSION_FILE.is_file():
        return None
    try:
        return json.loads(VERSION_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def next_version_id(prev: dict | None, today: str) -> str:
    """`bkn-YYYYMMDD-N`：同一日自增 N，跨日归 1。从既有版本自增，无需外部状态。"""
    if prev:
        pid = str(prev.get("version_id", ""))
        if pid.startswith(f"bkn-{today}-"):
            try:
                return f"bkn-{today}-{int(pid.rsplit('-', 1)[1]) + 1}"
            except (ValueError, IndexError):
                pass
    return f"bkn-{today}-1"


def cmd_write(label: str, changeset: str, released_by: str) -> int:
    files = build_manifest()
    prev = read_version()
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    vhash = version_hash(files)
    if prev and prev.get("version_hash") == vhash:
        print(f"内容未变，版本仍为 {prev.get('version_id')}（hash {vhash[:16]}…）——未生成新版本")
        return 0
    doc = {
        "schema": 1,
        "version_id": next_version_id(prev, today),
        "version_hash": vhash,
        "released_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "released_by": released_by or "",            # 可选（Q20：不强填，避免形式主义）
        "changeset_ref": changeset or "",             # 指向 changelog 条目 / 号方案（V-4 的键）
        "label": label or "",
        "supersedes": (prev or {}).get("version_id", ""),
        "file_count": len(files),
        "files": files,
    }
    VERSION_FILE.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✅ 已写 {VERSION_FILE.name}：{doc['version_id']}（{len(files)} 文件，hash {vhash[:16]}…）")
    if doc["supersedes"]:
        print(f"   取代 {doc['supersedes']}")
    print("   下一步：把 version_id 记入 90-history/bkn-changelog.md（V-4 changeset 对账）")
    return 0


def cmd_check(quiet: bool = False) -> int:
    prev = read_version()
    if prev is None:
        print(f"✗ 版本文件缺失或不可解析：{VERSION_FILE}", file=sys.stderr)
        return 1
    recorded = prev.get("files") or {}
    actual = build_manifest()

    added = sorted(set(actual) - set(recorded))
    removed = sorted(set(recorded) - set(actual))
    changed = sorted(k for k in set(actual) & set(recorded) if actual[k] != recorded[k])

    if not (added or removed or changed):
        if not quiet:
            print(f"✓ 内容与版本清单一致：{prev.get('version_id')}"
                  f"（{len(actual)} 文件，hash {version_hash(actual)[:16]}…）")
        return 0

    print(f"✗ 内容与版本清单 **不一致**（当前版本 {prev.get('version_id')}）——I14", file=sys.stderr)
    for tag, items in (("新增", added), ("删除", removed), ("修改", changed)):
        for k in items:
            print(f"    {tag}: {k}", file=sys.stderr)
    print(f"  共 {len(added) + len(removed) + len(changed)} 个文件差异。"
          f"改了本体就必须升级版本：`python3 scripts/bkn_version.py --write`", file=sys.stderr)
    return 1


def cmd_diff(pa: str, pb: str) -> int:
    try:
        a = json.loads(Path(pa).read_text(encoding="utf-8"))
        b = json.loads(Path(pb).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"✗ 读版本文件失败：{exc}", file=sys.stderr)
        return 2
    fa, fb = a.get("files") or {}, b.get("files") or {}
    print(f"A = {a.get('version_id')}（{a.get('released_at')}）")
    print(f"B = {b.get('version_id')}（{b.get('released_at')}）\n")
    for tag, items in (("新增", sorted(set(fb) - set(fa))),
                       ("删除", sorted(set(fa) - set(fb))),
                       ("修改", sorted(k for k in set(fa) & set(fb) if fa[k] != fb[k]))):
        for k in items:
            print(f"  {tag}: {k}")
    if fa == fb:
        print("  两者内容完全相同")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="BKN 版本身份（27 号批 V-0）")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--write", action="store_true", help="生成/升级版本")
    g.add_argument("--check", action="store_true", help="校验内容与版本清单是否一致（I14）")
    g.add_argument("--show", action="store_true", help="打印当前版本身份")
    g.add_argument("--diff", nargs=2, metavar=("A", "B"), help="比对两份版本文件")
    ap.add_argument("--label", default="", help="--write 时的简短标签")
    ap.add_argument("--changeset", default="", help="--write 时指向 changelog 条目 / 号方案")
    ap.add_argument("--released-by", default="", help="--write 时的发布人（可选，Q20）")
    ns = ap.parse_args(argv)

    if ns.write:
        return cmd_write(ns.label, ns.changeset, ns.released_by)
    if ns.check:
        return cmd_check()
    if ns.diff:
        return cmd_diff(*ns.diff)
    prev = read_version()
    if prev is None:
        print(f"（无版本文件：{VERSION_FILE}）")
        return 0
    print(f"version_id  : {prev.get('version_id')}")
    print(f"version_hash: {prev.get('version_hash')}")
    print(f"released_at : {prev.get('released_at')}  by {prev.get('released_by') or '—'}")
    print(f"changeset   : {prev.get('changeset_ref') or '—'}")
    print(f"files       : {prev.get('file_count')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
