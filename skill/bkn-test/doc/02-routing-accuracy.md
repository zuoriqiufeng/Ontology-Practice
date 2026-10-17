# ② 路由准确度测试

> 维度：指的方向对不对 | 优先级: P3 | 可自动化: ✅

---

## 评判标准

| 指标 | 计算方式 | 目标阈值 |
|------|---------|:---:|
| 路由准确率 | `diagnose_db_link` 返回的 `knowledge_context` 是否包含对应症状的正确诊断方向 | ≥ 90% |
| Skill 匹配率 | 推荐的 primary Skill 是否与最佳诊断 Skill 一致 | ≥ 85% |

---

## 测试方法

### 步骤 1：构造路由测试矩阵

覆盖全部 5 种症状 × 5 种数据库类型：

```
                 Oracle   MySQL   PostgreSQL  SQLServer   DB2
incremental_stuck   ✓        ✓         ✓          ✓        ✓
data_mismatch       ✓        ✓         ✓          ✓        ✓
connection_error    ✓        ✓         ✓          ✓        ✓
performance_degrad  ✓        ✓         ✓          ✓        ✓
crash_loop          ✓        ✓         ✓          ✓        ✓
```

### 步骤 2：逐组合调用 diagnose_db_link

```python
for symptom in ["incremental_stuck", "data_mismatch", ...]:
    for db_type in ["oracle", "mysql", "postgresql", ...]:
        result = diagnose_db_link(symptom=symptom, db_type=db_type)
        
        checks = {
            "knowledge_context 非空": len(result.knowledge_context) > 0,
            "recommended_skill 存在": result.recommended_skill is not None,
            "不推荐不相关 Skill": not any(s for s in result.recommended_skills if is_irrelevant(s, symptom, db_type)),
        }
```

### 步骤 3：人工判定路由是否正确

对每个组合，确认：
- `knowledge_context` 中的诊断方向是否覆盖了该 DB 类型该症状的典型根因
- 推荐的 Skill 是否是该场景的最优诊断入口

**判定示例**：

```
输入: symptom=connection_error, db_type=oracle, error_code=-4001
期望: knowledge_context 提到「VXLAN/MTU/网络中断/Keepalive」
      + primary_skill = demo-product-db-diagnostics
实际: 按上述检查项逐项核对
结果: ✓ PASS / ✗ FAIL
```

---

## 预期输出

```
路由准确度测试报告
══════════════════
总组合数: 25 (5 症状 × 5 DB)
正确路由: XX/25 (XX%)

失败明细:
  ✗ incremental_stuck × DB2 → knowledge_context 缺少 DB2 日志解析方向
  ✗ crash_loop × PostgreSQL → 推荐了 oracle-only 的 Skill

缺口: DB2 和 PostgreSQL 的覆盖需要补充
```
