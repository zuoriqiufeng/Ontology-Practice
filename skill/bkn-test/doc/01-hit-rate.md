# ① Qdrant 命中率测试

> 维度：搜得对不对 | 优先级: P0 | 可自动化: ✅

---

## 评判标准

| 指标 | 计算方式 | 目标阈值 |
|------|---------|:---:|
| Precision@3 | top-3 结果中至少 1 条与期望答案相关的比例 | ≥ 80% |
| MRR (Mean Reciprocal Rank) | 第一个相关结果排名的倒数均值 | ≥ 0.7 |
| NDCG@3 | 归一化折损累计增益，考虑相关度分级 | ≥ 0.6 |

**相关度分级**（人工标注）：
- 3 分：直接命中答案（如查询 DruidDataSource → 返回连接池生命周期说明）
- 2 分：部分相关（如返回 Dumper 组件说明，包含连接池但非主知识点）
- 1 分：微弱相关（如返回数据库连接通用说明）
- 0 分：无关

---

## 测试方法

### 步骤 1：构造测试用例

从真实请求中提取 query，人工标注期望答案：

```python
test_cases = [
    {
        "query": "DruidDataSource connection pool inited closed Demo Product dumper 数据源管理 连接池生命周期",
        "dimension": "组件行为/连接池",
        "expected_tags": ["DruidDataSource", "连接池", "dumper", "生命周期"],
        "min_score": 2,  # 期望至少 2 分相关
    },
    {
        "query": "Demo Product VXLAN MTU 同步中断 连接断开 4001 4009 网络 分片丢弃",
        "dimension": "网络/MTU",
        "expected_tags": ["VXLAN", "MTU", "分片", "4001", "4009"],
        "min_score": 3,  # 核心知识点，应直接命中
    },
    {
        "query": "YashanDB SQLExceptionType JDBC 驱动异常 Demo Product 同步 错误分类",
        "dimension": "源端特定/崖山",
        "expected_tags": ["YashanDB", "JDBC", "驱动", "SQLExceptionType"],
        "min_score": 2,
    },
    {
        "query": "同步规则 停止 可能原因 错误处理策略 连接池耗尽 磁盘空间",
        "dimension": "规则管理/异常处理",
        "expected_tags": ["规则停止", "错误处理", "4000", "4003"],
        "min_score": 2,
    },
    {
        "query": "Demo Product 同步延迟增大 oracle redo log 归档 增量抽取 性能",
        "dimension": "性能/增量",
        "expected_tags": ["延迟", "redo", "归档", "增量", "性能"],
        "min_score": 2,
    },
]
```

### 步骤 2：调用 search_qdrant 回放

```python
# 伪代码
for case in test_cases:
    results = search_qdrant(query=case["query"], top_k=5)
    for i, hit in enumerate(results):
        score = human_judge_relevance(hit, case["expected_tags"])
        # 记录 Precision@3, MRR, NDCG
```

### 步骤 3：人工标注

对每条 query 的 top-5 结果，逐条标注相关度分数（0-3）。

**标注原则**：
- 不要求结果完美匹配所有 expected_tags
- 结果中只要包含诊断所需的核心信息即认为相关
- 如果结果覆盖了 expected_tags 中的 3/5 以上 → 3 分
- 如果覆盖 1-2/5 → 2 分
- 如果只是同领域但未覆盖核心信息 → 1 分

### 步骤 4：计算指标

```python
precision_at_3 = sum(1 for c in test_cases if any(score >= c["min_score"] for score in c["top3_scores"])) / len(test_cases)
mrr = sum(1.0 / (first_relevant_rank(c) + 1) for c in test_cases) / len(test_cases)
```

---

## 执行频率

- 每次 Qdrant 数据更新后（新增/修改 snippet）→ 回归测试
- 每周例行 → 监控漂移
- BKN 版本发布前 → 门禁

---

## 预期输出

```
Qdrant 命中率测试报告
═══════════════════════
测试用例数: N
Precision@3: XX% (目标 ≥ 80%)
MRR: X.XX (目标 ≥ 0.7)

失败用例:
  ✗ "YashanDB SQLExceptionType..." → top-3 均未提及 JDBC 驱动
    根因: Qdrant 中缺少 YashanDB JDBC 异常分类的知识条目
    建议: 补充 snippet

趋势: 较上次 (↑2% / ↓5% / →)
```
