# ContextLoader 实现参考

> 基于 KWeaver Core 官方论文 (MSFAgentBench) 推断的实现方案
> 当前实现: `plugin/context_loader.py`（已内置 demo-product-bkn Plugin，v1.5 起含输出预算）

## Trim (相关性裁剪)

过滤三类低价值内容：
1. **评分字段**: _score, match_score, rerank_score, intent_score
2. **技术标识**: UUID, MD5, document_id, element_id, state_time, start_time
3. **冗余/空值**: display_name, data_source, module_type, null/""/[]/{}

实现: 正则匹配 + 白名单优先，递归裁剪嵌套 JSON 对象。

## Toon (标记优化表示)

将 JSON 转为紧凑格式:
```
输入: {"rules":[{"name":"t1","status":"STOP"},{"name":"t2","status":"RUNNING"}]}
输出: rules[2]{name,status}:\n  t1,STOP\n  t2,RUNNING
```

压缩率: 30-60%。内嵌约束: [N]声明长度, {fields}声明字段顺序，模型可自检。

## 实验效果

| 指标 | 基线 | ContextLoader | 提升 |
|------|:--:|:--:|:--:|
| AWorld 准确率 | 78.9% | 92.9% | +14pp |
| Token 消耗 | 407K | 272K | -33.2% |
| Hard 任务 | 55.6% | 88.9% | +33.3pp |
| SQL 错误率 | 7.3% | 1.2% | -84% |

## 集成方式

已内置于 demo-product-bkn Plugin（`plugin/context_loader.py`），按 Tool 分策略（raw/trim_only/toon_only/full）：

```
Plugin Tool → resolver → [Trim] → [Toon] → LLM 上下文
```

v1.5 新增：输出总量预算 `_enforce_budget()`（`search.output_max_chars`，默认 0 无限制），
三轮优先级截断（非白名单长字符串 → 删非白名单 key → 白名单内容字段最后），
截断时附 `_budget_note`；`raw` 模式不截断。

不依赖 KWeaver Core 平台。

## 详细设计

当前实现与设计文档:
- `plugin/context_loader.py` — TrimFilter / ToonFormatter / ContextLoader 全部实现
- `doc/build/demo-product-bkn/33-context_loader.md` — 策略、白名单、预算机制
