#!/usr/bin/env python3
"""pending_apply.py — 应用一条已批准的候选（28 号批 R-2）

**apply 是唯一能改生效位置的路径**（28 号 §3）。顺序：
  ① 校验候选存在、`status == pending`（I22：未审批的候选不可生效）
  ② 校验账本存在对应 `approve` 记录且 `by` / `reason` 非空（I23）
  ③ 校验 payload hash 与账本记录一致 —— 保证「审批对象 == 生效内容」
     （候选声明的 `removals` 非空时并入哈希：**"删了什么"也是审批对象**）
  ③b 校验 `removals`（移动/删除的旧位置）：白名单、存在、**sha256 与现场一致**——
      不一致 = 候选构造后现场已变（候选过期）→ 拒绝，而不是照删
  ④ 干跑（--dry-run）或落盘：把 `payload/` 复制到生效位置 + 执行 `removals` 删除
  ⑤ 落盘后跑 `scripts/gate.sh` 复验；失败即回滚（从 `payload/.pre-apply/` 还原，含被删文件）
  ⑥ 更新 candidate.json 的 status → applied；由 27 号生成版本号并回写 ledger
      （本脚本只提示，不代生成版本号 —— 版本号归属 27 号批 V-0）

用法:
  python3 scripts/pending_apply.py C-20261010-01 --dry-run   # 只看会改什么
  python3 scripts/pending_apply.py C-20261010-01             # 真正落盘 + 复验
  python3 scripts/pending_apply.py C-20261010-01 --no-gate   # 跳过复验（不推荐）

payload/ 布局约定（28 号 §2）：
  payload/<生效位置的相对路径>          BKN 类（整文件副本）
  payload/patch/*.patch                代码类（git apply 用）
  candidate.json 的 `removals`         移动/删除的**旧位置**（`{path, sha256}`，2026-10-11 起）——
                                       移动 = 副本落新路径（payload）+ 本条删旧路径

退出码：0 成功；1 校验失败或复验失败已回滚；2 参数/环境错误

依据: doc/optimize/28-pending-review-loop.md §2.3 / §3
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PENDING_DIR = REPO_ROOT / "doc" / "optimize" / "pending"

#: 允许被 payload 覆盖的生效位置前缀（白名单——防止候选写到奇怪的地方）
ALLOWED_PREFIXES = ("bkn/", "plugin/", "skill/", "doc/update/")

#: 落盘前的原件备份目录名（在 `payload/` 下）。**它不是候选内容**——见 `_is_payload_file`
PRE_APPLY_DIRNAME = ".pre-apply"


def _anchor_prefix() -> str:
    """版本锚行前缀：**单点定义在 `changeset.py`**（27 号批 V-4 的约定），此处只取用——
    函数内延迟导入，避免两个脚本在导入期互相牵连。"""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from changeset import ANCHOR_PREFIX  # noqa: PLC0415

    return ANCHOR_PREFIX


def _ledger_entries() -> list[dict]:
    ledger = PENDING_DIR / "ledger.jsonl"
    if not ledger.exists():
        return []
    out = []
    for line in ledger.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _payload_hash(files: list[Path], base: Path, removals: list[dict] | None = None) -> str:
    """payload 内容指纹：以 **payload 目录的相对路径**为键，逐个喂 (相对路径, sha256)。

    ⚠ 必须用相对路径：早期版本直接喂 `str(f)`（绝对路径），导致同一份 payload
    从不同 cwd/调用方式算出的哈希不同——审批人写进账本的哈希与 apply 时算出的对不上，
    `pending_apply` 会（正确地）拒绝落盘。哈希必须只取决于**内容与相对结构**。

    `removals`（移动/删除的旧位置，2026-10-11 起）：**非空时**把规范化的
    (path, sha256) 并入哈希——"删了什么"也是审批对象的一部分。
    空/缺省与旧行为逐字节一致（既有候选的账本哈希不受影响）。
    """
    h = hashlib.sha256()
    for f in sorted(files, key=lambda p: str(p.relative_to(base))):
        h.update(str(f.relative_to(base)).encode("utf-8"))
        h.update(_sha256(f).encode("utf-8"))
    for item in sorted(removals or [], key=lambda r: str(r.get("path", ""))):
        h.update(b"removal:")
        h.update(str(item.get("path", "")).encode("utf-8"))
        h.update(str(item.get("sha256", "")).encode("utf-8"))
    return h.hexdigest()


def collect_removals(cand: dict) -> list[dict]:
    """候选声明的「移动/删除的旧位置」：`removals: [{path, sha256}]`（2026-10-11 起）。

    移动 = payload 复制到新路径 + removals 删旧路径。**sha256 必填**：删除前与现场
    比对，不一致 = 候选构造后现场已变（候选过期）→ 拒绝（而不是照删）。
    """
    out: list[dict] = []
    for item in cand.get("removals") or []:
        if isinstance(item, str):  # 宽松形态：只给路径（apply 时因缺 sha256 被拒）
            item = {"path": item}
        if not isinstance(item, dict) or not str(item.get("path", "")).strip():
            raise ValueError(f"removals 条目非法（应为 {{path, sha256}}）：{item!r}")
        rel = str(item["path"]).strip()
        while rel.startswith("./"):
            rel = rel[2:]
        out.append({"path": rel, "sha256": str(item.get("sha256", "")).strip().lower()})
    paths = [r["path"] for r in out]
    if len(set(paths)) != len(paths):
        raise ValueError("removals 有重复路径")
    return out


def collect_payload(cand_dir: Path) -> tuple[list[Path], list[Path]]:
    """返回 (可直接复制的文件列表, patch 文件列表)。

    跳过 `__pycache__` / `*.pyc`——它们不是候选内容（生成物），复制过去无意义且会污染生效树。
    """
    payload = cand_dir / "payload"
    if not payload.is_dir():
        return [], []
    patches = sorted((payload / "patch").glob("*.patch")) if (payload / "patch").is_dir() else []

    def _is_payload_file(p: Path) -> bool:
        parts = p.relative_to(payload).parts
        # `.pre-apply` 是本脚本自己写的**落盘前备份**，不是候选内容：必须排除。
        # 曾漏排除——落盘（或回滚）过的候选再被 apply 时，payload 文件数翻倍、
        # 算出的 hash 与账本对不上 → 被"正确地"拒绝，但报错会误导成"审批哈希写错了"。
        if "patch" in parts or "__pycache__" in parts or PRE_APPLY_DIRNAME in parts:
            return False
        return p.suffix != ".pyc"

    copies = [p for p in payload.rglob("*") if p.is_file() and _is_payload_file(p)]
    return copies, patches


def main(argv=None) -> int:
    global PENDING_DIR
    ap = argparse.ArgumentParser(description="应用一条已批准的候选（28 号批 R-2）")
    ap.add_argument("candidate_id", help="候选 id，如 C-20261010-01")
    ap.add_argument("--dry-run", action="store_true", help="只列出会改什么，不落盘")
    ap.add_argument("--no-gate", action="store_true", help="落盘后跳过 gate.sh 复验（不推荐）")
    ap.add_argument("--pending-dir", default=None, help="覆盖待审区目录（演练用）")
    ns = ap.parse_args(argv)
    if ns.pending_dir:
        PENDING_DIR = Path(ns.pending_dir).expanduser().resolve()

    cid = ns.candidate_id
    cand_dir = PENDING_DIR / cid
    cpath = cand_dir / "candidate.json"
    if not cpath.exists():
        print(f"✗ 候选不存在：{cpath}", file=sys.stderr)
        return 2
    cand = json.loads(cpath.read_text(encoding="utf-8"))

    # ① status 必须是 pending
    if cand.get("status") != "pending":
        print(f"✗ status={cand.get('status')!r}，只有 pending 可被 apply（I22）", file=sys.stderr)
        return 1

    # ② 账本须有 approve 记录
    entries = _ledger_entries()
    approves = [e for e in entries if e.get("id") == cid and e.get("decision") == "approve"]
    if not approves:
        print(f"✗ 账本中没有 {cid} 的 approve 记录 —— 未审批不得生效（28 号 §3 ④）", file=sys.stderr)
        return 1
    latest = sorted(approves, key=lambda e: str(e.get("at", "")))[-1]

    # ③ payload 与 hash（`removals` 非空时并入哈希——"删了什么"也是审批对象）
    copies, patches = collect_payload(cand_dir)
    try:
        removals = collect_removals(cand)
    except ValueError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    if not copies and not patches and not removals:
        print("✗ payload/ 为空且无 removals（BKN 类应为整文件副本；代码类应为 patch/*.patch）", file=sys.stderr)
        return 1
    actual_hash = _payload_hash(copies + patches, cand_dir / "payload", removals)
    recorded = str(latest.get("payload_hash", "")).strip()
    if recorded and recorded != actual_hash:
        print("✗ payload hash 与账本记录不符 —— 审批对象与生效内容不一致，拒绝 apply：", file=sys.stderr)
        print(f"   账本 {recorded}\n   实际 {actual_hash}", file=sys.stderr)
        return 1
    if not recorded:
        print("⚠ 账本 approve 记录无 payload_hash（旧格式）—— 无法证明「审批对象==生效内容」，仅本次放行")

    # ④ 越界检查
    targets: list[tuple[Path, Path]] = []
    for f in copies:
        rel = f.relative_to(cand_dir / "payload")
        if not str(rel).startswith(ALLOWED_PREFIXES):
            print(f"✗ 目标越界（不在白名单 {ALLOWED_PREFIXES}）：{rel}", file=sys.stderr)
            return 1
        targets.append((f, REPO_ROOT / rel))
    for p in patches:
        print(f"  代码类 patch（需人工 git apply）：{p.relative_to(cand_dir)}")

    # ④b removals 校验（移动/删除的旧位置）：白名单 / 与 payload 不同路径 / 存在 / sha256 一致
    payload_rels = {str(f.relative_to(cand_dir / "payload")) for f in copies}
    removal_targets: list[tuple[dict, Path]] = []
    for rm in removals:
        rel = rm["path"]
        if not rel.startswith(ALLOWED_PREFIXES):
            print(f"✗ removals 越界（不在白名单 {ALLOWED_PREFIXES}）：{rel}", file=sys.stderr)
            return 1
        if rel in payload_rels:
            print(f"✗ removals 与 payload 同路径（既覆盖又删除，自相矛盾）：{rel}", file=sys.stderr)
            return 1
        dst = REPO_ROOT / rel
        if not dst.is_file():
            print(f"✗ removals 目标不存在：{rel}", file=sys.stderr)
            return 1
        if not rm["sha256"]:
            print(f"✗ removals 缺 sha256（拒绝无校验删除）：{rel}", file=sys.stderr)
            return 1
        got = _sha256(dst)
        if got != rm["sha256"]:
            print(f"✗ removals 目标已变（候选过期）：{rel}", file=sys.stderr)
            print(f"   声明 {rm['sha256'][:16]}… / 现场 {got[:16]}…", file=sys.stderr)
            return 1
        removal_targets.append((rm, dst))

    print(f"候选 {cid}｜落点 {cand.get('landing')}｜维度 {cand.get('target_dimension')}")
    print(f"账本 approve：by={latest.get('by')!r}｜reason={str(latest.get('reason'))[:60]!r}")
    print(f"将写入 {len(targets)} 个文件：")
    for src, dst in targets:
        exists = "（覆盖现有）" if dst.exists() else "（新增）"
        print(f"  {dst.relative_to(REPO_ROOT)} {exists}")
    if removal_targets:
        print(f"将删除 {len(removal_targets)} 个文件（移动/退役的旧位置；sha256 已校验）：")
        for rm, dst in removal_targets:
            print(f"  {dst.relative_to(REPO_ROOT)}")
    if patches:
        print(f"另有 {len(patches)} 个 patch 需人工 git apply（本脚本不自动打补丁）")

    if ns.dry_run:
        print("\n（--dry-run：未落盘）")
        return 0

    # ⑤ 落盘（先备份，失败即回滚）
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = cand_dir / "payload" / ".pre-apply"
    restore: list[tuple[Path, Path | None]] = []
    try:
        for src, dst in targets:
            backup_dir.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                b = backup_dir / dst.relative_to(REPO_ROOT)
                b.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dst, b)
                restore.append((dst, b))
            else:
                restore.append((dst, None))
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        # removals：先备份再删（回滚时从备份还原——被删文件必须可逆）
        for rm, dst in removal_targets:
            b = backup_dir / dst.relative_to(REPO_ROOT)
            b.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dst, b)
            restore.append((dst, b))
            dst.unlink()
    except Exception as exc:
        print(f"✗ 落盘失败，开始回滚：{exc}", file=sys.stderr)
        for dst, b in reversed(restore):
            if b is None:
                dst.unlink(missing_ok=True)
            else:
                shutil.copy2(b, dst)
        return 1

    # ⑥ 生成版本身份（27 号 §2.4：版本号只在候选 applied 之后产生）
    #    —— apply 本身就是"发布新版本"的动作；`bkn_version.py --write` 幂等（内容未变则不动），
    #    故对不改 `.bkn` 的候选是 no-op。**必须在跑 gate 之前做**：否则 I14（版本与内容一致）
    #    会让任何改 `.bkn` 的候选在复验时被判不一致 → 回滚，导致这类候选永远 apply 不了。
    version_file = REPO_ROOT / "bkn-version.json"
    version_backup: str | None = None
    version_before = ""
    if version_file.is_file():
        version_backup = version_file.read_text(encoding="utf-8")
        try:
            version_before = str(json.loads(version_backup).get("version_id", ""))
        except json.JSONDecodeError:
            version_before = ""
        # 留下**上一版清单**（27 号批 V-4）：否则 apply 之后无法离线回答
        # "这一版改了哪几个文件"——`changeset.py --show` 靠它与候选 payload 对比
        # 得出 新增/修改 分类。它与 payload 同级但在 `.pre-apply/` 下，不算候选内容。
        v_prev = cand_dir / "payload" / PRE_APPLY_DIRNAME / "bkn-version.json"
        v_prev.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(version_file, v_prev)
    if (REPO_ROOT / "scripts" / "bkn_version.py").is_file():
        rc_v = subprocess.run(
            [sys.executable, "scripts/bkn_version.py", "--write",
             "--changeset", f"候选人 {cid}"],
            cwd=str(REPO_ROOT), capture_output=True, text=True)
        print("\n版本身份（27 号 V-0）：" + (rc_v.stdout.strip().splitlines() or [""])[0])
        if rc_v.returncode != 0:
            print(f"✗ 版本生成失败，回滚：{rc_v.stderr[:200]}", file=sys.stderr)
            for dst, b in reversed(restore):
                if b is None:
                    dst.unlink(missing_ok=True)
                else:
                    shutil.copy2(b, dst)
            if version_backup is not None:
                version_file.write_text(version_backup, encoding="utf-8")
            return 1

    # ⑦ 复验 + 记录门禁结果（28 号 §2.1：gates 落在 candidate.json）
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    gate_rc: int | None = None
    if not ns.no_gate:
        print("\n复验：bash scripts/gate.sh --fast")
        gate_rc = subprocess.run(["bash", "scripts/gate.sh", "--fast"], cwd=str(REPO_ROOT)).returncode
        if gate_rc != 0:
            print(f"\n✗ 复验失败（gate.sh 退出码 {gate_rc}），回滚：", file=sys.stderr)
            for dst, b in reversed(restore):
                if b is None:
                    dst.unlink(missing_ok=True)
                else:
                    shutil.copy2(b, dst)
            # 版本文件也回滚——否则它会描述已被撤销的内容（I14 立刻红）
            if version_backup is not None:
                version_file.write_text(version_backup, encoding="utf-8")
                print("  已回滚 bkn-version.json", file=sys.stderr)
            print("  已回滚到落盘前状态；候选保持 pending", file=sys.stderr)
            return 1

    gates = cand.setdefault("gates", {})
    gate_detail = (f"apply 时 gate.sh --fast（lint+pytest+图结构量）退出码 {gate_rc}"
                   if gate_rc is not None else "apply 时 --no-gate，未复验（不推荐）")
    for gk in ("structure", "regression"):
        prev = gates.get(gk) or {}
        gates[gk] = {
            "passed": (gate_rc == 0) if gate_rc is not None else bool(prev.get("passed")),
            "detail": gate_detail,
            "checked_at": stamp,
        }
    # evidence 门由人/产出方在提交审批前落定，apply 不覆盖（它判的是"内容为真"，不是"不劣化"）

    # ⑦ 标记 applied + 回写版本（27 号批 V-4：版本号 → candidate.json 与账本，形成
    #    「候选 → 版本 → changelog 锚行」的可对账链；账本只增不改，故追加 apply 事件）
    applied_version = ""
    try:
        applied_version = str(json.loads(version_file.read_text(encoding="utf-8"))
                              .get("version_id", ""))
    except (OSError, json.JSONDecodeError):
        pass
    # 版本号只在**本体内容**（`bkn/**`）变化时前进；Skill/Plugin 类候选落盘后版本不变——
    # 那种情况下"生效于版本 X"仍为真（当时本体就是 X），但要显式标出"未变"，
    # 免得被读成"本候选属于 X 的内容"（对账时不必去找新的 changelog 锚行）。
    version_changed = bool(applied_version) and applied_version != version_before

    cand["status"] = "applied"
    cand["applied_at"] = stamp
    if applied_version:
        cand["applied_version"] = applied_version
        cand["version_changed"] = version_changed
    cpath.write_text(json.dumps(cand, ensure_ascii=False, indent=1), encoding="utf-8")

    if applied_version:
        event = {
            "id": cid, "at": stamp, "decision": "apply", "by": "pending_apply.py",
            "reason": (f"落盘生效于 {applied_version}"
                       + ("" if version_changed else "（本体版本未变：本次无 .bkn 变更）")
                       + (f"；删除/移动 {len(removals)} 个旧位置" if removals else "")),
            "version_id": applied_version,
            "version_changed": version_changed,
        }
        if removals:
            event["removals"] = [r["path"] for r in removals]
        with (PENDING_DIR / "ledger.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")

    print(f"\n✅ 已落盘并标记 applied（{stamp}）")
    if applied_version:
        print(f"   版本 {applied_version} 已回写 candidate.json 与 ledger（只增不改）"
              + ("" if version_changed else "；**本体版本未变**（本次无 `.bkn` 变更）"))
        if version_changed:
            print(f"   发布收尾：把版本锚行写进 changelog —— {_anchor_prefix()}{applied_version}"
                  f"，再跑 python3 scripts/changeset.py --check --strict")
    print("   另：若本次解决了缺口，执行 plugin/scripts/mark_gaps_resolved.py（22 号 I6）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
