# BKN Skill 审计方法论

> **已废止，勿引用**：`symptom-router.bkn` 登记路径已退场——现行＝补边（`suspected_in`/`has_class`）+ 维度类集有界不新增。

当需要对一组现有 Agent Skill 进行 BKN 合规审计时，按以下流程系统化执行。

## 核心审计维度

围绕 BKN 双层结构检查每个 Skill——业务本体四元体系 (Object/Relation/Action/Risk) + 诊断路由层 (Symptom/DiagnosticClass)：

| 维度 | 检查问题 | 典型缺失信号 |
|------|---------|-------------|
| **Object** | 核心业务对象是否显式定义？ | 对象属性散落在自然语言流程中 |
| **Relation** | 跨 Skill 依赖是否结构化？ | "创建前必须先检查..." 靠口头约定 |
| **Action** | 操作是否独立定义且有前置条件？ | 脚本调用和前置条件混在过程描述中 |
| **Risk** | 危险操作是否有硬约束？ | "先 dry-run 确认" 高度依赖 LLM 自觉 |
| **Symptom/DiagnosticClass**（诊断域） | 症状是否已登记？诊断类是否越界扩类？ | 症状散在 Skill 文本中未进 `symptom-router.bkn`；新现象直接建诊断类（应走登记制 + gap 证据评审） |

## 五步审计流程

### Step 1: 加载全部 Skill

```bash
# 读取所有目标 Skill 的 SKILL.md
# 提取: 核心对象、操作命令、约束规则、状态描述
```

### Step 2: 提取隐式 Object

扫描 Skill 的自然语言描述，识别未显式建模的业务对象：

```
信号词:
- "规则名称/规则UUID" → 暗示 SyncRule 对象
- "节点状态必须为 NORMAL" → 暗示 DatabaseNode.status
- "工作节点在线且 iahelper 运行正常" → 暗示 WorkerNode
- "对比规则名称" → 暗示 CompareRule
```

### Step 3: 发现隐式 Relation

检查"前置检查清单"类的描述：

```
信号:
- "创建规则前置检查: 源端角色必须含 source" → Relation: SyncRule → DatabaseNode
- "必须绑定 license" → Relation: DatabaseNode → License
- "创建前检查工作节点状态" → Relation: DatabaseNode → WorkerNode
```

### Step 4: 识别隐式 Risk

扫描流程中"必须先...才能..."的约束：

```
信号:
- "必须先确认规则已停止" → Risk: 修改运行中规则
- "先 dry-run 确认" → Risk: 未确认即删除
- "必须追问是否同时停止日志解析" → Risk: 日志解析未停止
- "创建前先检查工作节点状态" → Risk: 节点OFFLINE时创建
- "用 `uv run` 而非 `python`" → Risk: 虚拟环境未激活
```

### Step 5: 生成 BKN 网络 + 优化 Skill

输出:
1. `network.bkn` — 全局索引
2. `objects/` — 每个 Object 一个 .bkn
3. `relations/` — 跨 Skill 拓扑
4. `actions/` — 每类操作一个 .bkn
5. `risks/` — 按领域分组
6. `skills-optimized/` — 精简后的 Skill (引用 BKN)

优化后 Skill 结构:
```markdown
# Skill 名称 (BKN优化版)
> 对应 BKN: [Object](path) | [Actions](path) | [Risks](path)

## 运行环境 (仅保留不变的环境配置)
## 决策流程 (决策树，引用 BKN 约束)
## 状态机速查 (如有)
## 脚本入口 (精简命令表)
## BKN Risk 硬约束 (引用/提取关键 Risk)
```

## 八类典型审计问题

对任意 Agent Skill 进行 BKN 审计时，常见 8 类问题。按优先级排列：

| # | 问题 | 检测方式 | 修复方向 |
|---|------|---------|---------|
| 1 | **Object 未定义** — 核心业务对象散落在过程描述中 | 搜索"判断用户请求是..."、"如果是..."等过程描述信号词 | 用 BKN Object 语法显式建模 |
| 2 | **Relation 缺失** — 跨 Skill 依赖靠口头约定 | 搜索"创建前必须先检查..."、"前置检查清单" | 用 BKN Relation 定义拓扑依赖链 |
| 3 | **Action 未独立** — 脚本调用和前置条件混在一起 | 搜索脚本入口和前置条件是否在同一段落 | 用 Action 语法：归属对象 + 前置条件 + 执行方式 |
| 4 | **Risk 零定义** — 危险操作靠 LLM"随机应变" | 搜索"先 dry-run 确认"、"必须先..."、"需要追问" | 用 Risk 语法：CRITICAL/HIGH/MEDIUM + 约束行为 + 处置策略 |
| 5 | **隐式状态机** — 状态转换靠自然语言"如果-那么" | 搜索错误码（-4071/-4031）和相关处理规则 | 用 TRANSITION 表显式定义状态流转 |
| 6 | **Token 浪费** — 相同信息（认证/目录/返回码）在多个 Skill 中重复 | 对比多个 Skill 的 SKILL.md，找出重复段落 | 提取到共享 BKN 层，各 Skill 只引用 |
| 7 | **无渐进式披露** — 全量内容一次性注入上下文 | 统计 SKILL.md 行数 > 100 行但 80% 场景仅需 20% | 拆分为 L0(索引) + L1(references/按需加载) |
| 8 | **多 Skill 孤立** — 应是一张网络却各自为战 | Skill 数量 ≥ 3 且存在跨 Skill 依赖但无共享定义 | 创建 BKN 知识网络，各 Skill 通过索引表引用共享 Object/Relation/Risk |

## Token 优化目标

| 指标 | 优化前 | 优化后 |
|------|--------|--------|
| 单 Skill 行数 | 原始全部 | 压缩 60-80% |
| 全量加载 | 15000+ tokens | 7000 tokens |
| 按需加载 | 全量 | 500-800 tokens (仅展开目标文件) |
| 重复内容 | 认证/目录/返回码 ×N 次 | 集中 1 次 |

## 审计报告模板

```markdown
# BKN 审计报告: {项目名}

## 概览
- 审计 Skill 数: N
- 发现隐式 Object: N个
- 发现隐式 Risk: N条
- 建议新增 Relation: N条

## 逐 Skill 分析

### {skill_name}
- 现有 Object: ...
- 缺失 Object: ...
- 隐式 Risk: ...
- 改进建议: ...

## 优先级排序

| 优先级 | 改进项 | 预期收益 |
|--------|--------|---------|
| P0 | 补充 Risk 定义 | 防止越权操作 |
| P0 | 定义状态机 | 避免无效操作 |
| P1 | 提取 Object | 结构化可复用 |
| P1 | 建立 Relation | 自动检查前置条件 |
| P2 | 去重 + 渐进式披露 | Token 节省 |
```
