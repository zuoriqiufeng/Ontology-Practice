#!/usr/bin/env python3
"""sync_audit.py — 外面（生效树）↔ 待审区 payload 的对账机检（2026-10-12）

**不变量**（28 号 §1 铁律 3「apply 是唯一能改生效位置的路径」的机械形式）：
对任一被候选触及过的文件，其**当前内容**必须等于「**最后一次落盘它的那个候选**」的 payload 副本
（整文件副本口径）；被 `removals` 删除的文件必须确实不存在。

**回答的问题**：外面与待审区「同步没有」——逐文件指出**最后落盘者**（候选 + 版本），
并检出「绕过候选的直接改动」（payload 覆盖过的文件被手改 / 已删文件又重新出现）。

**范围**：只覆盖**候选曾触及的文件**（payload ∪ removals）。从不经候选的文件
（`doc/**` 工作文档、`scripts/**` 工具、`logs/**`、台账与记忆等）不在对账范围——它们按各自纪律直改。
另：apply 后 payload **不再**是外面的镜像（后来的批次会继续改同一文件）——
所以对账看的是「最后落盘者」，不是「每个 payload 都等于外面」。

用法:
  python3 scripts/sync_audit.py                 # 对账（0 一致 / 1 有漂移）
  python3 scripts/sync_audit.py --verbose       # 逐文件列出「最后落盘者」
  python3 scripts/sync_audit.py --pending-dir X --root Y   # 演练/测试

退出码：0 一致；1 检出漂移；2 环境错误

依据: doc/optimize/28-pending-review-loop.md §1/§2；README 的「payload 与外面的关系」节
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))
import pending_apply as pa  # noqa: E402 —— 单点复用 payload 语义（整文件副本；排除 .pre-apply/__pycache__/*.pyc）


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _ledger(pending_dir: Path) -> list[dict]:
    ledger = pending_dir / "ledger.jsonl"
    out: list[dict] = []
    if not ledger.exists():
        return out
    for line in ledger.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def last_touch(pending_dir: Path, ledger: list[dict]) -> dict:
    """{相对路径: (候选 id, 版本, 类型)}——按 apply 事件的时间顺序推进，后落盘者覆盖前落盘者。"""
    applies = sorted((e for e in ledger if e.get("decision") == "apply"),
                     key=lambda e: str(e.get("at", "")))
    touched: dict = {}
    for e in applies:
        cid = str(e.get("id", ""))
        cand = pending_dir / cid
        cpath = cand / "candidate.json"
        if not cpath.exists():
            continue
        try:
            cand_json = json.loads(cpath.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            cand_json = {}
        files, _ = pa.collect_payload(cand)
        for f in files:
            rel = str(f.relative_to(cand / "payload"))
            touched[rel] = (cid, str(e.get("version_id", "")), "payload")
        for rm in cand_json.get("removals") or []:
            rel = str((rm or {}).get("path", "")).strip()
            if rel:
                touched[rel] = (cid, str(e.get("version_id", "")), "removal")
    return touched


def audit(root: Path, pending_dir: Path) -> dict:
    """对账：返回 {covered, rows, problems}。`rows` 为一致项（供 --verbose）。"""
    touched = last_touch(pending_dir, _ledger(pending_dir))
    rows: list[tuple] = []
    problems: list[str] = []
    for rel, (cid, ver, kind) in sorted(touched.items()):
        live = root / rel
        if kind == "removal":
            if live.exists():
                problems.append(f"{rel}: 已由 {cid} 删除，但现在又在外面出现（绕过候选的直接创建？）")
            else:
                rows.append((rel, cid, ver, "removed"))
            continue
        src = pending_dir / cid / "payload" / rel
        if not src.exists():
            continue  # 极端情况：payload 文件后来被人工清理——跳过而非误报
        if not live.exists():
            problems.append(f"{rel}: {cid} 落盘过，但现在外面不存在")
        elif _sha256(live) != _sha256(src):
            problems.append(f"{rel}: 内容与最后落盘者 {cid} 的 payload 不一致（绕过候选的直接改动？）")
        else:
            rows.append((rel, cid, ver, "ok"))
    return {"covered": len(touched), "rows": rows, "problems": problems}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="外面 ↔ 待审区 payload 对账机检")
    ap.add_argument("--root", default=str(SCRIPTS_DIR.parent), help="生效树根（默认仓库根）")
    ap.add_argument("--pending-dir", default=None, help="待审区目录（默认 <root>/doc/optimize/pending）")
    ap.add_argument("--verbose", action="store_true", help="逐文件列出「最后落盘者」")
    ns = ap.parse_args(argv)
    root = Path(ns.root).resolve()
    pending = (Path(ns.pending_dir).expanduser().resolve() if ns.pending_dir
               else root / "doc" / "optimize" / "pending")
    if not pending.is_dir():
        print(f"✗ 待审区不存在：{pending}", file=sys.stderr)
        return 2
    data = audit(root, pending)
    if ns.verbose:
        for rel, cid, ver, state in data["rows"]:
            tail = f"  ← {cid}" + (f"（{ver}）" if ver else "")
            print(f"  {rel}  [{state}]{tail}")
    print(f"对账：候选触及文件 {data['covered']} 个｜漂移 {len(data['problems'])} 处")
    for p in data["problems"]:
        print(f"  ✗ {p}")
    if data["problems"]:
        print("（外面与待审区**不同步**：候选曾触及的文件被绕过候选改动过）")
        return 1
    print("✅ 一致：候选触及的每个文件 == 最后一次落盘它的候选的 payload；被删文件均不存在")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
