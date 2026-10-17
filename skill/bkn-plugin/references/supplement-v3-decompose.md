# Supplement Pipeline — v3.0 / v3.1 技术细节

## v3.0: Hermes-native Decompose (SEARCH_DEFER_TO_HERMES)

当 `config.yaml` 中 `SEARCH_DEFER_TO_HERMES: true` 时，`fallback_to_qdrant()` 跳过内部 Qdrant 搜索，返回 `_search_deferred: true` + `_instruction`，由 Agent 自主调用 `search_qdrant` Tool 补查。

### 跳过的管道
```
fallback_to_qdrant() L837:
  if SEARCH_DEFER_TO_HERMES and confidence in ("none", "partial"):
      instruction = _build_search_instruction(tool_name, args, gaps)
      result["_instruction"] = instruction
      result["_search_deferred"] = True
      return result  # ← 下面的全部跳过:
  # 跳过: _decompose_queries / search_qdrant / _aggregate_results
  # 跳过: 会话跨调用去重 (_SESSION_SEEN)
  # 跳过: assess_qdrant_quality 双维评估
  # 跳过: 四象限降权 + 质量反馈
```

### Agent 补查路径
```
Agent 收到 _search_deferred + _instruction
  → search_qdrant_handler(query, dimension, tool_name)  ← BKN Tool #10
    ├─ 默认集合: search_qdrant() BGE+BM25→RRF + _is_valid_content
    ├─ 自定义集合: BGE + _is_valid_content (统一过滤)
    ├─ v3.1: _track_dimension(dim, count) → _SESSION_DIMS
    └─ 返回 {hits[]._dim, coverage{covered_dims, uncovered_dims}}
```

## v3.1: 维度感知覆盖度追踪

### 核心数据结构
```python
_SESSION_DIMS = {}  # {"全量同步参数": 5, "增量/日志解析": 3, ...}
```

### 关键函数
```python
def _track_dimension(dim_name: str, hit_count: int):
    """每次 search_qdrant 调用后记录维度命中"""
    if dim_name:
        _SESSION_DIMS[dim_name] = _SESSION_DIMS.get(dim_name, 0) + hit_count

def get_dimension_coverage(tool_name: str = None) -> dict:
    """返回当前 session 维度的全覆盖报告"""
    known = _get_known_dimensions(tool_name)
    covered = [d for d in known if d in _SESSION_DIMS]
    uncovered = [d for d in known if d not in _SESSION_DIMS]
    return {
        "total_dims": len(known),
        "covered_dims": covered,
        "uncovered_dims": uncovered,
        "dim_hit_count": {d: _SESSION_DIMS[d] for d in covered},
    }
```

### 维度集来源
维度名从 `_DECOMPOSE_TEMPLATES` 提取，默认使用 `design_solution` 的 9 维度:
1. 字符集/类型映射
2. 全量同步参数
3. 增量/日志解析
4. 断点续传/容错
5. 数据校验/对比
6. 源端特定配置
7. 目标端特定配置
8. 跨地域/网络优化
9. 风险/异常处理

### __report__ 模式
`search_qdrant(query="__report__", dimension="__report__")` 不执行搜索，仅返回当前覆盖度快照。

## v2.3 质量评估 vs v3.1 覆盖度追踪

| | v2.3 | v3.1 |
|---|---|---|
| 触发路径 | decompose=false (Tool内部) | decompose=true (Agent外部) |
| 评估方式 | 双维启发式 (relevance × completeness) | 维度命中统计 (确定性) |
| 误判风险 | 有 (关键词匹配遗漏) | 无 |
| Agent 作用 | 被动消费四象限标签 | 主动迭代补搜 |
| 代码量 | ~200 行 | ~40 行 |
