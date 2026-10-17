# BM25 索引重建流程

> 适用场景: Qdrant 新增切块后，BM25 稀疏检索索引未更新导致关键词搜索无法命中新文档

## 问题

BM25 索引在 `bm25.py` 中以全局懒加载单例 (`_bm25_index` / `_bm25_ready`) 形式存在。Hermes Plugin 启动时首次调用 `get_bm25_index()` 后，索引不会自动刷新。新切块入库后，BM25 关键词搜索找不到新文档。

`scripts/reload.py` 只重建 BKN 数据（resolver/traverser/loader），**不重置 BM25 单例**。

## 重建命令

```bash
cd /path/to/demo-product-bkn && \
/root/demo/stream-agent/.venv/bin/python3 -c "
import sys; sys.path.insert(0, '.')
import plugin.bm25 as bm

# 重置全局状态
bm._bm25_index = None
bm._bm25_ready = False

# 重建
idx = bm.get_bm25_index()
print(f'BM25 重建完成: {idx.doc_count} 文档, 平均长度 {idx.avg_doc_len:.0f} token')
"
```

## 约束

必须使用安装了 `qdrant-client` 的 Python 环境。当前可用的 venv:

| venv | qdrant-client |
|------|--------------|
| `/root/demo/stream-agent/.venv` | ✅ 1.16.1 |
| 系统 `python3` | ❌ 无模块 |
| `/usr/local/lib/hermes-agent/venv` | ❌ 无模块 |

## 验证

重建后验证新文档可被 BM25 搜索命中:

```bash
/root/demo/stream-agent/.venv/bin/python3 -c "
import sys; sys.path.insert(0, '/path/to/demo-product-bkn')
from plugin.bm25 import bm25_search

# 搜索新加的 -4002
hits = bm25_search('-4002', top_k=5)
print(f'命中: {len(hits)} 条')
for h in hits[:3]:
    print(f'  bm25_score={h.get(\"bm25_score\",0):.3f} | {h[\"content\"][:100]}')
"
```

预期: 命中 > 0 条，content 包含 `IAERR_LOG_SEQ` 或 `4002`。

## 原理

`get_bm25_index()` 通过 Qdrant `scroll` API 全量拉取 `i2tream_collection` 中所有文档，在内存中构建 BM25 倒排索引。每次调用都需遍历全部 1800+ 文档，耗时约 2-5 秒。

## 改进方向

在 `reload.py` 中增加 BM25 重建逻辑，使 `hermes plugins reload` 时一并刷新。
