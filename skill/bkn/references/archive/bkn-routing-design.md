> 历史文档（已归档）
> 本文描述的是 `find_bkn.py` / `demo-product_bkn_router` 阶段的旧路由架构。
> 当前项目已迁移到 Hermes Plugin（10 个 Tool）查询 BKN，不再使用以下工具/脚本。
> 保留本文仅供追溯设计演进。

# BKN 路由设计

> 版本: 2026-06-23 | Demo Product 实战

## 问题

Agent 遇到用户输入时，如何确定查哪个 BKN 文件？最初做法是 Agent 读路由表文本 + 脑海正则匹配，存在三个问题：

1. **Token 浪费**: 每次要读 network.bkn 全文做匹配
2. **变体遗漏**: 正则补全后用户说"挂了"不匹配"ABNORMAL"
3. **Agent 负担**: 推理链多一步"理解表格→正则匹配"

## 三层演进

### 第1层: 文本路由 (初版)

Agent 读 network.bkn 路由表 → 用正则匹配 → 确定文件 → read_file。

```
用户: "Oracle 同步到 OB"
Agent: read_file(network.bkn) → 正则匹配到 Priority 8 → read_file(database.bkn)
```

问题: 每次读全文, ~100行 token。

### 第2层: 同义词标准化 (改进)

在 network.bkn 中增加同义词映射，Agent 先标准化再匹配。

```
用户: "ora库挂了"
Agent: "挂了" → 标准化 → "异常" → Priority 10 → risks.bkn
```

问题: 仍需 Agent 手动做标准化 + 正则匹配，逻辑在推理链中。

### 第3层: 工具下沉 (当前)

路由逻辑从 Agent 推理链搬到 `find_bkn.py` 工具脚本。

```bash
python3 find_bkn.py "ora库挂了"
# → {"best": {"file": "risks/risks.bkn", "priority": 10, ...}}
```

Agent 只需:
1. `terminal("python3 find_bkn.py '用户输入'")`
2. 读 JSON → 按 best.file 用 search_files/read_file

## find_bkn.py 设计

```
输入: 用户输入文本
  ↓
同义词标准化 (SYNONYMS dict)
  ↓
正则路由匹配 (ROUTES list, 按 priority 排序)
  ↓  
输出: JSON {hits, best, normalized}
```

关键设计决策:
- 长变体优先匹配 (防"ora"误伤"Oracle")
- 短变体如果是标准词子串，跳过
- 多条命中按优先级排序，best 取最高

## 集成方式

- `demo-product_bkn_router` Skill 描述该工具用法
- Agent 加载 Skill → 知道调 find_bkn.py
- 路由逻辑完全在 Agent 推理链之外
