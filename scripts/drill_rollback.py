#!/usr/bin/env python3
"""drill_rollback.py — 回滚决策树演练（27 号批 V-3；分支① 定点恢复）

在**隔离副本**（默认 `/tmp/v3drill`）里完整走一遍：

  建副本 → 造一个"改错了"的候选 → 走待审区落盘（自动升版）→ 发现改错
  → 分支①：从该候选 `payload/.pre-apply/` 恢复文件 → 升一个新版本 → 门禁复验

**它不触碰生效内容**：副本是 `cp -a` 出来的独立树；副本里 `plugin/bkn` 会被改写成
指向副本自己的相对软链（源仓库里它是绝对软链，直接拷会指回真实 `bkn/`）。

用法:
  python3 scripts/drill_rollback.py            # 默认副本 /tmp/v3drill
  python3 scripts/drill_rollback.py --dest /tmp/other

预期结果：① 内容 sha256 精确回到改动前；② 门禁全绿；③ 版本号**前进**（不回写历史）。
注意步骤 4a 会**故意**让门禁 ③b 红一次——那是顺序规则（先升版再复验），不是失败。

依据: doc/optimize/27-ontology-versioning-release.md §3 批 V-3 / skill/bkn-release/references/rollback.md §6
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

SRC = Path(__file__).resolve().parent.parent
TARGET = "bkn/objects/host.bkn"      # 演练改动的文件（只加一个空行：零语义影响）
CID = "C-20261010-90"                # 演练候选 id


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Drill:
    def __init__(self, dest: Path):
        self.dest = dest

    def sh(self, cmd: list[str], check: bool = True) -> int:
        print(f"\n$ {' '.join(cmd)}")
        r = subprocess.run(cmd, cwd=str(self.dest), capture_output=True, text=True)
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        if out:
            print(out)
        if check and r.returncode != 0:
            print(f"!! 退出码 {r.returncode} —— 演练失败")
            sys.exit(1)
        return r.returncode

    def copy_tree(self) -> None:
        print(f"## 0. 建隔离副本\ncp -a {SRC} {self.dest}")
        if self.dest.exists():
            shutil.rmtree(self.dest)
        shutil.copytree(SRC, self.dest, symlinks=True,
                        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
        link = self.dest / "plugin" / "bkn"
        if link.is_symlink():
            link.unlink()
        link.symlink_to("../bkn")
        print("plugin/bkn → ../bkn（改为副本内相对软链，避免指回真实 bkn/）")

    def make_bad_candidate(self) -> tuple[Path, str]:
        cand = self.dest / "doc" / "optimize" / "pending" / CID
        payload_file = cand / "payload" / TARGET
        payload_file.parent.mkdir(parents=True, exist_ok=True)
        payload_file.write_bytes((self.dest / TARGET).read_bytes() + b"\n")
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        (cand / "candidate.json").write_text(json.dumps({
            "id": CID, "created_at": stamp, "created_by": "drill_rollback.py",
            "status": "pending", "target_dimension": "content", "landing": "四元",
            "hypothesis": "演练用：制造一次可回滚的内容变更（仅尾随空行，语义不变）",
            "evidence": [{"type": "机制演练", "ref": "scripts/drill_rollback.py",
                          "strength": "strong"}],
            "changes": [{"path": TARGET, "op": "append-blank-line", "summary": "演练用"}],
            "review": {"by": "drill_rollback.py", "at": stamp},
            "rollback": f"从 {CID}/payload/.pre-apply/{TARGET} 恢复",
            "risk": "无（隔离副本演练）",
        }, ensure_ascii=False, indent=1), encoding="utf-8")

        sys.path.insert(0, str(self.dest / "scripts"))
        import pending_apply as pa  # noqa: PLC0415

        copies, patches = pa.collect_payload(cand)
        phash = pa._payload_hash(copies + patches, cand / "payload")
        print(f"\npayload 文件数 = {len(copies)}；payload_hash = {phash[:16]}…")
        ledger = self.dest / "doc" / "optimize" / "pending" / "ledger.jsonl"
        with ledger.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "id": CID, "at": stamp, "decision": "approve",
                "by": "用户（V-3 演练）", "reason": "演练用：验证回滚决策树分支①（隔离副本）",
                "payload_hash": phash, "hash_method": "payload-relative-v2",
            }, ensure_ascii=False) + "\n")
        print("已追加账本 approve（含 payload_hash）")
        return cand, phash

    def run(self) -> int:
        self.copy_tree()
        before = sha(self.dest / TARGET)
        print(f"\n改动前 {TARGET} sha256 = {before[:16]}…")
        self.sh(["python3", "scripts/bkn_version.py", "--show"])

        print("\n## 1. 造一个『改错了』的候选（只加一个空行，零语义影响）")
        cand, _ = self.make_bad_candidate()

        print("\n## 2. 走待审区落盘（apply 是唯一生效路径；内部自动升版）")
        self.sh(["python3", "scripts/pending_apply.py", CID])
        applied = sha(self.dest / TARGET)
        print(f"\n改动后 sha256 = {applied[:16]}…（与改动前不同：{applied != before}）")
        print(f"候选 .pre-apply 备份存在：{(cand / 'payload' / '.pre-apply' / TARGET).exists()}")
        self.sh(["python3", "scripts/bkn_version.py", "--show"])

        print("\n## 3. 发现改错 —— 分支①：从候选 .pre-apply/ 定点恢复")
        print(f"$ cp -a doc/optimize/pending/{CID}/payload/.pre-apply/{TARGET} {TARGET}")
        shutil.copy2(cand / "payload" / ".pre-apply" / TARGET, self.dest / TARGET)
        restored = sha(self.dest / TARGET)
        print(f"恢复后 sha256 = {restored[:16]}…（== 改动前：{restored == before}）")

        print("\n## 4a. 先跑门禁会看到 ③b 红——**预期，不是失败**（顺序规则）")
        print("（I14 判「内容 ↔ 版本身份」：内容刚回退、版本还指着旧内容 → 必然红。"
              "正确顺序是「回滚 → 升版 → 复验」。）")
        self.sh(["bash", "scripts/gate.sh", "--fast"], check=False)

        print("\n## 4b. 升一个新版本（回滚 = 一次新发布，不覆盖历史）")
        self.sh(["python3", "scripts/bkn_version.py", "--write",
                 "--label", f"回滚 {CID} 的 {TARGET}（分支①）"])

        print("\n## 4c. 复验（此时应全绿）")
        rc = self.sh(["bash", "scripts/gate.sh", "--fast"])
        self.sh(["python3", "scripts/bkn_version.py", "--check"])

        print("\n## 结论")
        print(f"① 内容精确回到改动前：{restored == before}（sha256 {restored[:16]}…）")
        print(f"② 门禁复验退出码：{rc}")
        print("③ 版本号前进而非回写：")
        self.sh(["python3", "scripts/bkn_version.py", "--show"])
        ok = rc == 0 and restored == before
        print("\n" + ("✅ 演练通过（分支① 可用）" if ok else "❌ 演练未通过，需核对"))
        return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="回滚决策树演练（27 号批 V-3 分支①）")
    ap.add_argument("--dest", default="/tmp/v3drill", help="隔离副本目录（默认 /tmp/v3drill）")
    ns = ap.parse_args(argv)
    return Drill(Path(ns.dest).expanduser()).run()


if __name__ == "__main__":
    raise SystemExit(main())
