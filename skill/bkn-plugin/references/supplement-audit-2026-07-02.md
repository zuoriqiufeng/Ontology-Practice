# supplement.py v2.2 审计报告 (2026-07-02)

## 触发场景

用户问"DB2(长沙)→MySQL(苏州)跨地域迁移方案"，Agent 调用了 4 个 BKN Tool：
- `design_solution` → BKN skeleton + Qdrant enrichment（正常）
- `explain_architecture("incremental_sync")` → BKN skeleton, **Qdrant 未触发**（bug）
- `query_product("overview")` → BKN skeleton, **Qdrant 未触发**（bug）
- `check_compatibility` → 仅返回 supported=true, **Qdrant 未触发**（bug）

Agent 拿到 skeleton 后，用 `read_file` 读 BKN 静态文件补充，跳过了 Qdrant。
用户连续追问三次"为什么没走 Qdrant"，最终定位到 supplement.py 置信度评估盲区。

## 根因分析

### Bug 1: `REQUIRED_FIELDS["explain_architecture"] = []` (L39)

```python
REQUIRED_FIELDS = {
    "design_solution":      ["scenario", "description", "compatibility"],
    "check_compatibility":  ["supported"],
    "explain_architecture": [],            # ← 空！
    "query_product":        ["raw"],
    ...
}
```

在 `assess_confidence()` L101:
```python
required = REQUIRED_FIELDS[tool_name]
if required:              # ← 空列表 → False → 跳过
    for field in required:
        ...
```

结果：`explain_architecture` 的字段校验永不被执行。只剩长度检查（L97-98）：
```python
if len(raw_text) < SEARCH_MIN_CONTENT_LENGTH:  # 50 字符
    gaps.append(...)
```

任何 BKN 返回的 JSON > 50 字符 → confidence="full" → Qdrant 兜底不触发。

**修复**：`REQUIRED_FIELDS["explain_architecture"] = ["raw"]`

### Bug 2: `_deep_check()` 只覆盖 2 个 Tool (L116-147)

```python
def _deep_check(result, tool_name):
    if tool_name == "design_solution":      # ← 只处理
    elif tool_name == "diagnose_error":     # ← 这两个
    # explain_architecture / query_product / check_compatibility
    # get_prerequisites / list_scenarios / resolve_relation
    # → 全部不匹配 → 无 gaps → 无 Qdrant 补充
```

**修复**：新增通用 elif 分支覆盖 6 个 Tool：
```python
elif tool_name in ("explain_architecture", "query_product", "check_compatibility",
                    "get_prerequisites", "list_scenarios", "resolve_relation"):
    _META_KEYS = {"confidence", "gaps", "_tool_name", "_bkn_skeleton",
                  "fallback_hint", "enrichment", "notes"}
    raw_json = json.dumps({k: v for k, v in result.items()
                           if k not in _META_KEYS}, ensure_ascii=False)
    if len(raw_json) < 200:
        gaps.append("BKN 返回内容过短, 建议查 Qdrant 补充")
    elif not result.get("enrichment") and not result.get("fallback_hint"):
        gaps.append("BKN 内容可能不完整, 建议查 Qdrant 补充")
```

### Bug 3: tools.py check_compatibility handler 注入无效 metadata (L94-97)

```python
# 修复前
if result.get("supported"):
    result["confidence"] = "full"   # ← 被 _wrap() 覆盖，空操作
    result["gaps"] = []             # ← 被 _wrap() 覆盖，空操作  
    result["notes"] = "..."         # ← 残留，污染 _deep_check JSON 长度
```

**修复**：删除整个 `if result.get("supported")` 块，`_wrap()` 会自己评估。

### Bug 4: resolve_relation 不在 _DECOMPOSE_TEMPLATES

fallback_to_qdrant 触发后，`SEARCH_DECOMPOSE && tool_name in _DECOMPOSE_TEMPLATES` → False → 退化到单查询模式。

**修复**：添加 `resolve_relation` 模板 + `_decompose_queries` 参数路由（`source_entity`）。

### Bug 5: _deep_check metadata 泄漏

排除 metadata 用 `not k.startswith("_")` 但 `confidence`/`gaps`/`notes` 不是下划线开头。

**修复**：改用显式 `_META_KEYS` 集合。

### Bug 6: design_solution 目标端模板 Oracle 硬编码

```python
# 修复前
("目标端特定配置", lambda s, t: f"{t} 归档模式 附加日志 用户授权 字符集 配置命令"),
# "归档模式/附加日志" → Oracle/DM 专用，MySQL/DB2/PG 目标端不适用
```

**修复**：改为 `f"{t} 同步 配置 字符集 用户授权 环境要求"`

### Bug 7: _GAP_KEYWORD_MAP 缺通用匹配

新增 gap 消息 "BKN返回内容过短" / "内容可能不完整" 不含已有的主题词（风险/跨地域等），
`_extract_gap_keywords()` 返回空列表。

**修复**：追加通用条目：
```python
"内容过短": "配置 参数 步骤 操作 注意事项",
"内容可能不完整": "配置 参数 步骤 注意事项 兼容性",
"建议查 Qdrant": "配置 参数 操作 步骤 注意事项",
```

## 影响范围

修复前：9 个 BKN Tool 中，只有 `design_solution` 和 `diagnose_error` 有完整的置信度评估。
其余 7 个 Tool 中 6 个存在不同程度的盲区（`resolve_operation` 走的是操作路由，不依赖 supplement）。

修复后：全部 9 个 Tool 有完整的 L1→L2→L3 覆盖。

## Agent 行为教训

即使 supplement pipeline 有 bug，Agent 也应遵守"禁止用 read_file 替代 Qdrant"的约束。
当 Tool 返回 skeleton + gaps 时，正确路径是用 `qdrant_search.py` 脚本补查，而非回退到 read_file。
