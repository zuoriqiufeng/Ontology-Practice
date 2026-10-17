# ⑤ 时效性/一致性审计

> 维度：旧不旧 | 优先级: P2 | 可自动化: 半自动

---

## 评判标准

| 指标 | 计算方式 | 目标阈值 |
|------|---------|:---:|
| 矛盾率 | 矛盾条目数 / 总可验证条目数 | = 0% |
| 过期率 | 包含过时信息的条目 / 总条目数 | ≤ 5% |
| 上次审计距今 | 天数 | ≤ 30 天 |

---

## 测试方法

### 审计项 1：同主题跨文件交叉对比

搜索同一事实在不同 BKN 文件中的表述，检查是否矛盾：

```
检查项: Oracle supplemental log 要求

  bkn/objects/database.bkn        → "需要 SUPPLEMENTAL_LOG_DATA_MIN=YES, PK=YES"
  bkn/actions/rule_lifecycle.bkn  → "需要 supplemental log，min+pk"

  → 表述一致 ✓
```

```
检查项: TCP Keepalive 建议值

  风险 constraints.bkn      → "tcp_keepalive_time=5"
  场景 topology-patterns   → 未提及

  → 无矛盾，但 topology-patterns 可补 ✓
```

### 审计项 2：版本时效性

逐条检查包含版本号的事实断言：

```python
versioned_facts = [
    {
        "file": "bkn/objects/database.bkn",
        "claim": "Demo Product 支持 YashanDB 23.4.1.102",
        "latest_known": "23.4.1.102",  # 需与 Demo Product release notes 对比
        "status": "current"
    },
    {
        "file": "bkn/objects/product.bkn",
        "claim": "Oracle 支持 11gR2 ~ 19c",
        "latest_known": "23c 已发布",
        "status": "may_be_stale"  # 需确认
    },
]
```

### 审计项 3：错误码映射完整性

```python
# 检查 BKN 中的错误码列表是否与实际日志中出现的错误码一致
bkn_error_codes = extract_error_codes_from_bkn()
observed_error_codes = extract_error_codes_from_logs()
missing = observed_error_codes - bkn_error_codes
stale = bkn_error_codes - observed_error_codes  # BKN 有但从未出现在日志中
```

### 审计项 4：与官方文档对比

```python
checklist = [
    ("BKN 中 Demo Product 架构描述", "Demo Product 最新产品文档"),
    ("BKN 中 DB 支持列表", "Demo Product 兼容性矩阵"),
    ("BKN 中最佳实践参数", "Demo Product 官方调优指南"),
]
```

---

## 预期输出

```
BKN 时效性审计报告
═════════════════
审计日期: 2026-07-15
上次审计: 首次

矛盾条目: 0  ← 目标 0
过期条目: 2
  ⚠ bkn/objects/product.bkn: Oracle 支持版本只写到 19c，23c 未更新
  ⚠ bkn/objects/database.bkn: 引用的 dumpredo 参数描述与最新版不一致（命令细节归 Skill）

建议操作:
  1. 更新 Oracle 版本支持范围至 23c
  2. 与 Demo Product 9.1.4Beta dumpredo 文档同步参数描述
```

---

## 执行频率

- 每月：全量审计
- Demo Product 新版本发布后：版本时效性专项审计
- BKN 每次大更新后：交叉对比
