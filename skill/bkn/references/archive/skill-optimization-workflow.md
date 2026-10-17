# Skill BKN 优化工作流

> **已废止，勿引用**：同上（`symptom-router.bkn` 已退场）——现行口径见 `dimension:*` 类集与 lint 的 `_namespace_registry_consistency`。

对现有 Agent Skill 进行 BKN 审计和优化的实战流程。

## 输入

一组已有的 Agent Skill (如 Demo Product 的 rule_manager / node-manager / db_manager / diff_op)。

## 输出

1. 共享 BKN 知识网络 (`bkn/`)
2. 渐进式优化版 SKILL.md (精简到 L0，通过索引指向 BKN)

## 六步流程

### Step 1: 读取 + 度量

```
wc -l skills/*/SKILL.md skills/*/*/SKILL.md
→ 了解当前注入量级；标记 > 200 行的 Skill 为重点优化目标
```

### Step 2: BKN 审计 (见 references/skill-audit.md)

用要素视角逐 Skill 审计（业务域四要素 + 诊断域 Symptom/DiagnosticClass）：

| 审计维度 | 检查项 |
|---------|--------|
| Object识别 | 核心业务对象是否已被明确定义？还是散落在流程描述中？ |
| Relation缺失 | 跨 Skill 依赖是否靠口头约定？能否用拓扑图表达？ |
| Action独立 | 操作步骤是否与前置条件、脚本路径混在一起？ |
| Risk零定义 | 危险操作是否有显式约束？还是靠 LLM "随机应变"？ |
| 状态机隐式 | 对象生命周期是否靠"如果-那么"文本描述？ |
| Token重复 | 相同信息(认证/目录/返回码)是否在多处重复？ |
| 症状/诊断类（诊断域） | 症状是否已登记（symptom-router.bkn + routing.bkn 归类边）？诊断类是否越界扩类（应 gap 证据 + 评审）？ |

### Step 3: 设计 BKN 文件树 (对象级拆分 + 分级)

```bash
bkn/
├── objects/                  ← 每个 Object 独立文件 (不合并)
│   ├── syncrule.bkn          ← 22行, 只查规则时不带入其他定义
│   ├── workernode.bkn        ← 7行
│   ├── dbnode.bkn            ← 8行
│   └── ...
├── actions/                  ← 按关联 Object 拆分
│   ├── syncrule.bkn
│   ├── workernode.bkn
│   └── ...
├── shared/                   ← 跨 Skill 共享内容（当前 Demo Product 已收敛到统一 bkn/risks/ + bkn/diagnostics/）
│   ├── risks.bkn             ← L0段(常驻) + L2段(按需)；Demo Product 实例: bkn/risks/constraints.bkn
│   └── diagnostics/          ← 诊断路由层；Demo Product 实例: bkn/diagnostics/（classes/routing/error-codes…）
└── ...
```

**拆分原则**:
- 一个文件对应一个 Object，不让不相关的定义泄漏进上下文
- shared/ 放公共内容（risks/auth），其他 skill 用相对路径引用
- L0 (CRITICAL) 内联到 SKILL.md 常驻，L1 (object+action) 按需加载，L2 (HIGH+MEDIUM) 仅写操作加载

**命名原则**:
- Object 文件名 = 单个对象名 (如 syncrule.bkn)，非汇总文件 (platform.bkn)
- Action 与对应 Object 同名
- Risk 按 L0/L2 分段标记，支持分级加载

### Step 4: 编写 BKN 内容

**Object**: 从 SKILL.md 中提取属性、约束、状态机、对应脚本路径

**Relation**: 画出前置依赖链，标注共享信息(认证/env)

**Action**: 为每个操作定义：前置条件 + 脚本入口 + 参数 + 约束(引用Risk)

**Risk**: 从 SKILL.md 的"注意事项"和"禁止"中抽取，标注级别和处置方式

### Step 5: 精简 SKILL.md

目标: 每个 Skill 的精简版 30-60 行 (~600-1500 tokens)

精简版保留:
- 运行环境 (cd 路径 + uv run 规则)
- 渐进式加载索引表 (场景 → read_file 路径)
- 状态机速查 (仅高频转换)
- 脚本入口表 (操作 → 命令)
- 全局约束 (来自 Risk 的硬边界，仅 TOP5)

精简版删除:
- **迁移历史/墓碑** — 「已迁 xx（日期）」「自本文迁入」「旧节 → 新位置」一律**不写入** SKILL.md 或 references；只保留「主题 → 权威位置」的正确索引（索引正确即足够，历史记录零信息量、纯耗 token）
- 详细流程描述 → 移到 bkn/actions/
- 类型参数/模板 → 移到 bkn/objects/
- 错误码/故障排查 → 移到 bkn/diagnostics/error-codes.bkn + bkn/diagnostics/routing.bkn（19 号方案收拢）
- 重复的认证/环境信息 → 移到 bkn/relations/

### Step 6: 部署 + 验证

```bash
# 部署 BKN
cp -r bkn/ $STREAM_ROOT/bkn/

# 备份原始 SKILL.md
cp skills/*/SKILL.md skills/*/SKILL.md.bak

# 写入精简版 (覆盖)
# ... write_file 操作 ...

# 验证 Token
wc -l skills/*/SKILL.md
# → 目标: L0 总和 < 200 行
```

## 实战效果 (Demo Product 案例, 2026-07)

| 指标 | 优化前 | 优化后 |
|------|--------|--------|
| L0 注入总量 | 781行 / ~6000tokens | 161行 / ~1200tokens |
| 按需加载 | 不可用 | ~300-500tokens |
| Object 定义 | 0 (散落) | 4 个明确 Object |
| Risk 定义 | 0 (隐含) | 结构化约束表（CRITICAL×7 + HIGH×5 + MEDIUM×4，2026-08 起 severity 归一为 critical/warning/info + 约束ID 机器可读列） |
| 跨 Skill 依赖 | 口头约定 | 结构化拓扑 |
| Token 节省 | — | 75-80% |

## 陷阱

1. **BKN 不要过大** — 单个 .bkn 文件控制在 50 行以内，保持 Agent 按需加载的效率
2. **SKILL.md 不要过瘦** — 保留脚本入口表和状态机速查，不能只剩索引链接；反之**迁移历史不要留**——索引对就够，墓碑只是占位耗 token
3. **Risk 必须有处置** — 不可只定义风险不写处置策略，否则 Agent 不知道触发后该做什么
4. **路径必须一致** — BKN 引用的脚本路径必须与实际部署路径一致
