# ContextLoader 集成指南

ContextLoader 是 KWeaver 中连接 BKN 与 Agent 的上下文加载器，通过 Trim + Toon 两个机制优化上下文质量。

## 核心机制

### Trim — 字段级相关性裁剪

过滤工具返回结果中的低价值内容（评分字段、UUID、空对象等），确保只有业务相关字段进入 Agent 上下文。

### Toon — Token 优化表示格式

将冗余的 JSON 转换为 LLM 友好的紧凑格式：

```
JSON:                                     Toon:
{"users":[{"id":1,"name":"Alice",...}]}   users[2]{id,name,role}:
                                             1,Alice,admin
                                             2,Bob,user
```

压缩率: 30-60%

## 实验验证 (MSFAgentBench)

| 环境 | 基线准确率 | ContextLoader 准确率 | 提升 |
|------|----------|-------------------|------|
| AWorld | 78.9% | 92.9% | +14.0 pp |
| Dify | 70.4% | 84.5% | +14.1 pp |

Token 减少: 27.5-33.2% | SQL 调用减少: 33.1-58.1% | SQL 错误率: 7.3% → 1.2%

## 与 Hermes BKN 的映射

| ContextLoader | Hermes BKN |
|--------------|------------|
| Trim (过滤低价值) | Agent 按需 read_file 目标文件，非全量注入 |
| Toon (紧凑格式) | Markdown 表格+列表 (BKN 语法天然紧凑) |
| Schema 感知 | BKN objects/ 定义 Object 属性/约束 |
| 动态构造 | L0 索引 → L1 按需展开 |

## 三层上下文优化链

```
原始输出 → [Trim] → [Toon] → Agent 上下文
  ↑ Schema from BKN        ↑ 高质量推理
```

参考: KWeaver ContextLoader 论文 (2026-03-19)
