# BKN Plugin 审计方法论与版本维护清单

> 从 `SKILL.md` 分离，保持主文件精简。
> 关联: `../SKILL.md`

## Plugin 审计方法论

当对 Plugin 做一个复杂改动后，用以下流程系统审查：

### 代码 vs 设计文档对照

```
1. 读 schemas.py → 确认 description 和 handler 实际返回字段对齐
2. 读 tools.py _wrap() → 确认注释和实际调用链一致
3. 读 context_loader.py _FULL_CONTENT_KEYS → 确认所有 supplement 新增字段在白名单
4. 读 config.yaml + config.py → 确认所有配置项两端对齐
```

### 设计文档一致性审计

```bash
# 版本一致性
grep -rn "v2\.[0-9]\|v3\.[0-9]" supplement.py tools.py schemas.py config.py | head -20
# Tool 数量审计
grep -c "HANDLERS\[" tools.py; grep -c '"name":' schemas.py | head -1
```

**审计检查清单**：

```
□ plugin.yaml provides_tools 数量 vs schemas.py SCHEMAS 数量 vs 设计文档声称数量
□ plugin.yaml version 是否与 SKILL.md/README.md 版本号对齐
□ _wrap() 注释是否反映当前补充管道行为（v3.0+ 无质量评估）
□ 架构图是否列出已移除的模块（v2.3 双维评估/四象限/会话去重/动态噪声）
□ supplement-mechanism.md 是否标记 deprecated 章节
□ 设计文档文件结构注释是否反映当前功能集
□ 补充策略版本号是否全局一致
□ tool-design.md 每个 Tool 是否有 Schema + Handler 逻辑 + 返回示例三段
□ Tool 10 (search_qdrant) 是否有完整的 Handler 逻辑伪代码
□ README.md 底部日期版本号是否与文档内容一致
□ 所有设计文档最后更新日期是否对齐同一版本
□ 源码注释是否引用正确的版本号/功能描述
```

**典型不一致模式**：

| 模式 | 现象 | 修复 |
|------|------|------|
| 数字漂移 | plugin.yaml 说9个Tool，实际10个 | 实测 provides_tools 计数 |
| 残留引用 | _wrap注释含"四象限降权"（v3.1已移除） | 对齐当前管道行为 |
| 架构图过时 | supplement 框图列出已归档模块 | 移除+标注归档位置 |
| 版本链断裂 | README v2.4 → 实际 v3.1 | 全局搜索替换版本号 |
| deprecated未标记 | 186行v2.3文档无归档提示 | 加[已归档]标记+warning |
| 缺失设计段 | Tool 10 缺Handler逻辑 | 补全三段式设计 |

> 📎 完整审计报告: [design-code-audit-2026-07-03.md](design-code-audit-2026-07-03.md)

## 边缘用例走查清单

新增 Tool/功能后逐项检查：

```
□ quality_enable=false 时路径是否回退安全逻辑？
□ 所有 hits 被去重后 → fallback_hint 而非空返回？
□ 新字段是否被 ToonFormatter 截断？（check _FULL_CONTENT_KEYS）
□ 新函数是否引入了未 import 的模块？
□ keyword 检查是否覆盖 _query 标签？
□ 不走 _wrap() 的 handler 是否返回 str 而非 dict？
□ normalize_db 是否处理复合名/别名？
□ BM25 索引后 content 是否回填？
□ design_solution 返回是否含顶层 prerequisites/constraints/risks？
□ schemas.py description 是否与 handler 实际返回对齐？
□ schemas.py SCHEMAS 列表是否包含所有 HANDLERS 中注册的 Tool？（新 Tool 三点铁律 #1）
□ constants.py 是否被 resolver + supplement 共同引用？
□ reload.py 是否独立可执行 + 完整重建全局实例？
□ search_qdrant_handler 不走 _wrap()？（避免 supplement 管道循环）
□ search_qdrant_handler collection 分支 model=None 时返回 error 而非静默回退？
□ search_qdrant_handler 维度追踪: dimension 参数传入后 _track_dimension 被调用？（v3.1）
□ search_qdrant_handler __report__ 模式返回 {coverage, mode:"report_only"}？（v3.1）
□ _SESSION_DIMS 跨调用累积: coverage 正确更新？（v3.1）
□ 移除代码后是否确认无残留引用？（grep 被删函数名）
□ config.yaml 是否无 quality_* 残留配置项？（v3.1）
□ search_qdrant_handler 所有 return 路径返回 string (json.dumps) 而非 dict？
□ search_qdrant() BM25 fallback: dense_hits 为空时是否触发 BM25？（v3.3.1）
□ Hermes venv 是否安装了 qdrant_client + sentence_transformers + jieba？
□ BGE 模型维度是否与 Qdrant 索引维度一致？（bge-small=512, bge-large=1024）
□ search_qdrant() except 块是否吞异常后直接掉路径2 无 BM25？
```

## v2.5 审计历史 Pitfalls（部分已随 v3.1 代码移除）

| # | Pitfall | 根因 | 修复 | 状态 |
|---|---------|------|------|------|
| 1 | 带版本号的 DB 名噪声误判 | `_build_noise_patterns` 精确匹配 → Oracle 被误标记 | 改为模糊匹配 | ✓已移除(v3.1) |
| 2 | BM25 scroll API 不兼容 | `client.scroll()` 老版返回格式不同 | try/except 降级 | 保留 |
| 3 | BM25 RRF 融合空 content | `bm25_search` 返回空 content | 索引时缓存，检索时回填 | 保留 |
| 4 | `reload.py` `_loader` 不重建 | `_loader = None` 不重建 | `_loader = ContextLoader()` | 保留 |
| 5 | `reload.py` 绝对导入失败 | 从 scripts/ 独立执行找不到模块 | 提取 reload() + path 注入 | 保留 |
| 6 | `design_solution` Schema 夸大 | description 说返回部署拓扑但 handler 没有 | 补齐字段 + Schema 收敛 | 保留 |
| 7 | `_gap_coverage_enhanced` NameError | 缺 `import re` | 补充 import | ✓已移除(v3.1) |
| 8 | `quality_enable=false` 降级路径 | 返回全0→落入象限④ | 加 early return | ✓已移除(v3.1) |

## 版本更新清单

每次改动后应更新以下位置：

- `constants.py` — 新增别名/噪声变体
- `config.yaml` — 新增配置项
- `supplement.py` — 版本注释在关键函数
- `tools.py` — handler 返回字段变更
- `schemas.py` — description 与 handler 对齐 + SCHEMAS 与 HANDLERS 一致
- `context_loader.py` — _FULL_CONTENT_KEYS 新字段
- `bm25.py` — scroll/索引 API 变更
- `scripts/reload.py` — 全局实例重建逻辑
- 设计文档 — `<repo>/bkn/hermes-bkn-plugin/*`
- 本 SKILL.md — 版本号、Tool 数量、新 pitfall、移除记录

## 快速排查：Plugin Tool HTTP 400 vs Plugin 代码 bug

当遇到 `content should be a string or a list` 类 API 错误时：

```
1. 确认出错的消息角色: messages[N]
   - N 为偶数 → assistant 消息 → 大概率是 DeepSeek content:null 问题
   - N 为奇数 → tool 结果消息 → 检查 handler 返回值

2. 验证 Plugin 返回值:
   python3 -c "from plugin.tools import search_qdrant_handler; ..."

3. 验证 .py/.pyc 一致性:
   stat plugin/supplement.py plugin/__pycache__/supplement.cpython-*.pyc
```

### search_qdrant 三步定位法（返回无关结果时）

```bash
# Step 1: 确认 handler 是否硬编码 hybrid=True
grep -n "hybrid=True" plugin/tools.py
# 预期: L277: raw_hits = search_qdrant(query, top_k=top_k, hybrid=True)

# Step 2: 模拟 handler 的实际调用路径
cd /path/to/demo-product-bkn && /root/demo/stream-agent/.venv/bin/python3 -c "
from plugin.supplement import search_qdrant
results = search_qdrant('-4002', top_k=5, hybrid=True)
for i, r in enumerate(results):
    print(f'[{i}] score={r.get(\"score\",0):.4f} fb={r.get(\"_fallback_reason\",\"N/A\")} {r[\"content\"][:80]}')
"
```

| dense_hits | scores | bge_failed | 走向 |
|-----------|--------|------------|------|
| [] | — | True | bm25_search(full_query) |
| [{0.0},..] | all<0.1 | True | bm25_search(full_query) |
| [{0.6},..] | 有≥0.1 | False | RRF 融合 → precision guard |

**常见失败模式**：
- BM25 索引过期 → `bm25_search()` 返回空或旧数据 → [重建索引](bm25-rebuild.md)
- BGE 返回高分但内容错误（精确率失败）→ v3.4 Precision Guard 应触发 → 检查 `SEARCH_BM25_PRECISION_GUARD` 配置
- Qdrant 服务不可用 → `query_points()` 抛异常 → `except` 返回空
