# ⑧ 搜索结果稳定性测试

> 维度：飘不飘 | 优先级: P0 | 可自动化: ✅

---

## 评判标准

| 指标 | 计算方式 | 目标阈值 |
|------|---------|:---:|
| Jaccard@3 | 3 次执行 top-3 结果集合的交/并比 | ≥ 0.7 |
| Rank Variance | 同一条目在 3 次执行中的排名方差 | ≤ 1.5 |
| Top-1 一致性 | 3 次执行 top-1 相同的比例 | ≥ 80% |

---

## 为什么这个维度重要

如果同一条 query 3 次返回 3 种不同的搜索结果：

```
  执行 #1:  top-3 = [A, B, C]  → LLM 看到 A 的诊断路径
  执行 #2:  top-3 = [C, D, E]  → LLM 看到完全不同的路径
  执行 #3:  top-3 = [B, A, F]  → 又不同
```

模型拿到的诊断依据不一致，结论就会漂移。尤其在 `new_template_broadcast` 这种重复触发场景（模板 #89 今天出现 4 次），如果 4 次搜索返回不同结果，可能 4 次诊断结论互相矛盾。

---

## 测试方法

### 步骤 1：选取测试 query

```python
stability_queries = [
    "DruidDataSource connection pool inited closed Demo Product dumper",
    "Demo Product VXLAN MTU 4001 4009 同步中断 网络",
    "YashanDB SQLExceptionType JDBC 驱动异常",
    "Demo Product 同步延迟增大 oracle redo log 归档",
    "同步规则 停止 可能原因 错误码",
]
```

### 步骤 2：每 query 执行 3 次

```python
for query in stability_queries:
    results = []
    for run in range(3):
        r = search_qdrant(query=query, top_k=5)
        results.append(r)
    
    # 计算 Jaccard@3
    top3_sets = [set(hit["id"] for hit in r[:3]) for r in results]
    intersection = top3_sets[0] & top3_sets[1] & top3_sets[2]
    union = top3_sets[0] | top3_sets[1] | top3_sets[2]
    jaccard = len(intersection) / len(union)
    
    # 计算 Top-1 一致性
    top1_ids = [r[0]["id"] for r in results]
    top1_consistent = len(set(top1_ids)) == 1
    
    # 计算 Rank Variance
    all_ids = union
    rank_variances = {}
    for doc_id in all_ids:
        ranks = []
        for r in results:
            for i, hit in enumerate(r):
                if hit["id"] == doc_id:
                    ranks.append(i)
                    break
            else:
                ranks.append(999)  # 未出现
        rank_variances[doc_id] = variance(ranks)
```

### 步骤 3：统计汇总

```python
avg_jaccard = mean(jaccard_scores)
top1_consistency_rate = sum(top1_consistencies) / len(top1_consistencies)
```

---

## 预期输出

```
Qdrant 稳定性测试报告
════════════════════
测试 query 数: 5
每 query 执行: 3 次

Query                               Jaccard@3  Top-1一致  Avg Rank Var  判定
────────────────────────────────────────────────────────────────────────────
DruidDataSource 连接池                1.00        ✅        0.00         ✅
VXLAN MTU 中断                       0.67        ✅        0.50         ⚠
YashanDB JDBC 异常                   0.50        ❌        2.33         ❌
增量延迟 oracle                       0.75        ✅        0.67         ✅
规则停止                              0.80        ✅        0.33         ✅

平均 Jaccard@3: 0.74 (目标 ≥ 0.7)
Top-1 一致性: 80% (目标 ≥ 80%)

不稳定 query:
  ❌ YashanDB JDBC — 3 次执行 top-3 仅共享 2 条，top-1 不一致
     可能原因: Qdrant 中 YashanDB 相关 snippet 相似度过近，排名波动
     建议: 增加 YashanDB 独特关键词的 snippet，拉开语义距离
```

---

## 稳定性 vs 命中率的关系

```
            高命中率              低命中率
高稳定性    ✅ 理想状态            🔴 知识库一致但不准
           (搜得对，结果稳定)       (需补充正确知识)

低稳定性    🟡 信息冗余             🔴 最差状态
           (搜得对但结果飘)         (需全面重建)
           (精简或加区分度)
```

---

## 执行频率

- 每次 Qdrant 数据变更后：立即执行
- 每周：例行稳定性检查
- 发现命中率下降时：联动检查稳定性
