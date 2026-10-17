# BKN + Qdrant 集成模式

> BKN 提供结构推理，Qdrant 提供内容细节。两者互补。

---

## 三种集成模式

### 模式 1: BKN 做索引，Qdrant 做详情

```
用户: "Oracle 同步到 OB 源端要配什么？"
  │
  ▼ BKN 匹配: database.bkn §OracleSource
  │ 返回: 归档日志 + 附加日志 + 强制写日志
  │
  └── 如果需要详细步骤 → Qdrant 检索
      "Oracle 开启归档日志 ALTER DATABASE ARCHIVELOG"
```

### 模式 2: BKN 做过滤，Qdrant 做内容

```
用户: "track 报错怎么排查？"
  │
  ▼ BKN: Risk -4073 → 排查步骤 [查节点, 查归档, 查日志]
  │
  └── 每步去 Qdrant 语义检索对应章节
      "工作节点在线状态检查" → chunk #11 (界面手册§1.2)
      "Oracle归档日志查询"   → chunk #156 (配置手册§3.1)
```

### 模式 3: BKN 做路由，Qdrant 做答案

```
用户: "什么是 iatrack"
  │
  ▼ BKN: 术语→term.md → 基本定义
  │
  └── 需要深入实现原理 → Qdrant
      "iatrack 增量解析 C++ 原理"
```

---

## BKN 文件中嵌入 Qdrant 引用的格式

```markdown
Risk: -4073 (源端日志不可读)
  排查步骤:
    step1: 查节点在线 → Qdrant("工作节点在线状态检查")
    step2: 查归档日志 → Qdrant("Oracle 归档日志检查 开启archivelog")
    step3: 查 iahelper 日志 → Qdrant("iahelper 日志查看方法")
```

Agent 流程: 读 BKN → 看到 Qdrant("关键词") → 按关键词搜索 Qdrant → 返回原文。

---

## 两者的关系

| | BKN | Qdrant |
|------|-----|--------|
| 给什么 | 结构、推理路径 | 内容、操作步骤 |
| 查法 | search_files (关键词) | 向量语义检索 |
| 成本 | ~150 token | ~500 token |
| 适合 | 知道查什么 | 需要详细原文 |

**BKN 给骨架，Qdrant 填血肉。**

## Qdrant 集合选择

Demo Product 有两个向量集合，按内容覆盖度排序：

| 集合 | 点数 | 内容 |
|------|------|------|
| `i2tream_collection` | 1220 | **优先**: 界面操作手册 + 安装手册 + 使用指引 + 案例 PDF (17文件) |
| `test_doc_chunks` | 1029 | **兜底**: 软件配置手册 (2文件) |

Agent 做 Qdrant 检索时先搜 `i2tream_collection`，无结果再回落 `test_doc_chunks`。
