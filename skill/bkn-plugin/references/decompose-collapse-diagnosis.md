# Decompose 去重塌缩诊断 → v2.1 已修复

> **状态**: 根因已修复 (2026-07-02 v2.1)。本文件保留作为历史诊断记录和回归验证指南。

## 问题概述

v2.0 的 `search_qdrant()` 使用 `client.search()` API，该 API 在老版 qdrant-client 中不存在，导致静默 fallback 到 REST scroll（score=0, 随机返回）。同时 Qdrant 中 PDF 转换文档含大量 `[嵌入图片]` 占位符，与 425 字符 MD5 去重碰撞，导致 40 条原始命中塌缩为 5 条无效结果。

## v2.1 修复（已实施）

| 修复 | 文件 | 变更 |
|------|------|------|
| API 兼容降级链 | supplement.py `search_qdrant()` | `query_points()` > `search()` > fallback scroll + 模型重排序 |
| 图片占位符过滤 | supplement.py `_is_valid_content()` | 正则匹配 `[嵌入图片:`, `[圖片:`, 等 + <20字符过滤 |
| 统一字段提取 | supplement.py `_payload_content()` | content > blurb > text 优先级 |
| Fallback 增强 | supplement.py `_fallback_scroll_with_filter()` | 多取 3 倍 + BGE 余弦重排序 |

## 验证命令（v2.1 预期：去重后 ≥10 条，score 0.6-0.8）

```bash
cd /tmp && python3 -c "
import sys; sys.path.insert(0, '/path/to/demo-product-bkn')
import plugin.supplement as S

args = {'source': 'PostgreSQL', 'target': 'DB2', 'scenario_hint': 'migration'}
gaps = ['风险条目过少(仅3条)', '兼容性确认但缺少版本/限制说明']

queries = S._decompose_queries('design_solution', args, gaps)
all_hits = []
for q in queries:
    hits = S.search_qdrant(q, top_k=S.SEARCH_DECOMPOSE_TOP_K, hybrid=S.SEARCH_HYBRID)
    if hits:
        all_hits.append((q, hits))

total = sum(len(h[1]) for h in all_hits)
agg = S._aggregate_results(all_hits)
print(f'去重前: {total}条 | 去重后: {len(agg)}条')
"
```

## 历史根因（v2.0）

| 层级 | 问题 | 影响 |
|------|------|------|
| 数据质量 | PDF 转文本含大量 [嵌入图片] 占位符 | 33字符无效内容占据命中 |
| 搜索 API | `client.search()` 返回 score=0.000 | 排序失效 |
| 去重逻辑 | 425字符 MD5 → 33字符内容全部碰撞 | 40→5 塌缩 |
