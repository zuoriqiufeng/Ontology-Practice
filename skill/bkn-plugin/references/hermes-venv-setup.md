# Hermes venv 依赖安装 & BGE 模型配置

> 更新: 2026-07-03

## 背景

demo-product-bkn Plugin 在 Hermes 进程内运行，Python 环境是 `/usr/local/lib/hermes-agent/venv/`（Py3.11）。
该 venv 默认不包含向量搜索所需依赖，需手动安装。

## 依赖清单

| 包 | 作用 | 大小 |
|----|------|------|
| `qdrant-client` | Qdrant API 连接 + query_points | ~5MB |
| `sentence-transformers` | BGE 模型加载和编码 | ~50MB |
| `jieba` | BM25 中文分词 | ~19MB |
| `torch` (CPU) | sentence-transformers 底层 | ~200MB |

**总计**: ~800MB（安装后）

## 安装步骤

```bash
# Step 1: torch CPU 版（避免拉 CUDA 全家桶 ~2GB）
/usr/local/lib/hermes-agent/venv/bin/python3 -m pip install \
  torch --index-url https://download.pytorch.org/whl/cpu

# Step 2: 其余依赖
/usr/local/lib/hermes-agent/venv/bin/python3 -m pip install \
  qdrant-client sentence-transformers jieba

# Step 3: 验证
/usr/local/lib/hermes-agent/venv/bin/python3 -c "
for m in ['qdrant_client','sentence_transformers','jieba','torch']:
    __import__(m); print(f'{m}: OK')
"
```

## BGE 模型配置

### 维度匹配检查（关键！）

Qdrant 索引时的模型维度 ≠ 本地模型维度 → `query_points()` HTTP 400 → 静默降级到 scroll。

```bash
# 查 Qdrant 集合维度
curl -s http://localhost:6333/collections/i2tream_collection | \
  python3 -c "import json,sys;d=json.load(sys.stdin);print(d['result']['config']['params']['vectors']['size'])"

# 查本地模型维度
/usr/local/lib/hermes-agent/venv/bin/python3 -c "
from sentence_transformers import SentenceTransformer
m = SentenceTransformer('<repo>/stream-agent/bge-small-zh-v1.5')
print(m.get_sentence_embedding_dimension())
"
```

### 可用模型

| 模型 | 维度 | 路径 | 状态 |
|------|------|------|------|
| bge-large-zh-v1.5 | 1024 | HF Hub `BAAI/bge-large-zh-v1.5` | 需下载 ~1.3GB |
| bge-small-zh-v1.5 | 512 | `<repo>/stream-agent/bge-small-zh-v1.5/` | 本地可用 |

**当前配置** (`config.yaml`):
```yaml
embedding:
  model_name: <repo>/stream-agent/bge-small-zh-v1.5  # 512-dim
  device: cpu
  hf_offline: true
```

⚠️ 如果 Qdrant 是 1024-dim，需要换成 bge-large 或重建索引。

## 验证 search_qdrant 是否正常工作

```bash
# 从 Hermes venv 直接测（模拟 Plugin 实际运行环境）
/usr/local/lib/hermes-agent/venv/bin/python3 -c "
import sys; sys.path.insert(0, '/path/to/demo-product-bkn')
from plugin.supplement import search_qdrant
results = search_qdrant('-4002', top_k=5, hybrid=True)
for i, r in enumerate(results):
    fb = r.get('_fallback_reason', '')
    print(f'[{i}] score={r[\"score\"]:.4f} fb={fb} | {r[\"content\"][:80]}')
"
# 预期输出:
# [0] score=1.0000 fb=BGE precision fail | 4002问题强行继续规则的方法...
# 如果 score=0.0 且 fb 为空 → BGE/模型出问题，走了 scroll 路径
```

## 常见故障

| 症状 | 原因 | 修复 |
|------|------|------|
| score=0.0, 无 fb, 随机文档 | Hermes venv 缺依赖 | 按上方步骤安装 |
| score=0.0, 无 fb, 装依赖后仍随机 | BGE 模型维度不匹配 | 换模型或重建索引 |
| score=0.44+, 无 fb, 内容不相关 | BGE 精确率失败, Precision Guard 未触发 | 检查 `SEARCH_BM25_PRECISION_GUARD` 配置 |
