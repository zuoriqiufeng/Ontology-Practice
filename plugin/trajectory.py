"""trajectory.py — 任务级轨迹事件流（25 号批 U-1，2026-10-12）

定位（Q13 本仓侧探查结论，见 33 号）：**调用级事件流 + 读时聚合**——
插件侧拿不到任务终态（`final_answer`/`task_status` 只在 Hermes 上游，本仓零命中），
且插件无「任务结束」信号，故不做进程内任务状态累积；每次 Tool 调用写一行事件，
由 `plugin/scripts/trajectory_report.py` 按 task_id 组装 timeline。

- 事件字段：task_id / session_id / seq / ts / tool / args(已裁剪快照) / args_hash /
  confidence / gaps / bkn_hits / question(user_task，若上游给) / error / out_chars /
  duration_ms / bkn_version；
- **两种条目**：调用级（`log_call`，每次 Tool 调用一行）与**过程级**（`log_event`，
  带 `kind: "event"` + `event` 字段——44 号 §3 的旁路累积器在调用出口一次刷盘）；
  同一文件、同一流，读侧按 `kind`/`event` 分流；
- **只在 task_id 非空时写**：压测、门禁（gate ④）、手工裸调用不落盘——43 号判据与
  门禁流量不受影响（与 usage_log 的「真假流量分离」同理）；
- 脱敏（I9）在写入前完成：IPv4 / 凭据键值 / URL 内口令一律掩码；
- 单行上限 8KB（超限逐级压缩，最终标 `_truncated`）；
- 全程 try/except：轨迹写入的任何异常都不影响 Tool 主流程。

不做（明确边界）：不记思维链；不记完整工具原始输出；不读 Hermes `state.db`。
"""

from __future__ import annotations

import hashlib
import itertools
import json
import re
import time
from pathlib import Path

from .config import resolve_log_path

#: 逻辑基名（实际文件由 log_rotate.rotate_day_file 按日期派生到 trajectories/ 子目录）
TRAJ_LOG = resolve_log_path("trajectories/trajectory.jsonl")

#: 版本身份文件（仓库根，27 号批 V-0）；测试可 patch
VERSION_FILE = Path(__file__).resolve().parent.parent / "bkn-version.json"

MAX_LINE_BYTES = 8192
MAX_HITS = 50
MAX_GAPS = 5
MAX_GAP_CHARS = 120
MAX_QUESTION_CHARS = 200
MAX_ERROR_CHARS = 200

#: 进程内单调序号（聚合侧按 (ts, seq) 排序；跨进程重启后序号重置，靠 ts 兜底）
_SEQ = itertools.count(1)

#: bkn_hits 的命名空间白名单（与 `bkn/SCHEMA.md` §0.1 的命名空间全量清单对齐）
#: 2026-10-14 补 `risk`：本体在用它（`risks_of` 的边目标，13 次 / 2 件）、`constants.RELATION_TARGET_NAMESPACES`
#: 也早已登记，唯独不在本白名单 ⇒ 这些命中被**系统性漏计**。P3 探针里它表现为 `paths_shape_gap` 的
#: **假缺口**——报「本体给了候选、一条没进输出」，其实是**识别器不认这个命名空间**，不是本体没用。
#: `class` 已退场（24 号退役为值 ID），保留**仅为历史轨迹容错**，不是现行命名空间。
_ID_PREFIXES = frozenset({
    "action", "capability", "class", "constraint", "controlnode", "dbnode",
    "dimension", "error", "host", "link", "log", "process", "risk", "rule",
    "scenario", "skill", "store", "symptom", "syncrule", "worknode",
})
# 显式字符类（plugin 禁正则简写，见 test_bkn_boundary）
_ID_RE = re.compile(r"(?<![A-Za-z0-9_:])([a-z_]{2,24}):([A-Za-z0-9_.\-]{1,64})")

#: 脱敏模式：IP / 凭据键值 / URL 内口令（I9）
_IP_RE = re.compile(r"[0-9]{1,3}(?:\.[0-9]{1,3}){3}")
_CRED_RE = re.compile(
    r"(?i)(password|passwd|pwd|token|secret|apikey|api_key)[ \t]*[:=][ \t]*[^ \t,;]{1,200}")
_URL_USERINFO_RE = re.compile(r"//[^/@ \t]{1,120}@")

_version_cache: dict = {"key": None, "value": None}


def _scrub(text: str) -> str:
    """写入前脱敏：IP / 凭据 / URL 口令 → 掩码（I9）。"""
    try:
        text = _IP_RE.sub("[IP已移除]", text)
        text = _CRED_RE.sub(lambda m: f"{m.group(1)}=[已移除]", text)
        text = _URL_USERINFO_RE.sub("//[凭据已移除]@", text)
    except Exception:
        pass
    return text


def _scrub_tree(obj):
    """对快照做递归脱敏（字符串值走 _scrub）。"""
    if isinstance(obj, dict):
        return {k: _scrub_tree(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub_tree(x) for x in obj]
    if isinstance(obj, str):
        return _scrub(obj)
    return obj


def _args_hash(snapshot) -> str:
    """入参快照的稳定短哈希（前后对比用；不含明文）。"""
    try:
        raw = json.dumps(snapshot or {}, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        raw = str(snapshot)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _version_id():
    """读仓库根 bkn-version.json 的 version_id（按 mtime 缓存）；不可得返回 None。"""
    try:
        st = VERSION_FILE.stat()
        key = (st.st_mtime_ns, st.st_size)
        if _version_cache["key"] == key:
            return _version_cache["value"]
        data = json.loads(VERSION_FILE.read_text(encoding="utf-8"))
        value = data.get("version_id")
        _version_cache.update(key=key, value=value)
        return value
    except Exception:
        return None


def _collect_hits(result, cap: int = MAX_HITS) -> list[str]:
    """从 Tool 返回体递归抽取本体对象 ID（命名空间白名单），去重保序、上限 cap。

    覆盖 25 号 §3 的 `bkn_hits` 语义：让「哪条知识被用到」可算。只收 ID 形态字符串，
    不收起结果文本（体量与 I9 双重约束）。
    """
    seen: list[str] = []

    def _walk(obj):
        if len(seen) >= cap:
            return
        if isinstance(obj, dict):
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, (list, tuple)):
            for v in obj:
                _walk(v)
        elif isinstance(obj, str):
            for m in _ID_RE.finditer(obj):
                if m.group(1) not in _ID_PREFIXES:
                    continue
                hit = f"{m.group(1)}:{m.group(2)}"
                if hit not in seen:
                    seen.append(hit)
                    if len(seen) >= cap:
                        return

    try:
        _walk(result)
    except Exception:
        pass
    return seen


def _to_line(entry: dict) -> str:
    """序列化为单行；超 8KB 逐级压缩（压 args/question → 压 gaps/hits → 只留核心）。"""
    line = json.dumps(entry, ensure_ascii=False)
    if len(line.encode("utf-8")) <= MAX_LINE_BYTES:
        return line

    small = dict(entry)
    small.pop("question", None)
    small.pop("args", None)
    small["gaps"] = [g[:40] for g in small.get("gaps", [])][:2]
    small["bkn_hits"] = small.get("bkn_hits", [])[:10]
    small["_truncated"] = True
    line = json.dumps(small, ensure_ascii=False)
    if len(line.encode("utf-8")) <= MAX_LINE_BYTES:
        return line

    for key in ("gaps", "bkn_hits", "error"):
        small.pop(key, None)
    # 44 号 §3.1：`kind`/`event` 是过程级事件的判别键（读侧按它分流），压到核心行也必须留住；
    # 调用级条目本就没有这两个键 → 既有输出逐字节不变。
    core = {k: v for k, v in small.items()
            if k in ("task_id", "session_id", "seq", "ts", "tool", "args_hash",
                     "confidence", "out_chars", "duration_ms", "bkn_version",
                     "kind", "event", "_truncated")}
    line = json.dumps(core, ensure_ascii=False)
    raw = line.encode("utf-8")
    if len(raw) > MAX_LINE_BYTES:  # 兜底（核心行远小于上限，正常不可达）
        line = raw[:MAX_LINE_BYTES].decode("utf-8", errors="ignore")
    return line


def _append(entry: dict) -> None:
    """追加一行事件（日期+大小轮转、保留期随 usage_log）。异常静默。"""
    try:
        from .log_rotate import rotate_day_file
        from .config import (LOG_ROTATE_TRAJ_MAX_BYTES, LOG_ROTATE_BACKUPS,
                             LOG_ROTATE_RETENTION_DAYS)
        path = rotate_day_file(TRAJ_LOG, LOG_ROTATE_TRAJ_MAX_BYTES, LOG_ROTATE_BACKUPS,
                               retention_days=LOG_ROTATE_RETENTION_DAYS)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(_to_line(entry) + "\n")
    except Exception:
        pass


def log_call(tool: str, args_snapshot=None, ctx=None, result=None,
             confidence=None, gaps=None, out_chars=None, duration_ms=None) -> None:
    """写一条调用级轨迹事件（U-1 单点写入器）。

    - `args_snapshot`：已裁剪的入参快照（调用方用 `tools._log_args`，单一裁剪规则）；
    - `ctx`：Hermes kwargs（`task_id`/`session_id`/`user_task`）；
    - `result`：Tool 原返回体（用于 bkn_hits / error 抽取）；
    - 非空 `task_id` 才写；任何异常静默。
    """
    try:
        ctx = ctx or {}
        task_id = str(ctx.get("task_id") or "").strip()[:48]
        if not task_id:
            return
        entry = {
            "task_id": task_id,
            "seq": next(_SEQ),
            "ts": int(time.time()),
            "tool": tool,
            "args_hash": _args_hash(args_snapshot),
            "bkn_version": _version_id(),
        }
        session_id = str(ctx.get("session_id") or "").strip()[:48]
        if session_id:
            entry["session_id"] = session_id
        snapshot = _scrub_tree(args_snapshot) if args_snapshot else None
        if snapshot:
            entry["args"] = snapshot
        if confidence:
            entry["confidence"] = confidence
        if gaps:
            entry["gaps"] = [_scrub(str(g))[:MAX_GAP_CHARS] for g in list(gaps)[:MAX_GAPS]]
        hits = _collect_hits(result)
        if hits:
            entry["bkn_hits"] = hits
        question = _scrub(str(ctx.get("user_task") or "").strip())[:MAX_QUESTION_CHARS]
        if question:
            entry["question"] = question
        if isinstance(result, dict):
            err = result.get("error")
            if err:
                entry["error"] = _scrub(str(err))[:MAX_ERROR_CHARS]
        if isinstance(out_chars, int):
            entry["out_chars"] = out_chars
        if isinstance(duration_ms, int):
            entry["duration_ms"] = duration_ms
        _append(entry)
    except Exception:
        pass


def log_event(tool: str, task_id: str, event: str, dropped: int = 0, **fields) -> None:
    """写一条**过程级**事件（44 号 §3.1）。与 log_call 同一文件、同一流，靠 event 字段区分。

    调用者（`observability.call_scope` 的出口）在**一次调用结束**时把该调用累积的决策点
    一次性刷盘：同一个 task 下，调用级条目与过程级事件按 (ts, seq) 天然交错成 timeline。

    - 脱敏（`_scrub_tree`）与单行 8KB 上限（`_to_line`）沿用本模块既有规则，不另写一套；
    - 非空 `task_id` 才写（与 log_call 同纪律：压测/门禁/裸调用不落盘）；
    - 任何异常静默。
    """
    try:
        task_id = str(task_id or "").strip()[:48]
        if not task_id:
            return
        entry = {
            "task_id": task_id,
            "seq": next(_SEQ),
            "ts": int(time.time()),
            "kind": "event",
            "tool": tool,
            "event": event,
        }
        if dropped:
            entry["dropped"] = dropped
        for key, value in (fields or {}).items():
            entry[key] = _scrub_tree(value)  # 键名不改，只脱敏值
        _append(entry)
    except Exception:
        pass


def reset_seq_for_tests() -> None:
    """测试辅助：重置进程内序号（生产不调用）。"""
    global _SEQ
    _SEQ = itertools.count(1)
