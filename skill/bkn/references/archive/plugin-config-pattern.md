# BKN Plugin 配置层级模式

> 本会话验证的 Plugin 配置架构模式

## 层级

```
环境变量 (最高优先级)
  ↓ 覆盖
config.yaml
  ↓ 覆盖
代码默认值 (最低优先级)
```

## 配置项

```yaml
# config.yaml（当前完整字段见 doc/build/demo-product-bkn/41-config_reference.md）
bkn:
  root: ../bkn                    # 环境变量: DEMO-PRODUCT_BKN_ROOT

qdrant:
  host: localhost                 # 环境变量: QDRANT_HOST
  port: 6333                      # 环境变量: QDRANT_PORT
  collection: demo-product_collection # 环境变量: QDRANT_COLLECTION
  secondary_collection: test_doc_chunks
  timeout: 5

embedding:
  mode: local                     # local | api
  model_name: BAAI/bge-large-zh-v1.5
  dimension: 1024                 # 必须与 Qdrant collection 向量维度一致
  device: cpu

search:
  top_k: 5
  score_threshold: 0.3
  hybrid: true                    # BM25 + BGE RRF 混合搜索
  fallback_on_bkn_none: true
  fallback_on_bkn_partial: true
  partial_enrich: true
  min_content_length: 50
  min_risk_count: 5
  defer_to_hermes: true           # _search_deferred + _instruction
  bm25_fallback_score: 0.1        # BGE miss 阈值
  bm25_precision_guard: true      # 精确项未命中时 BM25 兜底
  chunk_mode: mini_first          # v3.6 块感知检索策略
  output_max_chars: 0             # 输出总量预算（0=无限制）

risk_guard:                       # v1.5 代码级护栏（规则 BKN 驱动）
  enabled: true
  block: false                    # 灰度期只记录不阻断

tools:
  enabled: []                     # 空=全部启用; ["name1","name2"]=指定
```

## 加载代码

```python
# config.py
BKN_ROOT = os.environ.get("DEMO-PRODUCT_BKN_ROOT", 
                          BKN.get("root", "../bkn"))
```

## 为什么这样设计

1. **环境变量覆盖** — 容器化部署时注入, 不改配置文件
2. **config.yaml 做默认** — 开发环境开箱即用
3. **代码默认兜底** — 配置文件缺失也能跑

## 工具声明策略

- 工具定义在 `schemas.py` (唯一真实来源)
- `config.yaml tools.enabled` 只做过滤, 不重复声明
- 默认 `[]` 全部启用, 可指定白名单缩小范围
