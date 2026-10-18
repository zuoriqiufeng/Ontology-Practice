"""demo_product-bkn Plugin — 注册 14 个 Tool + RiskGuard pre_tool_call hook

Hermes 启动时调用 register(), 向 Plugin API 注册所有 Tool。
可通过 config.yaml tools.enabled 选择性启用。
v1.5: 注册 RiskGuard pre_tool_call hook（受控动作执行前的风险拦截，灰度期只记录）。
P1 (C-20261018-03): 新增 bkn_ask（摘要优先入口）＋ 会话常驻守则（prompt section）。
P1b (C-20261018-04): 新增请求级注入（llm_request middleware）＋ @bkn: 引用（context reference）。
P2 (C-20261018-05): 新增 check_plan（计划可行性机械核对）。
P2 (C-20261018-06): 新增全工具来源观测（tool_execution middleware）。
"""

from .schemas import SCHEMAS
from .tools import HANDLERS
from .config import _config


def register(plugin_api):
    """Hermes 启动时调用，注册 Tool schemas + handlers + RiskGuard hook"""
    enabled = _config.get("tools", {}).get("enabled", [])
    for schema in SCHEMAS:
        name = schema["name"]
        # enabled=[] → 全部启用; enabled=[...] → 仅列表中的
        if enabled and name not in enabled:
            continue
        handler = HANDLERS.get(name)
        if handler:
            plugin_api.register_tool(
                toolset="demo_product-bkn",
                name=name,
                schema=schema,
                handler=handler,
            )

    # P1 (C-20261018-03)：摘要优先入口 bkn_ask（不放进 SCHEMAS，避免改动 schemas.py）
    try:
        from .ask import SCHEMA as ASK_SCHEMA, ask as ask_handler
        if not enabled or "bkn_ask" in enabled:
            plugin_api.register_tool(
                toolset="demo_product-bkn",
                name="bkn_ask",
                schema=ASK_SCHEMA,
                handler=ask_handler,
            )
    except Exception:
        import logging
        logging.getLogger(__name__).warning("bkn_ask 注册失败（不影响旧工具）", exc_info=True)


    # P2 (C-20261018-05)：计划可行性检查（机械核对前置与约束）
    try:
        from .plan_check import SCHEMA as PLAN_SCHEMA, check_plan as plan_check_handler
        if not enabled or 'check_plan' in enabled:
            plugin_api.register_tool(
                toolset='demo_product-bkn',
                name='check_plan',
                schema=PLAN_SCHEMA,
                handler=plan_check_handler,
            )
    except Exception:
        import logging
        logging.getLogger(__name__).warning('check_plan 注册失败（不影响旧工具）', exc_info=True)


    # P2 (C-20261018-06)：全工具来源观测（tool_execution middleware，只观测不改结果）
    try:
        from .trace import register_trace
        register_trace(plugin_api)
    except Exception:
        import logging
        logging.getLogger(__name__).warning('trace middleware 注册失败（不影响工具）', exc_info=True)

    # v1.5 (P0-4): RiskGuard — pre_tool_call hook 实现代码级风险护栏。
    # 灰度期 RISK_GUARD_BLOCK=false 只记录日志不阻断；
    # 未命中受控动作时返回 None（observer 语义，零影响）。
    try:
        from .risk_guard import pre_tool_call_hook
        plugin_api.register_hook("pre_tool_call", pre_tool_call_hook)
    except Exception:
        # hook 注册失败不影响 Tool 注册
        import logging
        logging.getLogger(__name__).warning("RiskGuard hook 注册失败", exc_info=True)

    # P1 (C-20261018-03)：会话常驻守则（有界 ≤1200 字）；平台不支持时静默降级。
    try:
        from .prompt_sections import register_prompt_sections
        register_prompt_sections(plugin_api)
    except Exception:
        import logging
        logging.getLogger(__name__).warning("守则 section 注册失败（不影响工具）", exc_info=True)


    # P1b (C-20261018-04)：请求级卡片注入（llm_request middleware，命中码/症状才注入）
    try:
        from .inject import register_inject
        register_inject(plugin_api)
    except Exception:
        import logging
        logging.getLogger(__name__).warning('inject middleware 注册失败（不影响工具）', exc_info=True)

    # P1b (C-20261018-04)：`@bkn:` 按需展开（context reference）
    try:
        from .context_refs import register_context_refs
        register_context_refs(plugin_api)
    except Exception:
        import logging
        logging.getLogger(__name__).warning('context reference 注册失败（不影响工具）', exc_info=True)

    # 批 V-1 × U-2（2026-10-12）：服务自证——把「本进程加载了什么」写入 logs/.loaded_version.json，
    # 现场据此回答"此刻跑的是哪版"、并能发现"磁盘已改、进程未加载"（27 号 I16）。
    try:
        from .loaded_version import attest_loaded_version
        attest_loaded_version("register")
    except Exception:
        import logging
        logging.getLogger(__name__).warning("服务自证写入失败（不影响注册）", exc_info=True)
