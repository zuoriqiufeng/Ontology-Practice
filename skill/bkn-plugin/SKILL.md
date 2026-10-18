---
name: bkn-plugin
description: |
  【开发者参考 — 非诊断/分析场景勿加载】
  Demo Product BKN Plugin 架构与内部机制文档。仅限开发/维护/审计场景使用：
  理解 Plugin 代码结构、补充管道原理、置信度评估逻辑、Tool 注册流程。
  ⚠️ 日常诊断/分析/方案设计直接调用 15 个 BKN Tool 即可，BKN Tool 是注册好的函数，
  knowledge_context 直接消费，不需要加载此 Skill 理解底层 dispatch 机制。
triggers:
  - "BKN Plugin 源码"
  - "Plugin 架构修改"
  - "supplement pipeline 原理"
  - "置信度评估逻辑"
  - "BKN Tool 注册"
  - "Plugin 开发"
  - "BKN 代码结构"
  - "BKN 设计文档"
  - "BKN 优化方案"
  - "doc/build"
tools_used:
  - query_product
  - explain_architecture
  - design_solution
  - check_compatibility
  - list_scenarios
  - diagnose_error
  - diagnose_db_link
  - get_prerequisites
  - resolve_relation
  - resolve_operation
  - search_qdrant
  - check_action_risk
  - diagnose_mechanism
  - bkn_ask
  - check_plan
---

# Demo Product BKN Plugin 架构

## 速览

- **15 个 BKN Tool**：直接调用，不需要 skill_view（新增 bkn_ask 摘要入口 / check_plan 计划核对）
- **接入面四层**：会话守则 / 命中注入 / 摘要入口＋@bkn: / MCP(stdio)，见 build/01
- **7 个 Operational Skill**：必须先 `resolve_operation` → 再 `skill_view`
- **补充管道**：BKN 不足时 → `assess_confidence` → Skill 感知 + Qdrant 兜底 → `gap_log`
- **当前版本**：Plugin v1.6（15 Tool + RiskGuard + 守则/注入/引用/观测 + MCP）/ 搜索链路 v3.8（diagnose_db_link 症状优先级 + Skill 强制）
- **关键铁律**：`search_qdrant` 必须传 `dimension`；`search_qdrant_handler` 必须返回 JSON string
- **Hermes venv 依赖**：`qdrant-client` + `sentence-transformers` + `jieba` 缺一不可

---

## 设计文档体系（2026-10-18 精简）

- **工程实施文档**：`doc/build/demo-product-bkn/00-index.md`（现行表；01 架构 / 24 本体 / 30 模块 / 31 工具 / 42 检查单）
- **优化与台账**：`doc/optimize/00-index.md` + `00-changelog.md`
- **能力边界**：`doc/capability/capability-matrix.md`（总览）与 `ontology-inference.md`（推理专章）
- 文档清单不再在本 skill 内重复（避免第二份真相）。

---

## 核心概念：Tool ≠ Skill

demo-product-bkn plugin 有两层不同调用路径：

| 类型 | 数量 | 调用方式 | 例子 |
|------|:--:|---------|------|
| **BKN Tool**（查询/自查类） | 13 | **直接调用** | `design_solution`, `diagnose_error`, `check_action_risk` |
| **Operational Skill**（操作类） | 7 | `resolve_operation` → `skill_view` | `demo-product-rule-manager` |

---

## BKN Tool 完整列表

```
1. query_product          → 产品信息 (aspect 默认 overview; competitor 仅 competitors 用)
2. explain_architecture   → 技术原理 (topic 默认 all; 未命中返回 available_topics)
3. design_solution        → 方案设计 (scenario_hint 映射: migration→跨平台迁移/dual_active→数据库双活/
                            bigdata→大数据采集分析/disaster_recovery→两地三中心; 返回 prerequisites/
                            constraints/risks 从 relations 提取到顶层)
4. check_compatibility    → 兼容性检查 (支持 source_version/target_version)
5. list_scenarios         → 场景列表 (keywords 规范化: str→[str], 非 list→[])
6. diagnose_error         → 错误诊断 (规范化顶层 error_code + diagnosis)
7. get_prerequisites      → 前置条件 (规范化顶层 operation + prerequisites; 未命中返回 available 列表)
8. resolve_relation       → 关联查询 (relation_type 默认 all; target_hint 过滤)
9. resolve_operation      → 操作解析 → Skill 映射 (implements 带 skill: 前缀; implements_skills 多 Skill
                            带 primary/auxiliary 角色; prerequisite_knowledge 为 BKN+Qdrant 合成, 默认即查)
10. search_qdrant         → 维度感知向量搜索 (批量 queries 上限10; dimension __report__/__reset__;
                            chunk_mode: mini_first默认/parent_expand/standard_image/large_only/auto;
                            自定义 collection 仅 BGE 无 BM25; 必须返回 JSON string)
11. diagnose_db_link      → 链路诊断知识合成 (v3.7 症状优先级; v3.8 Skill 强制机制; 返回
                            _search_deferred=true + _available_dimensions + _divergence_prompt)
12. check_action_risk     → RiskGuard 风险自查 (v1.5; action + current_state; 返回 passed/block_reason/
                            rule_id/severity/error_code; action 为空时返回 available_rules)
13. diagnose_mechanism   → 机制归因 (M-4 五段契约; entry=症状/码; observations 可空;
                            候选机制 + 下一步最小验证动作 + 证据缺口)
```

> 实现核对 (2026-10): schemas.py 实为 13 个 schema, tools.py HANDLERS 13 个 handler 全量注册;
> __init__.py register() 按 config.yaml tools.enabled 过滤(空=全启用), toolset=demo-product-bkn,
> 并挂 pre_tool_call hook (RISK_GUARD_BLOCK=false 灰度只记录不阻断)。
> 所有走 _wrap() 的 handler 附加 confidence/gaps/_tool_name, none|partial 时 fallback_to_qdrant,
> BKN 边界安全网 _filter_command_fields 拦截端口/路径/SQL/工具名。

---

## 当前活跃陷阱 (Active Pitfalls)

1. **`search_qdrant` 必须传 `dimension`** — 否则 coverage 不更新
2. **Hermes venv 必须装依赖** — `qdrant-client` + `sentence-transformers` + `jieba`
3. **BGE 模型维度必须与 Qdrant 一致** — bge-large=1024
4. **新增 Tool 三点铁律** — 必须同时改 `schemas.py` + `tools.py Handler` + `tools.py HANDLERS`
5. **`search_qdrant_handler` 返回 string 而非 dict** — 不走 `_wrap()` 的 handler 必须 `json.dumps()`
6. **BM25 索引随 reload 可选重建**（**仅限 BM25 稀疏索引**；`.bkn` 数据更新不能靠它生效——`reload.py` 只重建执行它的短命进程的全局，**常驻服务必须重启进程**） — `reload.py` 默认不重建 BM25；BKN 重新向量化导入 Qdrant 后，用 `python3 -m plugin.scripts.reload --with-bm25` 重置稀疏索引（下次搜索自动重建）

---

## References 索引（开发者向）

> 本 Skill 只承载 Plugin 内部机制 / 审计记录 / 运行环境三类内容；产品与原理正文在
> `demo-product-product-knowledge`，检索质量评估在 `bkn-test`。

**值数据侧车（本体与实现的接缝，改口径只改这三处）**

- [error-semantics.md](references/error-semantics.md) — 码→含义：**码只作入口**（Q27），按日志消息文本命中 8 个有界 `dimension:*`
- [edge-semantics.md](references/edge-semantics.md) — 边走法/公理层：哪些声明**真的**被求值器消费（含缺陷 R-1「纸上公理」）
- [skill-manifest.md](references/skill-manifest.md) — ID→实现与检索源身份（`store:*` / `process:*` / 证据源顺序）

**Plugin 内部机制**

- [supplement-pipeline.md](references/supplement-pipeline.md) — search_qdrant 三级降级链与过滤规则（v2.1）
- [supplement-v3-decompose.md](references/supplement-v3-decompose.md) — v3.0/v3.1 Decompose 与维度覆盖度追踪
- [supplement-decompose-internals.md](references/supplement-decompose-internals.md) — Decompose 自动检索机制与失效分析
- [v2.4-quality-optimizations.md](references/v2.4-quality-optimizations.md) — v2.4 质量评估精度与健壮性修复
- [v2.3-quality-archive-pointer.md](references/v2.3-quality-archive-pointer.md) — v2.3 质量管道源码归档指针
- [audit-methodology.md](references/audit-methodology.md) — Plugin 审计方法论 + 版本维护清单 + Tool HTTP400 定位

**审计记录（历史留档）**

- [supplement-audit-2026-07-02.md](references/supplement-audit-2026-07-02.md) — supplement.py v2.2 审计（Qdrant 未触发盲区）
- [design-code-audit-2026-07-03.md](references/design-code-audit-2026-07-03.md) — 设计文档 vs 源码 13 处不一致
- [plugin-audit-2026-07-03.md](references/plugin-audit-2026-07-03.md) — Plugin 代码 vs 设计文档审计结论

**故障/环境/工具链**

- [bge-precision-failure-4002.md](references/bge-precision-failure-4002.md) — BGE precision 失败（-4002）端到端诊断
- [search-qdrant-dict-leak.md](references/search-qdrant-dict-leak.md) — handler 返回 dict 致 HTTP400 调用链
- [deepseek-api-compatibility.md](references/deepseek-api-compatibility.md) — DeepSeek API `content:null` → HTTP400
- [decompose-collapse-diagnosis.md](references/decompose-collapse-diagnosis.md) — Decompose 去重塌缩诊断（v2.1 已修复）
- [bm25-rebuild.md](references/bm25-rebuild.md) — BM25 索引重建 runbook（`reload --with-bm25`）
- [hermes-venv-setup.md](references/hermes-venv-setup.md) — Hermes venv 依赖安装 + BGE 模型维度配置

---

## 相关 Skill

| Skill | 用途 |
|-------|------|
| `demo-product-product-knowledge` | 产品与原理正文 |
| `demo-product-migration-designer` | 方案设计 + HTML 报告 |
| `demo-product-log-analyzer` | 日志分析 + 回调 POST |
| `demo-product_report_sender` | 分析报告发送 |
| `demo-product-db-diagnostics` | 多数据库链路诊断 |
| `bkn-updater` | 更新 BKN 业务知识网络 |
| `bkn-test` | BKN 效果评估（检索质量评估权威） |
