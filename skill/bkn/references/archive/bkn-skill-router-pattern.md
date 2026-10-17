> 历史文档（已归档）
> 本文描述的是 `find_bkn.py` / `demo-product_bkn_router` 阶段的旧路由架构。
> 当前项目已迁移到 Hermes Plugin（10 个 Tool）查询 BKN，不再使用以下工具/脚本。
> 保留本文仅供追溯设计演进。

# BKN Skill 路由委托模式

> 来源: Demo Product BKN 实战 (2026-06-23)
> 解决问题: 操作Skill 的 BKN 表和路由 Skill 引用重叠导致 Agent 困惑

## 问题

每个操作 Skill (如 demo-product_rule_manager) 和路由 Skill (demo-product_bkn_router) 都引用 BKN 文件。如果两个 Skill 都列了同一个 BKN 文件的引用，Agent 看到两套路径：

```markdown
# 规则管理 SKILL.md            # 路由 SKILL.md
| 错误码 → risks.bkn           | 错误码 → ~/.hermes/.../risks.bkn
```

Agent 不知道该跟哪个。

## 方案：Skill 只列专属，通用委托给路由

### 操作 Skill

```markdown
## BKN 按需参考

| 遇到问题时 | 参考文件 | 内容 |
|-----------|---------|------|
| 规则操作约束 | bkn/shared/risks.bkn | 禁止restart RUNNING |
| 规则命令参数 | bkn/actions/syncrule.bkn | 创建/操作/查询命令 |
| **其他 (错误码/DB差异/端口)** | → demo-product_bkn_router | 通用路由 |
```

### 路由 Skill

```markdown
## 路由表
| 优先级 | 信号 | BKN 文件 |
| 10 | -40xx 错误码 | risks/risks.bkn |
| 8 | Oracle/MySQL... | objects/database.bkn |
| 6 | 端口/字符集/权限 | objects/env_matrix.bkn |
```

## 职责划分

| | 操作 Skill | 路由 Skill |
|------|----------|----------|
| 覆盖范围 | **本 Skill 专属**的操作知识 | **跨 Skill 通用**的产品知识 |
| BKN 引用 | 操作型 BKN 文件 (通过 symlink) | 操作型 + 知识型 BKN 文件 |
| 示例 | 状态机、命令路径、操作约束 | 错误码诊断、DB差异、端口矩阵 |
| 更新频率 | 随 Skill 版本更新 | 随产品知识更新 |

## Agent 决策流程

```
1. 加载操作 Skill → 查看 BKN 表
   ├── 表中有 → 按表查询
   └── 表中无 (指向路由Skill) → 2

2. 加载路由 Skill → 信号匹配 → 按路由表查询

3. 路由也未命中 → 不查 BKN, 直接执行
```

## 关键规则

- 操作 Skill 的 BKN 表最后一行永远是 `→ demo-product_bkn_router` 委托
- 路由 Skill 是唯一的通用 BKN 入口
- 两个 Skill 的引用指向同一文件时，路径必须一致
