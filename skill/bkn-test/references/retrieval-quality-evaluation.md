# 检索质量评估与降权机制实现 (v2.3, 2026-07-03 最终落地)

## 问题背景

v2.2 的 `_instruction` 机制无条件强制模型消费 Qdrant enrichment。当 Qdrant 内容相关但覆盖不全（如 MySQL→Oracle 迁移：Oracle 授权完整，MySQL binlog 完全缺失），模型被要求"同等对待"，但缺失部分没有信号告知。同时 10+ 个 Tool 调用中相同 Oracle 授权 SQL 被重复灌入。

## 双维四象限评估模型

```
          完备度 ≥ 0.6
              │
  象限③        │      象限①
 "高量低质"     │     "充分可信"
 noise 警告     │     enrichment + CRITICAL _instruction
              │
相关度 < 0.6 ──┼──────── 相关度 ≥ 0.6
              │
  象限④        │      象限②
 "不可信"       │     "部分可用"
 fallback_hint  │     enrichment + PARTIAL _instruction
              │            + missing_dims 标注
          完备度 < 0.6
```

## 实施文件

| 文件 | 改动 | 行数变化 |
|------|------|---------|
| `config.yaml` | +5行，新增 quality_enable/quality_relevance_threshold/quality_completeness_threshold/quality_session_dedup | 45→50 |
| `config.py` | +5行，加载 SEARCH_QUALITY_ENABLE / SEARCH_QUALITY_RELEVANCE_THRESHOLD / SEARCH_QUALITY_COMPLETENESS_THRESHOLD / SEARCH_QUALITY_SESSION_DEDUP | 86→91 |
| `supplement.py` | +260行，新增 assess_qdrant_quality() + _content_hash() + _SESSION_SEEN + _NOISE_PATTERNS + _DIM_NAMES，重写 fallback_to_qdrant() | 653→946 |

## 核心函数：assess_qdrant_quality()

```python
def assess_qdrant_quality(hits, gaps, args, queries, tool_name) -> dict:
    """双维质量评估: 相关度(relevance) + 完备度(completeness)
    Returns: {relevance, completeness, covered_dims, missing_dims, noise_count}
    """
```

### 相关度 (Relevance) 指标

| 子指标 | 权重 | 计算方式 |
|--------|------|---------|
| 关键词命中率 | 0.4 | hits 中 **content + _query 联合匹配** source/target/error_code 的比例 |
| 向量分数分布 | 0.4 | score >= score_threshold(0.3) 的命中占比 |
| 反噪声比例 | 0.2 | 1 - (命中噪声模式且不含 source/target 的比例) |

### 完备度 (Completeness) 指标

| 子指标 | 权重 | 计算方式 |
|--------|------|---------|
| 维度覆盖率 | 0.4 | decompose 各维度 query 有 >=1 条命中的比例 |
| Gap 覆盖率 | 0.4 | BKN gaps 关键词在 hits 文字中出现的比例 |
| 唯一内容量 | 0.2 | min(去重字符数 / 600, 1.0) |

## 噪声模式识别 (_NOISE_PATTERNS)

```python
_NOISE_PATTERNS = [
    "PostgreSQL", "Postgres", "psql", "public schema",
    "search_path", "DM同步规则", "ClickHouse", "MongoDB",
]
```

命中任一模式且 hit 的 (content + _query) 不含 source/target 关键词 → 标记为噪声。噪声比例计入 relevance 的 20% 权重。

## 维度名映射表 (_DIM_NAMES)

将 decompose 子查询的维度 key 映射到人类可读的标签，用于在 `_instruction` 中输出 `covered_dims` / `missing_dims`：

```python
_DIM_NAMES = {
    # design_solution (9维)
    "字符集": "字符集/类型映射",
    "全量同步参数": "全量同步参数",
    "增量": "增量/日志解析配置",
    "断点续传": "断点续传/容错",
    "数据校验": "数据校验/对比",
    "源端特定配置": "源端特定配置(Mysql)",    # ← 参数化: 当时 source=MySQL
    "目标端特定配置": "目标端特定配置(Oracle)",  # ← 参数化: 当时 target=Oracle
    "跨地域": "跨地域/网络优化",
    "风险": "风险/异常处理",
    # check_compatibility (3维)
    "版本要求": "源端版本要求",
    "配置要求": "目标端配置要求",
    "数据类型映射": "数据类型映射",
    # diagnose_error (3维)
    "错误原因": "错误原因",
    "修复步骤": "修复步骤",
    "操作约束": "操作约束",
    # explain_architecture (3维)
    "原理机制": "原理机制",
    "配置调优": "配置调优",
    "异常场景": "异常场景",
    # get_prerequisites (3维)
    "环境要求": "环境要求",
    "权限配置": "权限配置",
    "参数验证": "参数验证",
    # list_scenarios (3维)
    "迁移场景": "迁移场景",
    "容灾场景": "容灾场景",
    "大数据场景": "大数据场景",
    # resolve_relation (2维)
    "实体关系": "实体关系",
    "关联约束": "关联约束",
}
```

## 四象限降权策略 (fallback_to_qdrant 内)

```python
R = 0.6  # quality_relevance_threshold
C = 0.6  # quality_completeness_threshold

if relevance >= R and completeness >= C:
    # 象限① 充分可信
    result["enrichment"] = {...}
    result["confidence"] = "full"
    result["_instruction"] = "CRITICAL: enrichment 优先级 ≥ BKN, 必须提取"

elif relevance >= R and completeness < C:
    # 象限② 部分可用 ← MySQL→Oracle 落这里
    result["enrichment"] = {...}
    # 不设 confidence=full, 保持 partial
    result["_instruction"] = (
        f"PARTIAL: relevant({relevance:.2f}) but incomplete({completeness:.2f}). "
        f"Covered: {covered_dims}. MISSING: {missing_dims}. "
        "保留enrichment中已覆盖维度, 缺失维度用模型知识补"
    )

elif relevance < R and completeness >= C:
    # 象限③ 高量低质
    result["fallback_hint"] = f"大量但无关(relevance={relevance:.2f}, 噪声比={noise_ratio:.2f})"
    result["_instruction"] = "NOISE: enrichment不可靠, 以BKN骨架为准"

else:
    # 象限④ 低相关低完备
    result["fallback_hint"] = f"低质量(relevance={relevance:.2f}, completeness={completeness:.2f})"
    result["_instruction"] = "UNRELIABLE: 相信BKN骨架和自己知识"
```

## 会话级跨调用去重

```python
_SESSION_SEEN = set()

def _content_hash(content: str) -> str:
    return hashlib.md5(content[:200].encode("utf-8")).hexdigest()

# 在 fallback_to_qdrant 中, _aggregate_results 之后:
fresh_hits = []
dup_count = 0
for h in hits:
    ch = _content_hash(h.get("content", ""))
    if ch not in _SESSION_SEEN:
        _SESSION_SEEN.add(ch)
        fresh_hits.append(h)
    else:
        dup_count += 1
if dup_count > 0:
    dedup_note = f"{dup_count}/{len(hits)} hits 与之前调用重复 (保留{len(fresh_hits)}条新内容)"
hits = fresh_hits
```

**去重效果验证**（模拟3次连续 Tool 调用，5条/次）：

| 调用 | 去重前 | 重复 | 保留新内容 |
|------|--------|------|-----------|
| 第1次 | 3 | 0 | 3 (全部新: Oracle授权×2 + audit_trail) |
| 第2次 | 3 | 1 | 2 (Oracle授权重复×1, sys.obj$授权×1新, 连接配置×1新) |
| 第3次 | 3 | 2 | 1 (Oracle授权重复×2, MySQL binlog配置×1新) |

## 验证结果 (MySQL→Oracle 场景模拟)

```
输入: 5个hits (4个Oracle授权SQL + 1个PG psql噪声)
      source=MySQL, target=Oracle, 8个decompose维度

输出:
  相关度: 0.88  ← Oracle授权被正确识别为相关 (含_query标签匹配)
  完备度: 0.07  ← 8维度仅命中1个(字符集/类型映射)
  噪声数: 1     ← PG psql被_NOISE_PATTERNS捕获
  归类: 象限② 部分可用

_instruction 效果:
  → enrichment 保留 Oracle 授权内容 (有用,不丢)
  → 明确告知: MISSING=[增量/日志解析, 断点续传, 数据校验, 源端配置MySQL, 跨地域/网络, 风险/异常]
  → 模型用自己的知识补 MySQL binlog 等缺失维度
```

## ✗ v2.3 救援Bug: keyword_rate 漏判 (已修复)

**现象**: 首次实现 keyword_rate 仅检查 `h['content']`。Oracle SQL 如 `create user i2 identified by i2` 字面不含 "oracle" → 相关度 0.48 → 错误归入象限④（预期象限②）。

**修复**: 改为联合检查 `h['content'] + h['_query']`。`_query` 标签含 "Oracle 同步 配置 字符集 用户授权" → 相关度 0.48→0.88。

**教训**: 检索命中片段可能不包含数据库类型关键词（SQL是通用的），但 _query 标签（由 decompose template 生成）必然包含源/目标类型信息。**凡涉及内容相关性判断，必须同时检查 _query 标签。**

## 配置 (config.yaml search 段新增)

```yaml
search:
  # ---- 检索质量评估 (v2.3) ----
  quality_enable: true               # 启用检索质量评估 + 降权反馈环
  quality_relevance_threshold: 0.6   # 相关度阈值: >=0.6 认为返回内容与查询相关
  quality_completeness_threshold: 0.6 # 完备度阈值: >=0.6 认为覆盖充分
  quality_session_dedup: true        # 跨调用去重: 同一会话中已返回过的内容不再重复
```

## 设计原则总结

1. **相关的不丢** — 象限② enriched content 保留，instruction 说"这部分可信"
2. **不相关的降权** — 象限③④ 走 fallback_hint，instruction 标注不可信
3. **缺的明确标** — missing_dims 列表精确告知模型哪些维度需要用自己的知识补
4. **重复的不灌** — _SESSION_SEEN 跨调用去重，10次Tool调用不灌10份相同内容
