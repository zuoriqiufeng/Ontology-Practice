"""prompt_sections.py — 会话常驻守则（P1：让本体出现在 Agent 的「眼前」）

只注册一段**有界**的常驻守则（默认 ≤1200 字），回答三个问题：
  什么时候该查本体、查哪个入口、什么算「查到了」。
"""

RULES = """【BKN 本体操作守则】
1) 问题涉及产品组件/依赖/报错码/操作约束，**先查本体**（默认 `bkn_ask` 摘要，需要细节加 `detail="ref"`）。**错误码先判来源**：产品码（-NNNN 或在侧车中命中的 4–5 位数字码，如 4017/4217）→ `diagnose_error`；数据库原生码（ORA-/TNS-/SQLSTATE/1062…）或来源不确定 → `bkn_ask`（它按来源分流，DB 码转 DB 诊断，需库类型）。码义以工具返回为准，不凭记忆作答。若本轮出现【BKN 卡片】，按卡片给出的入口走。
2) 引用本体的结论必须带证据：错误码看 `meaning`/`dimensions`，症状看 `recommended_skills`/`log_navigation`；没有证据就不要写成「本体说」。
3) 本体只给「做什么、看哪、找谁」；**命令与参数一律由 Skill 给出**，不要从本体推命令或阈值。
4) 本体给不出时如实说「本体未覆盖」，并说明需要什么输入（码所在的日志文本、日志来源、库类型）。
5) 码义看 `meaning`/`dimension`；数据库原生码本体只给排查落点，含义看 DB 文档/Skill；来源不明时先要库类型或日志文本，不要猜。
6) `bkn_ask` 摘要 `sufficient=true` 就直接作答；需要原始日志行才补一次检索（`search_qdrant(compact=true, top_k=3)`），不要连续检索凑证据。
7) 多个**互不依赖**的检索需求一次 `search_qdrant(queries=[...])` 发出（≤10 条，每项可带 top_k/chunk_mode）；仅当内容互相依赖时才逐条调用。
8) `bkn_ask` / `diagnose_*` 返回后，若补查内容已可确定（如码已确定、只补参数），把 `search_qdrant` 与下一条 `diagnose_*` 放进**同一轮** tool_calls 并行发出；内容依赖上一步结果的仍串行。
9) 诊断开始前先在思考里列出检索计划（查哪些码/症状/实体关系/操作映射），已知需求一次并行发出，不要逐条试错式检索。
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
