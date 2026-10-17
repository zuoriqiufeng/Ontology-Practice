"""demo_product-bkn Plugin — 注册 13 个 Tool + RiskGuard pre_tool_call hook

Hermes 启动时调用 register(), 向 Plugin API 注册所有 Tool。
可通过 config.yaml tools.enabled 选择性启用。
v1.5: 注册 RiskGuard pre_tool_call hook（受控动作执行前的风险拦截，灰度期只记录）。
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

    # 批 V-1 × U-2（2026-10-12）：服务自证——把「本进程加载了什么」写入 logs/.loaded_version.json，
    # 现场据此回答"此刻跑的是哪版"、并能发现"磁盘已改、进程未加载"（27 号 I16）。
    try:
        from .loaded_version import attest_loaded_version
        attest_loaded_version("register")
    except Exception:
        import logging
        logging.getLogger(__name__).warning("服务自证写入失败（不影响注册）", exc_info=True)
