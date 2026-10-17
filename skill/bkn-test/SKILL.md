---
name: bkn-test
description: |
  Demo Product BKN 效果评估体系 — 10 维度测试框架。当用户要求评估 BKN/知识库/搜索效果、
  设计测试方案、做质量审计、或问「BKN 效果如何」「怎么测」时使用。
triggers:
  - "BKN 效果"
  - "BKN 测试"
  - "效果评估"
  - "知识库质量"
  - "搜索效果"
  - "Qdrant 命中率"
  - "BKN 审计"
  - "测试维度"
  - "覆盖率"
tools_used:
  - search_qdrant
  - diagnose_db_link
  - write_file
  - search_files
---

# Demo Product BKN 效果评估体系

> BKN = Business Knowledge Network (骨架 .bkn + Qdrant 向量 + Skill)
> 测试文档: `doc/`（Skill 子目录）

## 速览

- **10 维度测试框架**，分四层（基础 → 诊断 → 覆盖 → 优化 ＋ **本体结构合规**）
- P0（自动化优先）：命中率 + 稳定性
- P1（质量底线）：覆盖率 + 防误性
- P2（持续优化）：Token 效率 + 时效性
- P3（精益求精）：互补性 + 路由 + 准确率
- **P0′（机检，零成本）**：本体结构合规（⑩）——%%BT%%lint_bkn.py%%BT%% + %%BT%%scripts/gate.sh%%BT%% 已是现成门禁，**不需要人工造用例**

## 决策树

```
用户说「BKN 效果怎么样」
  │
  ├─ 要快速评估 → 跑 P0（命中率 + 稳定性）
  │   └─ 参考: 01-hit-rate.md + 08-stability.md
  │
  ├─ 要质量审计 → P0 + P1（命中率 + 稳定性 + 覆盖率 + 防误性）
  │   └─ 参考: + 04-coverage.md + 09-anti-misdirection.md
  │
  ├─ 要优化建议 → P2（效率 + 时效性）
  │   └─ 参考: 05-freshness.md + 06-token-efficiency.md
  │
  ├─ 改过本体 / 要做发布前门禁 → 跑 P0′（本体结构合规，机检）
  │   └─ 参考: 10-ontology-structure.md
  │
  └─ 要完整评估 → 全部 10 维度
      └─ 参考: 00-overview.md
```

## 10 维度速查

| # | 维度 | 核心问题 | 指标 | 阈值 | 文档 |
|:--:|------|---------|------|:---:|------|
| ① | 命中率 | 搜得对不对 | Precision@3 | ≥80% | 01-hit-rate.md |
| ⑧ | 稳定性 | 飘不飘 | Jaccard@3 | ≥0.7 | 08-stability.md |
| ② | 路由率 | 指的方向对不对 | 路由准确率 | ≥90% | 02-routing-accuracy.md |
| ③ | 准确率 | 结论对不对 | 诊断正确率 | ≥85% | 03-diagnostic-accuracy.md |
| ⑨ | 防误性 | 有没有带歪 | 多方向发散率 | ≥80% | 09-anti-misdirection.md |
| ④ | 覆盖率 | 漏没漏 | **语义类别覆盖**（8 个 %%BT%%dimension:*%%BT%%；**不是错误码覆盖**——码空间无上界，Q27） | =8/8 | 04-coverage.md |
| ⑤ | 时效性 | 旧不旧 | 矛盾条目 | =0 | 05-freshness.md |
| ⑥ | 效率 | 省没省 | Token 回报率 | ≥1.0x | 06-token-efficiency.md |
| ⑦ | 互补性 | 1+1>2? | 互补分数 | ≥0.7 | 07-complementarity.md |
| ⑩ | **本体结构合规** | 骨架立得住吗 | lint 错误数 / 门禁道数 / 结构量单调 / 版本身份 | 0 error · 4/4 门 · 只增不减 | 10-ontology-structure.md |

## 测试文档结构

```
doc/
├── 00-overview.md             # 总览 + 优先级矩阵
├── 01-hit-rate.md             # ① 命中率 (P0)
├── 08-stability.md            # ⑧ 稳定性 (P0)
├── 04-coverage.md             # ④ 覆盖率 (P1)
├── 09-anti-misdirection.md    # ⑨ 防误性 (P1)
├── 05-freshness.md            # ⑤ 时效性 (P2)
├── 06-token-efficiency.md     # ⑥ Token 效率 (P2)
├── 02-routing-accuracy.md     # ② 路由率 (P3)
├── 03-diagnostic-accuracy.md  # ③ 准确率 (P3)
├── 07-complementarity.md      # ⑦ 互补性 (P3)
└── 10-ontology-structure.md   # ⑩ 本体结构合规 (P0′，机检)
```

每个文档含：评判标准（量化指标+阈值）、测试方法（步骤+伪代码）、预期输出样例、执行频率。

## 快速开始

1. 读 `00-overview.md` 了解全貌
2. 跑 P0 测试（命中率 + 稳定性）了解当前基线
3. 生成 P1 覆盖矩阵找缺口
4. 每月做一次 P2 效率 + 时效性审计

## 防坑

- 测试不替代人工判断。P3 的准确率/路由率需要专家标注 ground truth
- 稳定性测试必须同 query 多次执行（3 次），单次结果不能判定是否漂移
- 覆盖率的「已覆盖」不等于「覆盖得好」——命中率才是质量指标
- **覆盖率的分母是 8 个 %%BT%%dimension:*%%BT%% 语义类别，不是错误码表**——错误码空间无上界（Q27），拿码当分母会得到一个永远算不准的分数；权威 = %%BT%%plugin/error_semantics.yaml%%BT%%
- ⑩ 是**唯一可以全自动、无人工标注**的维度（跑命令看退出码）；但它只证「骨架立得住」，**不证**「答得对」——别用它替代 P3
- 防误性测试用例要故意构造误导性输入，不是正常流程

---

## References

- [retrieval-quality-evaluation.md](references/retrieval-quality-evaluation.md) — 检索质量评估：双维四象限（精度 × 覆盖）+ 会话去重 + 噪声模式（属评估域，非 Plugin 机制域）
