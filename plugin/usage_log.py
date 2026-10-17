"""usage_log.py — Tool 使用统计日志 (v1.5, P3-1)

独立于 gap_log 的轻量使用统计：
- search_qdrant 记录 chunk_mode/top_k/hits，为块感知策略调优供数据
- _wrap() 记录各 Tool 的 confidence 分布
- 2A: 全部 Tool 记录 duration_ms / out_chars / out_tokens_est（token 为粗估：CJK≈1 token/字，
  其余≈4 字符/token，仅供趋势分析）

文件: <log_rotate.dir>/usage_log_YYYY-MM-DD.jsonl（默认 <repo>/logs/，路径可配置，env LOG_DIR
可覆盖；文件名含日期，跨日自动开新文件，同日超大小轮转 .1/.2/.3——见 log_rotate.rotate_day_file；
USAGE_LOG 常量为**逻辑基名**，测试 patch 基名即可）
分析: python3 plugin/scripts/usage_stats.py
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from .config import resolve_log_path

USAGE_LOG = resolve_log_path("usage_log.jsonl")  # 逻辑基名；实际文件由 rotate_day_file 按日期派生


def _today_log_path() -> Path:
    """当日写入路径（日期+大小双维轮转；异常静默由调用方兜底）。"""
    from .log_rotate import rotate_day_file
    from .config import LOG_ROTATE_USAGE_MAX_BYTES, LOG_ROTATE_BACKUPS, LOG_ROTATE_RETENTION_DAYS
    return rotate_day_file(USAGE_LOG, LOG_ROTATE_USAGE_MAX_BYTES, LOG_ROTATE_BACKUPS,
                           retention_days=LOG_ROTATE_RETENTION_DAYS)


def log_usage(tool: str, **fields):
    """追加一条使用记录。任何异常都不影响主流程（静默吞掉）。"""
    try:
        path = _today_log_path()
        # 目录自愈：测试会用 mock.patch.object 换基名路径，目录可能尚不存在
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {"tool": tool, "ts": int(time.time()), **fields}
        line = json.dumps(entry, ensure_ascii=False)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
