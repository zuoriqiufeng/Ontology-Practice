# ⑦ 互补性测试（骨架 vs 快照）

> 维度：1+1>2? | 优先级: P3 | 可自动化: ✅

---

## 评判标准

| 指标 | 计算方式 | 目标阈值 |
|------|---------|:---:|
| 互补分数 | (BKN独有的信息 + Qdrant独有的信息) / 总信息 | ≥ 0.7 |
| 冗余率 | BKN和Qdrant都提供的信息 / 总信息 | ≤ 0.3 |

---

## 核心概念

BKN 提供**结构型知识**，Qdrant 提供**数据型知识**：

```
BKN skeleton (diagnose_db_link.knowledge_context):
  → 诊断方向：先查什么、后查什么
  → 风险上下文：可能违反的约束
  → Skill 路由：用哪个 Skill
  → 类型：结构、流程、决策树

Qdrant snippets (search_qdrant):
  → 具体参数值："tcp_keepalive_time=5"
  → 配置示例："INSERT INTO... ON CONFLICT..."
  → 案例细节："某银行 VXLAN 部署中 MTU 设为 1350"
  → 类型：数值、命令、案例
```

理想状态：两者信息**正交**——BKN 说"查网络 MTU"，Qdrant 说"MTU 建议 1400"。

**失败状态**：BKN 和 Qdrant 在说同一件事，没有信息增量。

---

## 测试方法

### 步骤 1：选取 N 个典型 query

```python
queries = [
    "Demo Product VXLAN 同步中断 oracle",
    "DruidDataSource 连接池 inited closed dumper",
    "YashanDB JDBC 异常 SQLExceptionType",
    "同步规则停止 oracle 错误码",
    "增量延迟 oracle redo log 归档",
]
```

### 步骤 2：分别获取两路结果

```python
for query in queries:
    # BKN 骨架
    bkn_result = diagnose_db_link(symptom=map_to_symptom(query), db_type=map_to_db(query))
    bkn_info = extract_facts(bkn_result.knowledge_context)
    
    # Qdrant 快照
    qdrant_result = search_qdrant(query=query, top_k=5)
    qdrant_info = extract_facts_from_snippets(qdrant_result)
```

### 步骤 3：计算信息重叠

```python
def calc_complementarity(bkn_info, qdrant_info):
    bkn_only = bkn_info - qdrant_info    # BKN 独有
    qdrant_only = qdrant_info - bkn_info  # Qdrant 独有
    overlap = bkn_info & qdrant_info      # 重叠
    
    total = bkn_only | qdrant_only | overlap
    complementarity = len(bkn_only | qdrant_only) / len(total)
    redundancy = len(overlap) / len(total)
    
    return complementarity, redundancy
```

**示例分析**：

```
Query: "VXLAN MTU 同步中断"

  BKN skeleton 提供:
    - 排查方向: MTU → Keepalive → 防火墙 → 物理网络 → 资源 → DB
    - 风险: VXLAN 封装 +50B 开销
    - Skill 推荐: demo-product-db-diagnostics
    [结构型知识]

  Qdrant snippets 提供:
    - MTU 建议值: 1400
    - TCP Keepalive 参数: 5/5/9
    - 错误码: 4001/4009
    - 命令: ip link set dev vxlan0 mtu 1400
    [数据型知识]

  重叠: "VXLAN", "MTU" (关键词层面)
  互补分数: (4 BKN独特 + 4 Qdrant独特) / 9 ≈ 0.89 ✅
```

### 步骤 4：冗余检测

如果某条 query 的互补分数 < 0.5：

```
问题: BKN 和 Qdrant 信息高度重叠
原因:
  - Qdrant 中的 snippet 直接复制了 BKN 的风险描述文本
  - BKN skeleton 中掺入了具体参数值（应该留给 Qdrant）
修复:
  - 精简 BKN，去掉具体数值，只保留方向
  - 或精简 Qdrant，去掉纯结构型描述
```

---

## 预期输出

```
互补性测试报告
═════════════
测试 query 数: 5

Query                          互补分数   冗余率   判定
─────────────────────────────────────────────────────
VXLAN 同步中断                   0.89      0.11     ✅
DruidDataSource 连接池           0.72      0.28     ✅
YashanDB JDBC 异常               0.45      0.55     ⚠ 冗余
规则停止 oracle                  0.78      0.22     ✅
增量延迟 oracle                  0.83      0.17     ✅

平均互补分数: 0.73 (目标 ≥ 0.7)
问题 query: YashanDB JDBC — BKN skeleton 和 Qdrant 都侧重"版本兼容性"，缺少互补信息
```
