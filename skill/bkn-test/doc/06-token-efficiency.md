# ⑥ Token 效率测试

> 维度：省没省 | 优先级: P2 | 可自动化: ✅

---

## 评判标准

| 指标 | 计算方式 | 目标阈值 |
|------|---------|:---:|
| BKN 加载开销 | Skill + BKN context 加载导致 input 增加的 token 数 | < 10,000 |
| 轮次节省比 | 无 BKN 时的诊断轮次 / 有 BKN 时的诊断轮次 | ≥ 1.5x |
| Token 回报率 | 节省的搜索轮次 token / BKN 加载增加的 token | ≥ 1.0 |

---

## 核心公式

```
Token 回报率 = (无BKN诊断总token - 有BKN诊断总token) / BKN加载token

  无BKN诊断总token = LLM自行搜索N轮的input+output
  有BKN诊断总token = BKN上下文(一次性) + 命中后的input+output
  BKN加载token = Skill内容 + knowledge_context + Qdrant snippets
```

**解释**：如果 BKN 多消耗 8K tokens 但省了一轮 LLM 搜索（~15K tokens），回报率 = 15K/8K = 1.87x，值得。

---

## 测试方法

### 方案 A：A/B 对照（理想，需同场景两次运行）

```
同一 query，两次执行：

  执行 A（无 BKN）：
    → 不加载 demo-product-log-analyzer / demo-product-db-diagnostics
    → LLM 自行判断需要搜索什么
    → 记录总 token 和总轮次

  执行 B（有 BKN，正常流程）：
    → 正常加载 Skill + BKN context
    → 记录总 token 和总轮次

  对比：
    token_diff = A.total_tokens - B.total_tokens
    turn_diff = A.turns - B.turns
```

### 方案 B：近似对照（从历史数据估算）

用今天已处理的两类请求做近似对比：

```
类型 1: 无 BKN 代理（或 BKN 轻量参与）
  例：api-6039bb3b5bc46588 (日志概况分析)
  观察：LLM 自行 search_files ×3 来查找上下文

类型 2: 有 BKN 完整参与
  例：api-6900ea905404cf44 (new_template 分析)
  观察：skill_view + diagnose_db_link 直接命中
```

### 方案 C：首轮延时分解

不依赖 A/B，直接测量单次请求中 BKN 的 token 占比：

```python
session = get_session("api-b34af63ede773c2d")
total_input = session.input_tokens  # 36,839

# 估算 BKN 占比
skill_tokens = estimate_skill_content_size(["demo-product-log-analyzer", "demo-product_report_sender"])  
# ~8,000 tokens (两个 Skill 全文)

bkn_context_tokens = estimate_knowledge_context_size()
# ~3,000 tokens (diagnose_db_link 返回的 knowledge_context)

qdrant_tokens = estimate_qdrant_snippets_size()
# ~2,000 tokens (search_qdrant 返回的 top-5 snippets)

system_prompt_tokens = estimate_system_prompt_size()
# ~8,000 tokens (BKN 指令 + Memory + Persona)

user_message = 2,700  # i2Agent 模板

# BKN 相关 token = skill + knowledge_context + qdrant + bkn指令部分
bkn_overhead = 8_000 + 3_000 + 2_000 + 3_000  # ~16,000

bkn_ratio = bkn_overhead / total_input  # 16,000 / 36,839 = 43%

# 如果没有 BKN，LLM 需要自行搜索 1-2 轮
# 每轮 ~15K input + ~2K output = ~17K
saved_tokens = 17_000  # 保守估计

roi = saved_tokens / bkn_overhead  # 17,000 / 16,000 ≈ 1.06
```

---

## 当前基线估算（基于今天 #32）

```
指标                    值
─────────────────────────────────
总 input tokens        36,839
BKN 相关 tokens        ~16,000 (43%)
   Skill 内容           ~8,000
   knowledge_context    ~3,000
   Qdrant snippets      ~2,000
   BKN system prompt    ~3,000
节省的搜索轮次            1 轮
节省的搜索 token       ~17,000
Token 回报率            ~1.06x
```

---

## 优化方向

如果回报率 < 1.0（BKN 开销 > 节省），优化手段：

1. **Skill 按需加载**：不加载完整 Skill，只加载决策树部分（→ 省 ~5K tokens）
2. **Qdrant top-K 缩小**：top-5 → top-3（→ 省 ~1K tokens）
3. **knowledge_context 精简**：只保留 must_know，去掉 verbose context
4. **请求模板瘦身**：i2Agent 侧缩小模板（→ 省 ~2K tokens/请求）

---

## 执行频率

- 每次 BKN 结构变更后：重新计算回报率
- 每周：抽样 5 个请求做效率分析
