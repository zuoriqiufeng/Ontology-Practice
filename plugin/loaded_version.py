"""loaded_version.py — 服务自证：把「本进程实际加载的 BKN 身份」落成可读文件

27 号批 V-1 × 25 号批 U-2（同批实施，2026-10-12）：

- 写入时机：`register()`（Hermes 启动注册插件时）与每次 `reload()` 之后（`plugin/scripts/reload.py`）；
- 内容：进程标识 + 加载时间 + 触发方式 + 实际 BKN 根 + **版本号** + **版本 hash**
  （算法**单点**在 `scripts/bkn_version.py::manifest_for/version_hash`，与磁盘身份同算法，两处必须一致）；
- 检查：`plugin/scripts/check_loaded_version.py`（I16）回答「此刻跑的是哪版」「磁盘已改、进程未加载？」；
- **刻意不进 `gate.sh`**：`.bkn` 一改、进程未重启时该检查必然报不一致，而 `pending_apply` 落盘后要跑
  `gate.sh --fast` 复验 → 会自锁（理由同步写在 27 号 §7.1 与 `skill/bkn-release/references/release-flow.md`）；
- 全程 try/except：自证写不进去（只读盘/无权限）**不得**影响插件注册与主流程。
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .config import resolve_log_path

logger = logging.getLogger(__name__)

#: 服务自证文件（logs/ 域；与 bkn-version.json 的 version_hash 对照——见 check_loaded_version.py）
LOADED_VERSION_FILE = resolve_log_path(".loaded_version.json")


def _import_bkn_version():
    """按文件路径加载 `scripts/bkn_version.py`（版本算法单点，不复制实现）。

    用 `importlib.util` 而非 `sys.path` 注入：不污染全局导入路径，也不与工具区脚本的
    `__main__` 守卫冲突。
    """
    target = Path(__file__).resolve().parent.parent / "scripts" / "bkn_version.py"
    if not target.is_file():
        raise FileNotFoundError(f"未找到版本算法模块：{target}")
    spec = importlib.util.spec_from_file_location("bkn_version_for_attestation", target)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_prev_version(path: Path):
    """写前旧值（优先 version_id，回落 version_hash）；读不到/解析失败 → None（异常静默）。"""
    try:
        prev = json.loads(path.read_text(encoding="utf-8"))
        return prev.get("version_id") or prev.get("version_hash")
    except Exception:
        return None


#: 本进程已写过的 (from_version, to_version) 对 —— B6 的循环保护（见 _emit_reload_event）
_EMITTED_PAIRS: set = set()

#: 「本进程已观测过一次版本」守卫 —— 避免每次 Tool 调用都读盘 + 写自证（见 observe_loaded_version）
_OBSERVED = False
_OBSERVE_LOCK = threading.Lock()


def _emit_reload_event(from_version, record: dict, ms: int | None = None) -> None:
    """B6（44 号 §3.3 `bkn_reload`）：版本换掉了 → usage_log 一条**进程级**事件。

    载体选择照先例：进程级事件走 usage_log（`risk_guard._emit_assembly_event` 同款），
    不走 trajectory——后者要求 task_id（进程启动/热重载没有 task 可言）。
    **只新增条目类型**，既有条目形状一个字段都不动；失败静默（自证不得影响主流程）。

    **循环保护（本轮明确取舍）**：同一 `(from_version, to_version)` 对**在本进程内只写一条**。
    - 挡住的：重复 import / `register()` 与首次 Tool 入口各 attest 一次 / 同一版本反复装载
      —— 这些都不是「版本换掉了」，不该每次一条（防重入日志噪音）；
    - 放过的：版本再变 → 新对 → 照写（哪怕同一个长驻进程内热重载多次，每次都记）。
    取舍：**宁可同一版本每进程一条，也不漏掉「没人调 reload.py 的那种换版」**——
    27 号 I16 只能看到「当下」，看不到「什么时候换的」，而恰恰是没人主动 reload 时最需要它。
    """
    try:
        to_version = record.get("version_id") or record.get("version_hash")
        pair = (from_version, to_version)
        if pair in _EMITTED_PAIRS:
            return                      # 循环保护：同一 (from→to) 对本进程只写一条
        _EMITTED_PAIRS.add(pair)
        from .usage_log import log_usage
        rec_hash = record.get("record_hash") or record.get("version_hash") or ""
        log_usage("bkn_reload",
                  record_type="process",     # 44 号 §6 批 3：进程级事件（无 args/confidence）
                  from_version=from_version,
                  to_version=to_version,
                  record_hash=str(rec_hash)[:16],
                  trigger=record.get("trigger"),
                  changed=bool(from_version is not None and from_version != to_version),
                  ms=ms)
    except Exception:
        pass


def observe_loaded_version(trigger: str = "tool_entry") -> dict | None:
    """B6 **真接线**：本进程第一次进入 Tool 入口时观测一次「我加载的是哪版」。

    为什么是这里：`scripts/bkn_version.py --write` 是**独立进程**（只 import
    argparse/hashlib/json/sys/datetime/pathlib，不 import 插件），插件侧唯一能观测
    「版本被换掉」的时机，就是**本进程下一次真入口调用**。写法照先例
    `risk_guard._load_rules` → `_emit_assembly_event`（进程级事件、每进程一次、失败静默），
    由 `tools._timed_handler`（HANDLERS 每一项的入口）调用。

    取舍（loop 保护，与 `_emit_reload_event` 的 (from→to) 去重配套）：
    - 每进程最多读一次盘 + 写一次自证（`_OBSERVED` + 锁），不落在热路径上；
    - 真事件由 `_emit_reload_event` 按 (from_version, to_version) 去重，
      同一版本重复装载只写一条；版本变了才再写。
    """
    global _OBSERVED
    try:
        with _OBSERVE_LOCK:
            if _OBSERVED:
                return None
            _OBSERVED = True
    except Exception:
        return None
    return attest_loaded_version(trigger)


def reset_for_tests() -> None:
    """测试辅助：复位 B6 的两处**进程级**守卫（生产不调用）。

    与 `trajectory.reset_seq_for_tests` / `risk_guard.reset_rules_cache` 同法：
    `_OBSERVED` 与 `_EMITTED_PAIRS` 是进程级状态，测试要能复位后重放同一条真入口路径。
    """
    global _OBSERVED
    _EMITTED_PAIRS.clear()
    _OBSERVED = False


def attest_loaded_version(trigger: str, bkn_root: str | None = None) -> dict | None:
    """写 `logs/.loaded_version.json` 并返回记录；任何失败静默返回 None。

    `bkn_root` 缺省取 `plugin.config.BKN_ROOT`（部署可配）；测试可注入临时根。
    """
    try:
        from .config import BKN_ROOT
        root = Path(bkn_root or BKN_ROOT)
        record = {
            "process": os.getpid(),
            "loaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "trigger": trigger,
            "bkn_root": str(root),
            "version_id": None,
            "version_hash": None,
            "record_hash": None,
        }
        try:
            bv = _import_bkn_version()
            if not root.is_dir():
                raise FileNotFoundError(f"BKN 根不存在：{root}")
            record["version_hash"] = bv.version_hash(bv.manifest_for(root, "bkn"))
            rec_file = bv.VERSION_FILE
            if rec_file.is_file():
                rec = json.loads(rec_file.read_text(encoding="utf-8"))
                record["version_id"] = rec.get("version_id")
                record["record_hash"] = rec.get("version_hash")
        except Exception as e:  # noqa: BLE001 —— 自证失败不得影响主流程
            record["hash_error"] = f"{type(e).__name__}: {e}"[:200]
        path = LOADED_VERSION_FILE
        # B6：先取**写入前**的旧值，写完再发事件——「谁在什么时候把 BKN 版本换掉了」
        # 此前没有事件（27 号 I16 只看得到当下，看不出变化）。
        _prev_version = _read_prev_version(path)
        _t_write = time.perf_counter()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
        _emit_reload_event(_prev_version, record,
                           ms=int((time.perf_counter() - _t_write) * 1000))
        return record
    except Exception:
        logger.warning("服务自证写入失败（不影响主流程）", exc_info=True)
        return None
