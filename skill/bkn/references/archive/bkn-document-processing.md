# BKN 文档处理管道

> **已废止，勿引用**：`bkn/diagnostics/` 已退场（26 号）——现行落点见 `bkn/objects/` 与 `bkn/relations/`。

从非结构化产品文档（PDF/DOCX/Markdown）到结构化 BKN 知识的 4 阶段管道。

## 使用场景

- 有产品配置手册、运维手册、故障排查指南等文档
- 需要从中提取结构化业务知识供 Agent 使用
- 文档已做 chunk 预处理（如存入 Qdrant 向量库）

## 管道架构

```
非结构化文档 (1029 chunk)
        │
        ▼ 阶段1: 实体抽取 (LLM)
  ┌─────────────────────────┐
  │ 每个 chunk 提取:         │
  │  Object: 业务对象        │
  │  Relation: 对象关系      │
  │  Action: 可执行操作      │
  │  Risk: 风险/注意事项     │
  └─────────────────────────┘
        │  ~200-300 条碎片实体
        ▼ 阶段2: 聚类合并
  ┌─────────────────────────┐
  │ 同义词归一化:            │
  │  "DB"/"数据库"/"数据源"  │
  │    → DatabaseNode       │
  │ 重复条目去重            │
  │ 子步骤归位到父 Action   │
  └─────────────────────────┘
        │  ~30-40 Object, ~50 Action, ~20 Risk
        ▼ 阶段3: 关系建模
  ┌─────────────────────────┐
  │ Rule → 依赖 → Database   │
  │ Database → 注册于 → Node │
  │ Action → 作用于 → Object │
  │ Risk → 约束 → Action     │
  └─────────────────────────┘
        │  ~15-20 Relation
        ▼ 阶段4: 文件生成
  ┌─────────────────────────┐
  │ objects/                 │
  │   database.bkn           │
  │   component.bkn          │
  │   host.bkn               │
  │ actions/                 │
  │   setup.bkn              │
  │   lifecycle.bkn          │
  │ relations/topology.bkn   │
  │ risks/constraints.bkn    │
  │ diagnostics/  (诊断内容时) │
  │   symptom-router.bkn     │
  │   error-codes.bkn        │
  └─────────────────────────┘
```

> 19 号方案：诊断域内容（症状/错误码/诊断类）不散落 risks/，收拢 `diagnostics/`。

## 阶段1: 实体抽取 Prompt

```markdown
从以下产品文档片段中提取 BKN 实体，以 JSON 格式返回：

{
  "objects": [{"name": "...", "description": "...", "attributes": [...]}],
  "actions": [{"name": "...", "description": "...", "target_object": "..."}],
  "relations": [{"source": "...", "target": "...", "type": "...", "description": "..."}],
  "risks": [{"name": "...", "level": "HIGH|MEDIUM|LOW", "condition": "...", "action": "..."}]
}

文档片段:
<chunk_content>
```

## 阶段2: 聚类合并规则

| 场景 | 规则 |
|------|------|
| 同义名 | "Oracle数据库" / "Oracle DB" / "oracle" → 统一为 canonical name |
| 重复属性 | 同名 Object 的属性 merge，冲突时取更完整的描述 |
| 子步骤 | "创建用户" 归类到 "PostgreSQL 环境准备" Action 下 |
| 条件分支 | "如果 Oracle 版本 < 11g 则..." → 提取为 Action 的变体，不是独立 Action |

## 阶段3: 关系推导规则

| 模式 | 推导关系 |
|------|---------|
| "在 X 上部署 Y" | Y → depends_on → X |
| "配置完成后启动 Z" | Action(配置) → precedes → Action(启动) |
| "必须先...再..." | ActionA → prerequisite → ActionB |
| "注意: 不能..." | Risk → constrains → Action |

## 阶段4: 产出物示例 (Demo Product 配置手册)

```
objects/database.bkn:
  Oracle Source Database (type=ORACLE, role=SOURCE)
  PostgreSQL Target Database (type=POSTGRESQL, role=TARGET)

actions/setup.bkn:
  系统参数配置 (ulimit, JDK, 安全公钥)
  PostgreSQL 环境准备 (建库, 建用户, 赋权, 创建Schema)
  工作节点部署 (安装, 激活, 验证连通性)

relations/topology.bkn:
  SyncTask → source → Database(SOURCE)
  SyncTask → target → Database(TARGET)
  Database → registered_on → WorkerNode

risks/pitfalls.bkn:
  root权限修改需客户确认 (HIGH)
  字符集不匹配导致脏数据 (MEDIUM)
  归档日志未开启导致CDC失败 (CRITICAL)
```

## 成本估算

| 文档规模 | chunk 数 | LLM 调用 | 预估 token |
|---------|---------|---------|-----------|
| 100页配置手册 | ~1000 | ~150 (每批7个) | 30-50万 |
| 50页运维手册 | ~500 | ~75 | 15-25万 |

## 集成方式

1. 文档已存入 Qdrant → 通过 scroll API 获取所有 chunk
2. 每批 5-10 个 chunk 发送给 LLM 做实体抽取
3. Python 脚本做聚类合并和关系推导
4. 输出 .bkn 文件到 `skills/<name>/references/bkn/`

## 与现有知识的互补

| 来源 | 作用 |
|------|------|
| SOUL.md 术语表/架构 | Agent 已有"是什么"的知识 |
| BKN 文档处理产出 | 补充"怎么做"和"有什么限制" |
| Qdrant 向量检索 | 回答未结构化的细节问题 |
