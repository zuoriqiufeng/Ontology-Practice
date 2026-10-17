# Qdrant 使用经验 (Demo Product 实践)

## 两个集合

| 集合 | 文档数 | 内容 | 搜索优先级 |
|------|--------|------|----------|
| i2tream_collection | 17文档 1220条 | 界面操作手册 + 安装手册 + 实现原理 + 案例PDF | **优先** |
| test_doc_chunks | 2文档 1029条 | 软件配置手册 | 兜底 |

## 关键教训

### 教训 1: 概念定义不要放向量库

Qdrant 擅长"怎么开归档日志"这类操作细节，不擅长"规则是什么"这类概念问题。
概念定义放 term.md（一行搞定），操作细节放 Qdrant。

### 教训 2: BKN 做骨架，Qdrant 填血肉

- BKN risks.bkn 给错误码→诊断链路骨架（3步排查）
- Qdrant 给每步的具体命令（`archive log list`）

不要在 BKN 里写冗长的操作步骤，用 `Qdrant("搜索词")` 标注即可。

### 教训 3: 嵌入模型离线加载

```
HF_HUB_OFFLINE=1 python3
from sentence_transformers import SentenceTransformer
model = SentenceTransformer('BAAI/bge-large-zh-v1.5', device='cpu')
```

BGE-large-zh-v1.5 模型已在本地缓存，需设置 `HF_HUB_OFFLINE=1` 避免网络请求。

### 教训 4: 两个集合搜不到概念

问"规则是什么"：
- i2tream_collection: "规则提交后立即启动" (UI配置)
- test_doc_chunks: "当规则处于停止时..." (操作说明)
- 没有概念定义，term.md 才有
