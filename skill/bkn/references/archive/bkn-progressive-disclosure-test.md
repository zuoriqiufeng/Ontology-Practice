> 历史文档（已归档）
> 本文描述的是 `find_bkn.py` / `demo-product_bkn_router` 阶段的旧路由架构。
> 当前项目已迁移到 Hermes Plugin（10 个 Tool）查询 BKN，不再使用以下工具/脚本。
> 保留本文仅供追溯设计演进。

# BKN 渐进式披露测试记录

> 测试日期: 2026-06-23 | 环境: Hermes Agent + Demo Product Skills

## 测试场景

5 个 Demo Product Skill 使用 BKN 优化，从"查询控制台规则"触发完整渐进式披露链路。

## 优化结果

| 指标 | 优化前 | 优化后 |
|------|--------|--------|
| 5个SKILL.md总行数 | ~236行 | 146行 |
| L0 Token | ~6000 | ~1200 |
| BKN共享层 | 无 | 6文件 245行 |
| 单场景按需加载 | — | ~900 tokens (L0+L1) |
| Token节省 | — | **80%** (L0模式) |

## 渐进式披露 4 步流程

```
用户: "查询控制台规则"
  │
  ├─ L0: SKILL.md 注入 (~400 tokens)
  │   包含: 渐进式加载表 + 状态机 + 全局约束
  │
  ├─ L1: read_file("bkn/actions/rule_lifecycle.bkn") (~500 tokens)
  │   匹配: "查询 → query_demo-product_sync_rule_info.py --list"
  │
  ├─ Risk: read_file("bkn/risks/all.bkn")
  │   "查询"是只读操作，无Risk触发 ✓
  │
  └─ 执行: terminal → 返回 9 条规则 ✓
```

## BKN 知识网络结构

```
~/.demo-product/stream-agent/bkn/
├── network.bkn                    # 根索引
├── objects/platform.bkn           # 5个Object
├── relations/topology.bkn         # 创建前置依赖链
├── actions/rule_lifecycle.bkn     # 规则操作
├── actions/other_lifecycle.bkn    # 节点/数据库/对比
└── risks/all.bkn                  # 16条约束(CRITICAL×7+HIGH×5+MEDIUM×4)
```

## 关键发现

1. **Hermes 需要手动 /skill 加载** — Agent 不会自动扫描磁盘上的 BKN 文件，需要 SKILL.md 被注入 System Prompt 后才会按渐进式协议执行
2. **`read_file` 是 Hermes BKN 的替代品** — Hermes 无 `@include` 指令，通过 Agent 主动 read_file 实现等效的渐进式披露
3. **Risk 文件需要全局可达** — 所有 5 个 Skill 共享 `bkn/risks/all.bkn`，避免重复定义

## 与 KWeaver ContextLoader 对比

| 维度 | KWeaver ContextLoader | Hermes BKN |
|------|---------------------|-----------|
| 加载方式 | Schema定位→对象查询→结构化整理 | SKILL.md索引→Agent read_file |
| Trim(过滤) | 自动过滤评分/技术字段 | Agent 自主决定读哪些文件 |
| Toon(压缩) | 紧凑结构化格式 | Markdown 表格天然紧凑 |
| Token节省 | 27-33% | 80% (L0模式, 全量vs渐进式) |
