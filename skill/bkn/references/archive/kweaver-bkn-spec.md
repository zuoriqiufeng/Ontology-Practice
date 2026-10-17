# KWeaver 官方 BKN 规范 — 关键摘录

> 来源: https://kweaver-ai.github.io/kweaver-core/bkn-business-knowledge-network-language
> 日期: 2026-04-10 | 作者: KWeaver Team
> 许可: Apache 2.0 (开源)

---

## 一、BKN 是什么

BKN (Business Knowledge Network) 是一种面向业务知识网络的 **Markdown 领域建模语言**，专为 Agent 上下文设计的**业务本体描述语言**。它是 KWeaver Core 项目的创新点之一。

**目标**: 把分散在数据库、接口、流程、规则和人脑经验里的业务知识，整理成 Agent 可以直接读取、理解、调用和约束的语义结构，作为 Agent 数据层面的 **Source of Truth（唯一事实来源）**。

## 二、核心四元体系

| 元素 | 回答的问题 |
|------|-----------|
| **Object** | "这个业务里有什么"（订单、供应商、Pod、Node） |
| **Relation** | "这些东西如何彼此连接"（归属、依赖、来源于） |
| **Action** | "围绕这些对象可以做什么"（可绑定工具或 MCP） |
| **Risk** | "这些动作在哪些边界内才成立"（执行约束和风险红线） |

> 注: BKN 与 Palantir Ontology 相通，但增加了 Risk 作为显式约束，这是 BKN 的创新。

## 三、设计原则

### 载体选择: Markdown
- 与 Anthropic SKILL、OpenAI AGENTS.md、OpenClaw SOUL.md/MEMORY.md 一致
- 既适合人维护，也适合模型读取
- **显著减少上下文长度**

### 渐进式披露
- BKN 不一次性把所有知识塞给模型
- Agent 首先面对语义空间的**索引**
- 再根据任务需要逐步展开相关对象、关系和边界条件
- 和 Claude SKILL 的设计逻辑一致

### 本体特征
1. **概念稳定**: 数据库表和接口总在变，但"订单""供应商"这类业务概念稳定
2. **结构化关系**: 不是词典，而是语义网络
3. **可执行语义**: 不只回答"是什么"，还回答"能做什么、什么时候能做、怎么控风险"

## 四、构建方式: BKN-Creator

BKN 不是手写的，而是通过 **BKN-Creator Skill** 自动化生成。构建过程分三步:

### Step 1: 萃取对象与关系
从需求文档、数据库 Schema、API 定义中识别业务实体和关联

### Step 2: 给对象绑定行动
把"重启"绑定到 Pod，"启动同步"绑定到 SyncTask

### Step 3: 注入风险控制
每个 Action 的约束直接写进 `.bkn` 文件，变成 Agent 思考时的**硬边界**

## 五、实测效果

24 个供应链业务问题，相同模型前提下对比:

| 指标 | 纯 SQL | BKN | 改善 |
|------|--------|-----|------|
| 通过率 | 79.2% | 95.8% | +16.6% |
| Token 消耗 | ~500K | ~292K | -41.6% |
| 调用次数 | 56 | 45 | -19.6% |

结论: BKN 让 Agent 不再总盯着底层表结构，而是更多围绕业务对象、关系和规则思考。BKN 不是为了替代 SQL——SQL 擅长精确查询和直接聚合，BKN 是把 SQL、Python、工具调用放进一个更贴近业务语义的框架里使用。

## 六、文件组织

```
business-domain/
├── SKILL.md       # 面向 Agent
├── network.bkn    # 知识网络根定义
└── .bkn 文件树    # 按类型拆分
```

## 七、核心理念引用

> "如果说 Agent 时代的核心问题是'如何让模型在复杂业务中持续做对事'，那么答案往往不只是追求更强的模型，而是通过更好的上下文工程，把业务语义、工具和执行规则理清楚。"
> — KWeaver Team

> "上下文不再只是给模型看的一段参考资料，而是变成了真正能驱动 Agent 理解、决策并受控执行的业务底座。"
> — KWeaver Team, Harness Engineering 章节
