#!/usr/bin/env python3
"""check_loaded_version.py — 服务自证一致性检查（27 号 I16 / 批 V-1 × U-2）

回答两个问题：
  ① 此刻**服务进程**加载的是哪版（`logs/.loaded_version.json`）；
  ② 它与**磁盘**是否一致——三方比对（I16 的字面要求是「加载的 hash == 磁盘 hash」）：

     A. 进程加载（loaded.version_hash，自证时算出）
     B. 磁盘现状（**现在**对 loaded.bkn_root 重算 manifest → hash）
     C. 版本记录（仓库根 `bkn-version.json` 的 version_hash，即"已发布的是哪版"）

  判定：
     A == B            → 一致（进程加载的就是磁盘现状）；若 B != C 附注「内容未升版（I14）」提示；
     A != B            → 不一致：磁盘已改、进程未加载 → 重启服务进程（这才是"哪版生效"的主判据）；
     A == B 但记录陈旧 → 不判失败（I14 由 gate ③b 负责），只提示先 `bkn_version.py --write`。

退出码（供现场与脚本用）：
  0 = 一致；1 = 不一致（磁盘已改、进程未加载 → 重启）；2 = 无记录 / 文件缺失 / 自证降级。

**刻意不挂 `gate.sh`**：`.bkn` 一改、进程未重启时本检查必报 1，而 `pending_apply` 落盘后要跑
`gate.sh --fast` 复验 → 会自锁。现场自检与发布收尾手工跑（`skill/bkn-release/references/release-flow.md` 自检节）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = PLUGIN_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from plugin.loaded_version import LOADED_VERSION_FILE, _import_bkn_version  # noqa: E402


def _disk_content_hash(bkn_root: Path):
    """对**当下的** BKN 根重算清单 hash（复用版本算法单点）。失败返回 (None, 错误串)。"""
    try:
        bv = _import_bkn_version()
        if not bkn_root.is_dir():
            return None, f"BKN 根不存在：{bkn_root}"
        return bv.version_hash(bv.manifest_for(bkn_root, "bkn")), None
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"


def check(loaded_path: Path, version_file: Path, bkn_root: Path | None = None) -> int:
    if not version_file.is_file():
        print(f"✗ 磁盘身份文件不存在：{version_file}", file=sys.stderr)
        return 2
    disk = json.loads(version_file.read_text(encoding="utf-8"))
    disk_hash = str(disk.get("version_hash", ""))

    if not loaded_path.is_file():
        print(f"✗ 无服务自证记录：{loaded_path}", file=sys.stderr)
        print("  → 服务进程未跑过含「服务自证」的代码（重启服务进程后自动生成）", file=sys.stderr)
        return 2
    try:
        loaded = json.loads(loaded_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print(f"✗ 服务自证文件不是合法 JSON：{loaded_path}", file=sys.stderr)
        return 2

    if loaded.get("hash_error"):
        print(f"⚠ 自证时 hash 计算失败：{loaded['hash_error']}")
        return 2

    loaded_hash = str(loaded.get("version_hash") or "")
    root = bkn_root or Path(loaded.get("bkn_root") or (REPO_ROOT / "bkn"))
    current_hash, cur_err = _disk_content_hash(root)
    if cur_err:
        print(f"⚠ 无法重算磁盘内容 hash：{cur_err}")
        return 2

    head = (f"进程 {loaded.get('process')}｜加载于 {loaded.get('loaded_at')}"
            f"（trigger={loaded.get('trigger')}）｜BKN 根 {root}")
    if loaded_hash == current_hash:
        print(f"✅ 一致：进程加载 == 磁盘现状（hash {current_hash[:16]}…）")
        if disk_hash and disk_hash != current_hash:
            print(f"  ⚠ 附注：磁盘内容与版本记录不一致（I14）——先跑 "
                  f"scripts/bkn_version.py --write（本项不判失败）")
        print(f"  {head}")
        return 0

    print("✗ 不一致：磁盘已改、进程未加载（需重启服务进程）")
    print(f"  进程加载：hash {loaded_hash[:16]}…（version_id {loaded.get('version_id')}，"
          f"trigger {loaded.get('trigger')}）")
    print(f"  磁盘现状：hash {current_hash[:16]}…")
    print(f"  版本记录：{disk.get('version_id')}｜hash {disk_hash[:16]}…"
          f"（released_at {disk.get('released_at')}）")
    print(f"  {head}")
    return 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="服务自证一致性检查（I16）")
    ap.add_argument("--loaded", default=str(LOADED_VERSION_FILE),
                    help="服务自证文件路径（缺省 logs/.loaded_version.json）")
    ap.add_argument("--version-file", default=str(REPO_ROOT / "bkn-version.json"),
                    help="磁盘身份文件路径（缺省仓库根 bkn-version.json）")
    ap.add_argument("--bkn-root", default=None,
                    help="重算磁盘内容 hash 的 BKN 根（缺省取自证记录里的 bkn_root）")
    ns = ap.parse_args(argv)
    return check(Path(ns.loaded), Path(ns.version_file),
                 Path(ns.bkn_root) if ns.bkn_root else None)


if __name__ == "__main__":
    raise SystemExit(main())
