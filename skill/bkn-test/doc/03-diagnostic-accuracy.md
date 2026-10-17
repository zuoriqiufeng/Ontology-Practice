# ③ 端到端诊断准确率测试

> 维度：结论对不对 | 优先级: P3 | 可自动化: ❌ 需人工

---

## 评判标准

| 指标 | 计算方式 | 目标阈值 |
|------|---------|:---:|
| 诊断正确率 | BKN 辅助下的最终诊断结论与已知正确答案一致的比例 | ≥ 85% |
| 严重度判定准确率 | 输出的 severity_assessment 与实际严重度一致 | ≥ 90% |
| 假阳性率 | 将非故障判定为故障的比例 | ≤ 5% |
| 假阴性率 | 将故障判定为非故障的比例 | ≤ 3% |

---

## 测试方法

### 步骤 1：收集真实案例

从 API Server 历史会话中提取已完成诊断的案例，建立"病例库"：

```python
cases = [
    {
        "id": "api-f47bfff25d336ab8",
        "date": "2026-07-14",
        "symptom": "VXLAN 环境下数据刚开始发很快就断",
        "bkn_conclusion": {
            "root_cause": "VXLAN MTU 过大导致大包分片",
            "severity": "high",
            "directions": ["MTU", "Keepalive", "防火墙超时", "物理丢包", "资源", "DB连接"],
        },
        "ground_truth": {
            "root_cause": "VXLAN MTU 过大导致大包分片",
            "severity": "high",
            "fix": "降 VXLAN MTU 至 1400 + 调 TCP Keepalive",
        },
        "match": True,  # BKN 结论与 ground_truth 是否一致
    },
    {
        "id": "api-70cf140ab468bcd7",
        "date": "2026-07-15",
        "symptom": "new_template_broadcast 模板 #89 DruidDataSource inited/closed",
        "bkn_conclusion": {
            "root_cause": "Druid 连接池正常生命周期，模板首次注册",
            "severity": "low",
        },
        "ground_truth": {
            "root_cause": "连接池正常行为，非故障",
            "severity": "low",
        },
        "match": True,
    },
    # ... 更多案例
]
```

### 步骤 2：人工标注 ground_truth

每条案例的 ground_truth 来源：
- 已验证的修复方案（如 VXLAN MTU 案例已实际修复）
- 数据库端确认（如 YashanDB yasql 可连，排除网络问题）
- 专家经验判断

### 步骤 3：计算指标

```python
correct = sum(1 for c in cases if c["match"])
accuracy = correct / len(cases)

severity_correct = sum(1 for c in cases if c["bkn_conclusion"]["severity"] == c["ground_truth"]["severity"])
severity_accuracy = severity_correct / len(cases)

false_positive = sum(1 for c in cases 
    if c["bkn_conclusion"]["severity"] in ["high","critical"] 
    and c["ground_truth"]["severity"] in ["low","info"])
false_positive_rate = false_positive / len(cases)
```

### 步骤 4：分类统计

按告警类型分组，找出薄弱环节：

```
              案例数   正确    正确率
new_template    10      9      90%
日志概况         3      2      67%  ← 薄弱
直接诊断         5      5     100%
```

---

## 当前基线（2026-07-15）

基于今天 5 个已处理的典型案例：

| 案例 | 诊断结论 | 实际 | 命中 |
|------|---------|------|:---:|
| #27 VXLAN 断连 | MTU + Keepalive，6 方向 | 正确 | ✅ |
| #46 模板 #89 | LOW，连接池正常 | 正确 | ✅ |
| #47 模板 #89 | LOW，同 #46 | 正确 | ✅ |
| #49 日志概况 | 异常率 13.67%，IaUtil 十六进制解码 | 待验证 | — |
| #51 模板 #89 | LOW，同前 | 正确 | ✅ |

模板 #89 类案例 4/4 正确（100%），日志概况类只有 1 例，样本不足。

---

## 执行频率

- 每周：回顾当周案例，更新病例库
- 每月：计算准确率趋势
- BKN 大版本更新后：全量回归
