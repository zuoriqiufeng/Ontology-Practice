# Supplement Pipeline — v2.1 技术细节

## search_qdrant() 三级降级链

```
search_qdrant(query, top_k, hybrid=True)

  ├── 路径1: client + model 都可用
  │   ├── hasattr(client, "query_points")
  │   │   → client.query_points(collection, query=emb, limit=top_k, score_threshold=0.3)
  │   │   → v2.1 新增: _is_valid_content() 过滤每个结果
  │   │   → v2.1 新增: _payload_content() 取 content > blurb > text
  │   ├── hasattr(client, "search")  [兼容]
  │   │   → client.search(collection, query_vector=emb, limit=top_k)
  │   └── 都不存在 → NotImplementedError → fall through
  │
  └── 路径2: 无 client/model 或异常
      → _fallback_scroll_with_filter(query, top_k, model)
        → _fallback_scroll_raw(top_k * 3)  # 多取3倍供过滤+重排
          → REST POST /collections/{name}/points/scroll
          → _is_valid_content() 过滤
        → 如果 model 可用: BGE 余弦相似度重排序
        → 截断到 top_k
```

## _is_valid_content() 过滤规则

```python
_IMAGE_PLACEHOLDER_PATTERNS = [
    "[嵌入图片:", "[圖片:", "[image:", "[Picture:",
]

def _is_valid_content(text):
    text = text.strip()
    if len(text) < 20:      # 极短噪声
        return False
    for pat in _IMAGE_PLACEHOLDER_PATTERNS:
        if pat in text:     # PDF 图片占位符
            return False
    return True
```

## _payload_content() 字段优先级

Qdrant 中不同文档来源字段名不一致：
- KWeaver-chunked 文档: `content` 字段
- 某些源: `blurb` 字段（摘要）
- 极少数: `text` 字段

统一取: `content > blurb > text`，截断到 600 字符。

## 修复前后对比

```
PostgreSQL → DB2, design_solution, 8维度 × top_k=5

修复前:
  去重前 40 条 → score 全 0.000 → 去重后 5 条
  内容: "[嵌入图片: document_image_rId119.png]" × N

修复后:
  去重前 ~35 条 → score 0.65~0.79 → 去重后 10 条
  内容: "全量装载线程数,缺省为1...DB2 grant dbadm...PostgreSQL同步规则..."
```
