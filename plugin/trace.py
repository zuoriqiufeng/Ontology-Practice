"""trace.py — 全工具来源观测（P2：把 `answer_source` 覆盖从 6% 补到近全覆盖）。

现状（43 号 §1）：只有 `diagnose_error` / `diagnose_db_link` 两个 handler 自己记 `answer_source`，
其余 13 个工具在生产日志里没有来源标记 ⇒「本体到底有没有参与」不可度量。

做法：`tool_execution` middleware 包一层，**只观测不改结果**：
  * 按工具名分类来源层（bkn_graph / bkn_code / bkn_summary / retrieval / other）；
  * 记 `chars`（体积）与 `ms`（耗时），供 43 号 D 系列与 77 号评测复用；
  * 已自行记录的两个 handler **跳过**，避免重复计数；
  * 只统计本插件 15 个工具（C-20261018-18：外部工具不入 answer_source，避免 D12 口径被污染）。
"""
from __future__ import annotations

import time

from .trajectory import _append

_LAYER = {
    "resolve_relation": "bkn_graph",
    "resolve_operation": "bkn_graph",
    "get_prerequisites": "bkn_graph",
    "check_plan": "bkn_graph",
    "explain_architecture": "bkn_graph",
    "bkn_ask": "bkn_summary",
    "diagnose_mechanism": "bkn_code",
    "search_qdrant": "retrieval",
    "query_product": "bkn_product",
    "design_solution": "bkn_product",
    "list_scenarios": "bkn_product",
    "check_compatibility": "bkn_product",
}
_ALREADY = frozenset({"diagnose_error", "diagnose_db_link"})

# C-20261018-18：只观测本插件 15 个工具；外部工具（exec_shell/terminal/...）不进 answer_source
_BKN_TOOLS = frozenset({"query_product", "explain_architecture", "design_solution", "check_compatibility", "list_scenarios", "diagnose_error", "get_prerequisites", "resolve_relation", "resolve_operation", "search_qdrant", "diagnose_db_link", "check_action_risk", "diagnose_mechanism", "bkn_ask", "check_plan"})


def classify(tool_name: str) -> str:
    return _LAYER.get(tool_name, "other")


def tool_execution_middleware(*, tool_name: str, args: dict, next_call, **kwargs):
    """包一层观测：先执行，再记事件；异常原样抛出（不影响工具语义）。"""
    t0 = time.perf_counter()
    result = next_call(args)
    try:
        if tool_name in _BKN_TOOLS and tool_name not in _ALREADY:
            text = result if isinstance(result, str) else str(result)
            _append({"event": "answer_source", "ts": int(time.time()),
                     "task_id": str(kwargs.get("task_id") or "")[:48],
                     "tool": tool_name, "layer": classify(tool_name),
                     "chars": len(text), "duration_ms": round((time.perf_counter() - t0) * 1000, 1),
                     "via": "middleware"})
    except Exception:  # noqa: BLE001 — 观测失败绝不影响工具
        pass
    return result


def register_trace(plugin_api) -> bool:
    try:
        plugin_api.register_middleware("tool_execution", tool_execution_middleware)
        return True
    except Exception:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning("trace middleware 注册失败（平台可能不支持）", exc_info=True)
        return False
