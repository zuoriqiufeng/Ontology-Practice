> 历史文档（已归档）
> 本文描述的是 `find_bkn.py` / `demo-product_bkn_router` 阶段的旧路由架构。
> 当前项目已迁移到 Hermes Plugin（10 个 Tool）查询 BKN，不再使用以下工具/脚本。
> 保留本文仅供追溯设计演进。

# BKN 两类分工：操作型 vs 知识型

> 来源: Demo Product BKN 实战 (2026-06-23)
> 核心发现: BKN 按用途天然分成两类，不能混在一处

## 两类定义

| | 操作型 BKN | 知识型 BKN |
|------|-----------|-----------|
| **定位** | "怎么做" | "是什么 / 为什么" |
| **内容** | 命令路径、状态机、操作约束 | 错误原因、DB差异、配置要求、架构原理 |
| **来源** | Skill 提取 (SKILL.md → BKN) | 产品文档提取 (docx → BKN) |
| **体积** | 轻量 (~7-60行/文件) | 较深 (~140-220行/文件) |
| **引用** | 通过 Skill symlink 共享 | Agent 直接 read_file/search_files |
| **Qdrant** | 不包含 | 每条嵌入 Qdrant 检索词 |

## Demo Product 实例

### 操作型 (16文件, 466行)
```
/root/.demo-product/stream-agent/bkn/
├── shared/risks.bkn     ← "禁止restart RUNNING" (操作约束)
├── objects/syncrule.bkn ← "STOPPED→RUNNING→STOPPED" (状态机)
└── actions/syncrule.bkn ← "rule_create.py --dry-run" (脚本路径)
```

### 知识型 (5文件, 880行)
```
~/.hermes/demo-product/bkn/
├── risks/risks.bkn           ← "-4073: 源端日志不可读, 3步排查" (诊断)
├── objects/database.bkn      ← "Oracle需归档+附加日志, OB需obcdc" (差异)
├── actions/prerequisites.bkn ← "状态前置: 先确认对象状态机位置" (维度段; 逐操作由 constrained_by 边派生)
├── objects/env_matrix.bkn    ← "Oracle:1521, 权限: GRANT DBA" (速查矩阵)
└── relations/topology.bkn    ← "控制机→iaproxy→iahelper→进程" (架构)
```

## 互补不合并

两条文件在两条不同路径，但路由 Skill (`demo-product_bkn_router`) 统一覆盖：

```
用户问
  ├── "怎么操作" → 操作型 BKN (通过 Skill symlink)
  ├── "为什么报错" → 知识型 BKN (Agent 直接读)
  └── "两个都要" → 路由表引导串行查询
```

## 关键设计决策

1. **不要合并到一个目录**：操作型由 Skill 共享（symlink），知识型独立管理
2. **不要互相引用**：操作型文件不嵌 Qdrant，知识型文件不嵌脚本路径
3. **统一路由入口**：`demo-product_bkn_router` Skill 覆盖两者，Agent 不纠结去哪个
4. **同等结构**：都用 objects/actions/risks/relations 四元目录，格式对齐
