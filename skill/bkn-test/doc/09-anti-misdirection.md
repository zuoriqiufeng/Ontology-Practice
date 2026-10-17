# ⑨ 防误导性测试（反向测试）

> 维度：有没有带歪 | 优先级: P1 | 可自动化: ❌ 需人工

---

## 评判标准

| 指标 | 计算方式 | 目标阈值 |
|------|---------|:---:|
| 多方向发散率 | BKN 返回的分析方向 ≥ 2 个的案例比例 | ≥ 80% |
| 锁定率 | BKN 仅返回 1 个方向的案例比例 | ≤ 10% |
| 误引导率 | BKN 的首要方向与真实根因不同且无其他方向补正的案例比例 | ≤ 5% |

---

## 核心问题

BKN 的价值是「收窄故障域」，不是「锁定单一答案」。如果 BKN 过于自信地指向一个方向，而这个方向恰好是错的，模型就会被带偏，忽略真正的根因。

```
危险模式:
  症状: connection_error
  BKN → knowledge_context 只说 "VXLAN MTU"  ← 锁定单一方向
  真实根因: 磁盘满 (4003)
  → 模型被带到网络排查，完全忽略磁盘
  → 误诊

安全模式:
  症状: connection_error
  BKN → knowledge_context 说:
    1. 网络层: VXLAN MTU / 防火墙 / Keepalive (可能性 60%)
    2. 资源层: 磁盘空间 / fd 耗尽 (可能性 20%)
    3. DB 层: 连接池 / 会话数 (可能性 20%)
  → 模型有多方向，逐一判断
  → 不会漏掉磁盘
```

---

## 测试方法

### 测试用例设计原则

故意给不完整、模糊或有误导性的输入：

| 场景 | 输入 | 期望 BKN 行为 |
|------|------|-------------|
| 信息缺失 | 仅 error_code=4009，无 symptom | 返回网络/资源/DB 多方向，不锁定 |
| 症状模糊 | "连接失败"，不指定 oracle/mysql | 返回通用网络排查 + 建议确认 DB 类型 |
| 误导向信息 | symptom=connection_error 但实际是磁盘满 | 不排除资源方向 |
| 极端输入 | new_template_broadcast info 级别 | 不升级严重度，不走深度诊断 |
| 同模板重复 | 模板 #89 第 4 次出现 | 不每次生成相同完整分析 |

### 测试用例

```python
adversarial_cases = [
    {
        "name": "只有错误码，无上下文",
        "input": {"error_code": "-4009"},
        "expected": {
            "min_directions": 2,  # 至少 2 个方向
            "must_include": ["网络超时", "资源", "数据库连接"],
            "must_not_lock": True,
        }
    },
    {
        "name": "误导向：连不上 → 实际是磁盘满",
        "input": {"symptom": "connection_error", "db_type": "oracle"},
        "expected": {
            "min_directions": 3,
            "must_include": ["网络", "磁盘/资源", "数据库"],
        }
    },
    {
        "name": "info 级别不应升级",
        "input": {"symptom": "connection_error", "error_code": "info"},
        "expected": {
            "max_severity": "low",
            "should_skip_full_diagnosis": True,
        }
    },
    {
        "name": "不指定 DB 类型",
        "input": {"symptom": "incremental_stuck"},
        "expected": {
            "min_directions": 2,
            "must_include": ["通用排查", "建议确认数据库类型"],
        }
    },
    {
        "name": "冷门 DB (DM 达梦)",
        "input": {"symptom": "data_mismatch", "db_type": "dm"},
        "expected": {
            "min_directions": 1,  # DM 覆盖可能不足，至少别返回 oracle-only 建议
            "must_not_include": ["Oracle redo log", "Oracle ASM"],
        }
    },
]
```

### 判定流程

```python
for case in adversarial_cases:
    result = diagnose_db_link(**case["input"])
    
    checks = {
        "directions_count": count_diagnostic_directions(result.knowledge_context),
        "min_met": checks["directions_count"] >= case["expected"]["min_directions"],
        "includes": all(tag in result.knowledge_context for tag in case["expected"]["must_include"]),
        "excludes": not any(tag in result.knowledge_context for tag in case["expected"].get("must_not_include", [])),
    }
```

---

## 今天已验证的防误导案例

### 案例 1：VXLAN 故障 (#27) ✅

```
输入: symptom=connection_error, db=auto
BKN 返回: 6 个方向 (MTU/防火墙/Keepalive/物理丢包/资源/DB连接)
真实根因: 方向 1 (MTU)
判定: ✅ 多方向发散，没有过早锁定
```

### 案例 2：模板 #89 重复 (#46/#47/#51/#32) ✅

```
输入: new_template_broadcast, info 级别, 模板 #89
BKN 返回: 先判定 iaAgent 测试注入 → 排除 → 结论 LOW
重复触发: 4 次，每次结论一致且正确
判定: ✅ 稳定识别低严重度告警，未升级
```

### 案例 3：YashanDB 异常 ✅

```
输入: YashanDB JDBC SQLExceptionType$8, error
BKN 返回: 多原因列表 (驱动版本 40%/SQL兼容 25%/YStream 15%/...)
判定: ✅ 6 个可能原因，按概率排序，未锁定单一方向
```

---

## 预期输出

```
防误导性测试报告
═══════════════
测试用例数: 5

用例                              方向数  最小要求  锁定?  通过
──────────────────────────────────────────────────────────
只有错误码 -4009                     3       2      否     ✅
误导向 connection_error             4       3      否     ✅
info 级别不升级                    1       1      否     ✅
不指定 DB                          2       2      否     ✅
冷门 DB (DM)                        2       1      否     ✅

通过率: 5/5 (100%)

多方向发散率: 4/5 = 80% (目标 ≥ 80%)
锁定率: 0/5 = 0% (目标 ≤ 10%)
```

---

## 执行频率

- 每次 BKN 结构变更后：全量执行
- 发现诊断错误后：针对该案例补充测试用例
- 每月：例行执行 + 扩充测试用例库
