
# supplement.py Decompose 自动检索机制与失效分析

## 机制概述

当 `design_solution(source="Oracle", target="DB2")` 返回 `confidence=partial` 时，`supplement.py` 的 `fallback_to_qdrant()` 自动触发多维度分解检索。

## 9 维度分解查询模板（design_solution）

源码位置: `plugin/supplement.py` 第 402-412 行

| 维度 | 查询模板 |
|------|----------|
| 字符集/类型映射 | `{s}到{t} 字符集转换 数据类型映射 字段长度 注意事项` |
| 全量同步参数 | `全量同步 大表拆分 导出线程 装载线程 表覆盖策略 单表拆分` |
| 增量/日志解析 | `{s} 增量同步 日志解析 CDC 配置要求` |
| 断点续传/容错 | `断点续传 checkpoint LSN 中断恢复 错误处理 冲突处理` |
| 数据校验/对比 | `数据校验 整库对比 表对比 一致性检查 差异修复` |
| 源端特定配置 | `{s} 数据库配置 编目 编码 环境要求 Demo Product部署` |
| 目标端特定配置 | `{t} 同步 配置 字符集 用户授权 环境要求` |
| 跨地域/网络优化 | `跨地域 异地同步 网络优化 压缩 带宽 延迟 批量提交` |
| 风险/异常处理 | `{s} {t} 同步 风险 异常 常见错误 故障排查` |

每条子查询: BGE 向量 + BM25 稀疏 → RRF 融合 → `SEARCH_DECOMPOSE_TOP_K`(默认5条) → 9路聚合去重 → 双维质量评估

## 质量评估四象限

| 象限 | relevance | completeness | 处理策略 |
|------|-----------|-------------|----------|
| ① 充分可信 | ≥0.55 | ≥0.50 | enrichment + 强制消费 |
| ② 部分可用 | ≥0.55 | <0.50 | enrichment 保留 + 标注缺失维度 |
| ③ 高量低质 | <0.55 | ≥0.50 | fallback_hint + 噪声警告 |
| ④ 低相关低完备 | <0.55 | <0.50 | **不可靠，仅参考** |

## 典型失效案例: Oracle → DB2

实测: relevance=0.20, completeness=0.27 → 象限④

**失效根因分析:**

1. **完备度低 (0.27)**: 9 维度中仅「字符集/类型映射」被覆盖，其余 8 维返回空或噪声。Qdrant 中 DB2 侧、跨地域优化的内容稀疏。

2. **相关度低 (0.20)**: 
   - 关键词命中率低: 泛化词如 "DB2 同步 配置 字符集" 的 BGE 向量与 Qdrant 内容语义距离远
   - 噪声率 40%: 2/5 条结果是其他 DB (DM/PostgreSQL) 的配置文档
   - 相似度分数: 最高仅 0.655

**外部分散查询为何有效:**

| 内部泛化查询 | 外部精确查询 | 命中效果 |
|-------------|-------------|---------|
| `DB2 同步 配置 字符集` | `db2set DB2CODEPAGE=1386 编码` | 精确命中 DB2 编码命令 |
| `Oracle 数据库配置 编目` | `DB2 编目 catalog tcpip node` | 精确命中 catalog 命令 |
| `全量同步 大表拆分 导出线程` | `全量装载线程数 建议改成4和8` | 命中具体建议值 |

## 应对策略

**当 `design_solution` 返回 LOW_CONFIDENCE 时:**

1. 检查 `quality.missing_dims` — 确认哪些维度未被覆盖
2. 外部 qdrant_search.py 查询时，**用精确命令/参数名而非泛化话题描述**
3. 参考 Qdrant 中已知存在的文档内容反推查询词（已知有 `db2set`、`catalog tcpip`、`dbrule.conf` 等）
4. 每个 missing dimension 单独构造 1-2 条精确查询，而非合并

## 配置阈值

```yaml
# config.yaml
search:
  decompose: true
  decompose_top_k: 5
  decompose_max: 9
  decompose_min: 3
  decompose_dedup: 90
  quality_enable: true
  quality_relevance_threshold: 0.55
  quality_completeness_threshold: 0.50
```
