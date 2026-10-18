"""prompt_sections.py — 会话常驻守则（P1：让本体出现在 Agent 的「眼前」）

只注册一段**有界**的常驻守则（默认 ≤1200 字），回答三个问题：
  什么时候该查本体、查哪个入口、什么算「查到了」。
"""

RULES = """【BKN 本体操作守则】
1) 问题只要涉及产品组件/依赖关系/报错码/操作约束，**先查本体再回答**：先 `bkn_ask`（默认摘要），需要细节再加 `detail="ref"`。
2) 引用本体的结论必须带证据：错误码看 `meaning`/`dimensions`，症状看 `recommended_skills`/`log_navigation`；没有证据就不要写成「本体说」。
3) 本体只给「做什么、看哪、找谁」；**命令与参数一律由 Skill 给出**，不要从本体推命令或阈值。
4) 本体给不出时如实说「本体未覆盖」，并说明需要什么输入（码所在的日志文本、日志来源、库类型）。
5) 错误码只是入口：不要背码表含义，含义看 `meaning`/`dimension`；码不进本体是设计约束。
"""


def register_prompt_sections(plugin_api) -> bool:
    """注册常驻守则；平台不支持时返回 False（不抛异常、不影响工具注册）。"""
    try:
        plugin_api.register_system_prompt_section(
            id="bkn-operating-rules",
            content=RULES,
            position="after_memory",
            max_chars=1200,
        )
        return True
    except Exception:  # noqa: BLE001 — 老版本平台无此 API
        import logging
        logging.getLogger(__name__).warning("prompt section 注册失败（平台可能不支持）", exc_info=True)
        return False
