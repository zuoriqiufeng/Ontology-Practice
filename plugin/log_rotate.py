"""log_rotate.py — JSONL 日志轮转（日期 + 大小双维，21 号 2A 后扩展）

命名规则（2026-09-30 起）：
  <stem>_YYYY-MM-DD<suffix>            当日数据文件，如 usage_log_2026-09-30.jsonl
  <stem>_YYYY-MM-DD<suffix>.N          同日超大小轮转分片，.1/.2/.3（N 数字，最旧删除）
  跨日写入自动开新文件（文件名即日期）。历史旧命名（<base> 与 <base>.N）由
  iter_data_files / load_jsonl_entries 兼容读取（.bak 等非数字后缀不参与统计）。

线程安全: 模块级锁（批量模式 ThreadPoolExecutor 并发写时防竞争）
容错: 轮转/清理失败静默（与写入方现有容错一致，不影响主流程）
"""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timedelta
from pathlib import Path

_lock = threading.Lock()

# 从文件名提取日期：usage_log_2026-09-30.jsonl.1 → "2026-09-30"
# （用 [0-9] 而非 \d——test_bkn_boundary 禁止 plugin 内正则简写类）
_DATE_IN_NAME_RE = re.compile(r"_([0-9]{4}-[0-9]{2}-[0-9]{2})\.jsonl")


def rotate_if_needed(path: Path, max_bytes: int, backups: int = 3) -> bool:
    """若 path 超过 max_bytes，执行轮转。返回是否发生了轮转。

    轮转: xxx.jsonl → xxx.jsonl.1（原 .1 → .2，依此类推，最旧删除）。
    纯大小轮转（不感知日期）；日期维度见 rotate_day_file。
    """
    try:
        if not path.exists():
            return False
        if path.stat().st_size < max_bytes:
            return False
        with _lock:
            # double-check（持锁后另一线程可能已轮转）
            if not path.exists() or path.stat().st_size < max_bytes:
                return False
            # 最旧的先删，再逐级后移
            oldest = path.with_name(f"{path.name}.{backups}")
            if oldest.exists():
                oldest.unlink()
            for i in range(backups - 1, 0, -1):
                src = path.with_name(f"{path.name}.{i}")
                if src.exists():
                    src.rename(path.with_name(f"{path.name}.{i + 1}"))
            path.rename(path.with_name(f"{path.name}.1"))
        return True
    except Exception:
        return False


def day_file_path(base: Path, date: str | None = None) -> Path:
    """逻辑路径 → 当日数据文件：logs/usage_log.jsonl → logs/usage_log_2026-09-30.jsonl"""
    d = date or datetime.now().strftime("%Y-%m-%d")
    return base.with_name(f"{base.stem}_{d}{base.suffix}")


def rotate_day_file(base: Path, max_bytes: int, backups: int = 3,
                    retention_days: int = 0, now: datetime | None = None) -> Path:
    """日期 + 大小双维轮转。返回**当日应写入的文件路径**（写入方对返回值追加写）。

    - 文件名含日期（day_file_path），跨日自动开新文件；
    - 同日超 max_bytes → 数字后缀分片 .1/.2/...（复用 rotate_if_needed 换名梯队）；
    - retention_days > 0 时清理超期旧日文件（含其数字分片）；0 = 永久保留；
    - now 可注入（测试跨日/清理逻辑用）。
    """
    now = now or datetime.now()
    path = day_file_path(base, now.strftime("%Y-%m-%d"))
    rotate_if_needed(path, max_bytes, backups)
    if retention_days > 0:
        _prune_old_days(base, retention_days, now)
    return path


def _prune_old_days(base: Path, retention_days: int, now: datetime) -> None:
    """删除日期早于保留期的日文件及其数字分片（容错静默）。"""
    try:
        cutoff = (now - timedelta(days=retention_days)).strftime("%Y-%m-%d")
        for f in base.parent.glob(f"{base.stem}_*.jsonl*"):
            m = _DATE_IN_NAME_RE.search(f.name)
            if m and m.group(1) < cutoff:
                f.unlink(missing_ok=True)
    except Exception:
        pass


def iter_data_files(base: Path) -> list[Path]:
    """枚举某逻辑路径下的全部数据文件（新旧命名兼容，按文件名排序）。

    旧命名: <base> 本体 + <base>.N（N 为数字；.bak 等非数字后缀排除，如 .pre-observation.bak）
    新命名: <stem>_YYYY-MM-DD<suffix> 及其 .N 数字分片
    """
    files: set[Path] = set()
    if base.exists():
        files.add(base)
    for p in base.parent.glob(base.name + ".*"):
        if p.suffix.lstrip(".").isdigit():
            files.add(p)
    for p in base.parent.glob(f"{base.stem}_*.jsonl"):
        files.add(p)
    for p in base.parent.glob(f"{base.stem}_*.jsonl.*"):
        if p.suffix.lstrip(".").isdigit():
            files.add(p)
    return sorted(files)


def load_jsonl_entries(base: Path) -> list[dict]:
    """读取某逻辑路径下全部数据文件（iter_data_files）的 JSONL 行，容错跳过坏行。"""
    entries: list[dict] = []
    for f in iter_data_files(base):
        try:
            with open(f, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError:
            continue
    return entries
