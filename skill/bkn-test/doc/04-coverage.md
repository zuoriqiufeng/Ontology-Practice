# ④ 知识覆盖率测试

> 维度：漏没漏 | 优先级: P1 | 可自动化: 半自动

> **Q27 已改口径（2026-10-13）**：**错误码不是覆盖率的分母**——码空间无上界、码不进任何一层（02 号 §0.1②）。
> 覆盖率现在测的是 **8 个有界语义类别**（`plugin/error_semantics.yaml`）与**本体落点的连通率**；
> 原「错误码覆盖率」小节保留为**历史口径**（见附录 A），并标明废止原因。

---

## 评判标准

| 指标 | 计算方式 | 目标阈值 |
|------|---------|:---:|
| **语义类别覆盖率** | 8 个 `dimension:*` 中「有 `diagnosed_by` 边指向 Skill 且 `observed_in` 边指向日志」的个数 / 8 | **= 8 / 8** |
| 分类兜底率 | 随机抽样日志消息文本命中 `error_semantics.yaml` 规则的条数 / 抽样条数 | ≥ 90% |
| 症状覆盖率 | 有本体落点（`suspected_in` / `has_class` 边）的现场症状说法 / 全部登记症状 | ≥ 80% |
| DB 覆盖率 | 有 `dbnode` 对象 + 完整 operations 段的 DB / 支持的 DB 总数 | = 100% |

---

## 测试方法

### 步骤 1：语义类别维度（**不是**错误码维度）

基准 = `plugin/error_semantics.yaml` 的 **8 个有界 `dimension:*`**（不是错误码表——码空间无上界，Q27）。

```python
DIMENSIONS = ["log_readable", "state_machine", "permission", "connectivity",
              "resource", "consistency", "time_sync", "unknown"]   # 与 error_semantics.yaml 同序

# 每个类别至少要能走通一条「类 → Skill → 日志」的链
for dim in DIMENSIONS:
    skills = traverser.get_targets("dimension:" + dim, "diagnosed_by")
    logs   = traverser.get_targets("dimension:" + dim, "observed_in")
    assert skills, "dimension:%s 无 diagnosed_by 边（诊断断了）" % dim
    assert logs,   "dimension:%s 无 observed_in 边（日志入口断了）" % dim
    print(dim, skills, logs)

# 分类兜底率：随机抽 N 条真实日志消息文本，看命中率
hit = sum(1 for msg in sample_messages if classify_error_message(msg)["dimension"])
print("分类兜底率 = %d/%d" % (hit, len(sample_messages)))
```

### 步骤 2：症状×DB 矩阵

生成覆盖矩阵：

```
                    Oracle  MySQL  PG   MSSQL  DB2  DM   OB   YashanDB
incremental_stuck     [✓]    [ ]   [ ]   [ ]   [ ]  [ ]  [ ]    [ ]
data_mismatch         [✓]    [ ]   [ ]   [ ]   [ ]  [ ]  [ ]    [ ]
connection_error      [✓]    [ ]   [ ]   [ ]   [ ]  [ ]  [ ]    [ ]
performance_degrad    [ ]     [ ]   [ ]   [ ]   [ ]  [ ]  [ ]    [ ]
crash_loop           [✓]    [ ]   [ ]   [ ]   [ ]  [ ]  [ ]    [ ]

图例: [✓]=有独立或共享覆盖  [ ]=空白
```

### 步骤 3：Qdrant 条目覆盖审计

检查 110+ 条 Qdrant snippet 的分类分布：

```
维度              条目数   占比    缺口
──────────────────────────────────
全量同步参数        15     14%    -
增量/日志解析       18     16%    -
字符集/类型映射      8      7%    DB2 类型映射少
跨地域/网络优化     10      9%    -
风险/异常处理       20     18%    -
规则配置/装载策略   12     11%    -
性能调优            8      7%    -
源端特定配置        10      9%    DM/OB 少
目标端特定配置       6      5%    ← 偏少
最佳实践/FAQ         3      3%    ← 明显不足
──────────────────────────────────
合计              110    100%
```

### 步骤 4：输出缺口清单

```
覆盖缺口清单
════════════
高优先级（影响诊断正确率）:
  □ DM 数据库增量同步诊断路径缺失
  □ OceanBase 连接错误排查无独立条目
  □ 日志概况分析（全量扫描类请求）无对应 BKN 路径

中优先级:
  □ 最佳实践/FAQ 占比仅 3%，不足以支撑运维参考
  □ 目标端特定配置条目偏少（6%）

低优先级:
  □ DB2/PostgreSQL 类型映射细节可补
```

---

## 执行频率

- 每次 BKN 更新后：自动生成覆盖矩阵
- 每月：审查缺口清单，规划补充优先级
- 新 DB 接入时：覆盖矩阵扩充一行

---

## 附录 A：已废止口径 —— 错误码覆盖率（2026-10-13 废止）

**原口径**：`已覆盖错误码 / Demo Product 全部错误码 ≥ 90`，方法是一张「已知错误码表」逐一调 `diagnose_db_link(error_code=...)` 看有无知识上下文。

**废止原因（三条，任一条即足以废止）**：

1. **分母不存在**——错误码空间无上界（用户裁定 Q27）；所谓「全部错误码」只是当时拿到的那张表，覆盖率随表的大小任意变化，不是可复现的指标。
2. **与本体口径冲突**——Q27 定「码只作入口、不进任何一层」；用码做分母等于把码重新当作知识单位。
3. **实测已失效**——`diagnose_db_link` 现按**日志消息文本**命中语义类别；只给码不给文本时返回 `dimension:unknown`，扫码表只会得到一片 unknown（线上实测：83 条日志模式中 **34 条 `error_codes` 为空**，码本身就不是稳定入口）。

**替代**：见「步骤 1：语义类别维度」——分母换成 8 个有界类别，指标变为**连通率**（类 → Skill → 日志）与**分类兜底率**（抽样消息文本命中率）。
