# BGE Precision Failure — v3.4 完整诊断与修复

> 触发: 2026-07-03, `-4002` 错误码查询
> 修复: v3.4 BGE Precision Guard (supplement.py + config.py)
> 设计文档: <repo>/bkn/bge-precision-guard-design.md
> 审计报告: <repo>/bkn/plugin-audit-2026-07-03.md

---

## 故障链路 (端到端)

```
用户: "4002 是什么问题"
  → diagnose_error("-4002")
    → BKN risks.bkn: 无此条目 → confidence=partial
    → fallback_to_qdrant() → SEARCH_DEFER_TO_HERMES=true
      → 返回 _search_deferred=true + _instruction
        → Agent 调 search_qdrant("-4002 错误码 Demo Product 同步异常...", top_k=5)
```

### search_qdrant 内部执行

```
search_qdrant(query="-4002 错误码 Demo Product 同步异常 数据库连接 装载 导出", hybrid=True)
  │
  ├─ BGE query_points(score_threshold=0.3)
  │   → 5 条结果, score 0.67~0.69   ← 第一层失效
  │   → 内容: Demo Product原理、IAERR 4042、IAERR 4007、IAERR 4033
  │     (语义上都是"错误码相关", 但都不是 -4002)
  │
  ├─ v3.3 检查: bge_failed = all(scores < 0.1) → FALSE   ← 第二层失效
  │   BGE 给了高分但给错了 → 兜底被跳过
  │
  ├─ RRF 融合: BGE(rank 1-5) + BM25(rank N, N>15)
  │   → -4002 方案文档淹没在排名 15+  ← 第三层失效
  │
  └─ 返回: 前5条全是其他错误码(4033/4042/4007/3565)
```

---

## 根本原因 (三层)

### 层1: BGE 语义近似 — 高分但错误

BGE 模型把 `-4002` + `错误码` + `Demo Product` 编码后，向量指向"Demo Product 错误码"区域。
该区域包含了所有 Demo Product 错误码文档 (4033/4042/4007 等)，score 都在 0.67 以上。
BGE 正确理解了"这是关于错误码的查询"，但不知道"要的是 -4002 而不是 4007"。

### 层2: 兜底阈值设计 — 只防 recall 不防 precision

`SEARCH_BM25_FALLBACK_SCORE=0.1` 仅处理 "BGE 完全找不到" (score≈0) 的场景。
当 BGE 找到"错误"但"高置信"的结果时，阈值被越过。

### 层3: RRF 融合 — BM25 也被泛化查询淹没

查询词混入了太多泛化词 ("错误码" "Demo Product" "同步异常" "数据库连接" "装载" "导出")，
BM25 对泛化词的匹配把精确的 "-4002 dumpredo" 方案文档推到排名 15+。

---

## 修复: v3.4 BGE Precision Guard

### 核心思路

BGE 返回后，验证结果中是否包含查询的精确匹配项（错误码等）。
若不包含，说明 BGE 发生了 precision failure，触发内容级字符串匹配 + BM25 两路合并。

### 精确项提取

```python
_EXACT_TERM_PATTERNS = [
    (r'-\b\d{4}\b',   'error_code'),   # -4002, -4073 (仅负号, 避免端口/年份噪声)
    (r'\bORA-\d{5}\b', 'ora_error'),    # ORA-00001
]
```

### 内容级字符串匹配

绕过 tokenizer 分词问题。jieba 把 `"4002问题"` 分词为单 token → BM25 倒排索引无 `"4002"` 词条。
`_search_content_exact()` 直接字符串 `in` 匹配 + 横杠变体处理 ("-4002"→也搜"4002")。

### 修复效果

| 查询 | 修复前 | 修复后 |
|------|--------|--------|
| `-4002 错误码` | 其他错误码表 (4033/4042) | "4002问题强行继续规则的方法" |
| `Oracle到MySQL 类型映射` | RRF 融合 | 不受影响 (无精确项) |
| `PostgreSQL 5432 配置` | RRF 融合 | 不受影响 (正数不匹配) |

### 二次故障: jieba 分词吞噬数字

Qdrant 文档 `"4002问题强行继续规则的方法"` 经 jieba fallback tokenizer 处理后:
- token 列表: `['问', '问题', '题', '题强', '强', '强行', ...]`
- **没有 "4002" token** — 数字被中文 bigram 吞并

`_search_content_exact()` 绕过 tokenizer 直接用 `"4002" in content` 解决。

---

## 文件改动

| 文件 | 改动 | 行数 |
|------|------|------|
| `config.py` | +`SEARCH_BM25_PRECISION_GUARD` | +3 |
| `supplement.py` | +`_extract_exact_terms`, `_any_hit_contains_term`, `_search_content_exact`, 兜底逻辑 | +60 |
| `supplement.py` docstring | 更新 `search_qdrant` 版本号 | 1 |
