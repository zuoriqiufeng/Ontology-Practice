#!/usr/bin/env python3
"""reload.py — 热重载 BKN 数据

清除 Plugin 内部缓存, 重新加载所有 .bkn 文件。

**作用域（2026-10-10 实测更正）**: 只重建**执行本脚本的那个进程**内的全局对象
（见 `reload()` 里的 `tools._resolver = ...`）。本脚本是短命进程，因此
**常驻服务进程不会因此刷新**——一次性新进程执行即生效，常驻服务以"重启服务进程"为准。
（复现与证据: `skill/bkn-release/references/release-flow.md` §3.2；服务自证见 27 号批 V-1）

v1.5 (P2-5): mtime 快照 + 变更清单
  - 每次 reload 记录各 .bkn 的 mtime/section 名快照到 plugin/.reload_state.json
  - 输出相对上次 reload 的变更：哪些文件变了、哪些 section 增删
  - 首次运行或无快照时全量加载并建立基线

推荐用法:
  cd <repo> && python -m plugin.scripts.reload
兼容用法 (直接执行脚本):
  cd <repo>/plugin && python3 scripts/reload.py
"""

import json
import sys
from pathlib import Path

# 将 plugin 包所在目录加入 path, 支持直接执行脚本和模块调用两种模式
_plugin_dir = str(Path(__file__).resolve().parent.parent)
_project_dir = str(Path(_plugin_dir).parent)
for _d in (_plugin_dir, _project_dir):
    if _d not in sys.path:
        sys.path.insert(0, _d)

STATE_FILE = Path(_project_dir) / "logs" / ".reload_state.json"


def _snapshot(resolver) -> dict:
    """{rel_path: {"mtime": float, "sections": [section_name, ...]}}"""
    snap = {}
    for rel, data in resolver.cache.items():
        path = resolver.root / rel
        mtime = path.stat().st_mtime if path.exists() else 0
        snap[rel] = {
            "mtime": mtime,
            "sections": sorted(k for k in data if k != "_head"),
        }
    return snap


def _diff(old: dict, new: dict) -> list[str]:
    """对比新旧快照，输出人类可读变更清单"""
    changes = []
    for rel in sorted(set(old) | set(new)):
        if rel not in old:
            changes.append(f"[新增文件] {rel} ({len(new[rel]['sections'])} sections)")
            continue
        if rel not in new:
            changes.append(f"[删除文件] {rel}")
            continue
        if old[rel]["mtime"] == new[rel]["mtime"]:
            continue  # 未变
        old_secs = set(old[rel]["sections"])
        new_secs = set(new[rel]["sections"])
        added = new_secs - old_secs
        removed = old_secs - new_secs
        parts = []
        if added:
            parts.append(f"新增 section: {', '.join(sorted(added))}")
        if removed:
            parts.append(f"删除 section: {', '.join(sorted(removed))}")
        if not parts:
            parts.append("内容修改（section 结构不变）")
        changes.append(f"[变更] {rel}: {'; '.join(parts)}")
    return changes


def _reset_bm25(collection: str = None):
    """--with-bm25: 重置 BM25 索引（下次搜索时自动重建）。

    v1.7: 无参时重置注册表中的全部集合；带集合名时只重置该集合。
    """
    from plugin import bm25
    from plugin.config import QDRANT_COLLECTIONS
    if collection and collection not in QDRANT_COLLECTIONS:
        print(f"未知集合: {collection}，已注册集合: {', '.join(QDRANT_COLLECTIONS)}")
        return
    reset = bm25.reset_bm25(collection)
    for name in reset:
        desc = QDRANT_COLLECTIONS.get(name, "")
        print(f"BM25 索引已重置: {name}（{desc}）— 下次搜索时自动重建")


def _bm25_hint():
    return ("提示: BKN 内容有变更；若已重新向量化导入 Qdrant，"
            "建议运行 reload --with-bm25 重建稀疏索引")


def reload():
    """重新初始化全局实例"""
    from plugin.resolver import BKNResolver
    from plugin.relations import RelationTraverser
    from plugin.context_loader import ContextLoader
    from plugin import tools

    # 读取上次快照
    old_snap = {}
    if STATE_FILE.exists():
        try:
            old_snap = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            old_snap = {}

    tools._resolver = BKNResolver()
    tools._traverser = RelationTraverser()
    tools._loader = ContextLoader()

    new_snap = _snapshot(tools._resolver)

    print("BKN 数据已重新加载")
    ops = tools._resolver.list_operations()
    print(f"已加载 {len(ops)} 个操作: {', '.join(ops[:5])}...")

    # 变更清单
    if not old_snap:
        print(f"变更清单: 首次运行，已建立基线（{len(new_snap)} 个文件）")
    else:
        changes = _diff(old_snap, new_snap)
        if changes:
            print(f"变更清单（相对上次 reload，共 {len(changes)} 项）:")
            for c in changes:
                print(f"  {c}")
            print(_bm25_hint())
        else:
            print("变更清单: 无变化")

    STATE_FILE.write_text(
        json.dumps(new_snap, ensure_ascii=False, indent=1), encoding="utf-8")

    # 批 V-1 × U-2（2026-10-12）：服务自证（trigger=reload）。
    # 作用域同上——只证明"执行本脚本的这个进程"加载了什么；常驻服务以重启为准。
    try:
        from plugin.loaded_version import attest_loaded_version
        attest_loaded_version("reload")
    except Exception:
        print("  ⚠ 服务自证写入失败（不影响重载结果）")
    print("提示: 本命令只对**执行它的这个进程**有效；常驻服务进程以重启为准"
          "（自证与检查见 logs/.loaded_version.json / plugin/scripts/check_loaded_version.py）")


def _watch():
    """P3-3: watch 模式——监听 bkn/ 目录变化自动热重载（防抖 0.5s）"""
    try:
        from watchfiles import watch
    except ImportError:
        print("watch 模式不可用: watchfiles 未安装")
        sys.exit(1)

    bkn_root = Path(_project_dir) / "bkn"
    print(f"watch 模式启动，监听 {bkn_root}（Ctrl+C 退出）")
    reload()  # 启动即全量一次
    import time as _time
    last = 0.0
    for changes in watch(bkn_root, recursive=True):
        now = _time.time()
        if now - last < 0.5:  # 防抖：批量变化合并
            continue
        last = now
        print(f"\n检测到 {len(changes)} 个文件变化，重新加载...")
        reload()


if __name__ == "__main__":
    if "--watch" in sys.argv:
        _watch()
    else:
        reload()
        if "--with-bm25" in sys.argv:
            # --with-bm25 [collection]: 无参重置全部注册集合，带参只重置指定集合
            idx = sys.argv.index("--with-bm25")
            target = None
            if idx + 1 < len(sys.argv) and not sys.argv[idx + 1].startswith("--"):
                target = sys.argv[idx + 1]
            _reset_bm25(target)
