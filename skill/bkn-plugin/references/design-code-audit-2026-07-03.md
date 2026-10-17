# 设计文档 vs 源码一致性审计报告

> 日期: 2026-07-03
> 审计范围: `<repo>/bkn/hermes-bkn-plugin/` (5个设计文档) vs `<repo>/demo-product-bkn/plugin/` (源码)

## 发现的 13 处不一致

| # | 文件 | 不一致 | 严重度 |
|---|------|--------|--------|
| 1 | `plugin.yaml` L3 | description: "9个Tool" 实际 provides_tools 10个 | 🔴 |
| 2 | `tools.py` L30 | _wrap 注释 "四象限降权" v3.1 已移除 | 🟡 |
| 3 | `plugin-architecture.md` | 架构图列出"双维评估/四象限/会话去重"v3.1 已移除 | 🔴 |
| 4 | `plugin-architecture.md` L169 | _wrap 注释 "v2.4: 四象限+gap精准匹配" | 🟡 |
| 5 | `README.md` L139 | config.yaml 注释 "v2.3: quality 阈值" 配置已移除 | 🟡 |
| 6 | `supplement-mechanism.md` L669-857 | 186行 v2.3 质量评估文档需标记 deprecated | 🔴 |
| 7 | `supplement-mechanism.md` L1-5 | 头部说 v3.1 移除 → 正文仍完整保留 | 🔴 |
| 8 | `README.md` L182 | 补充策略标注 v2.4 → 实际 v3.1 | 🟡 |
| 9 | `README.md` L204 | 底部日期 "v2.4: 精度提升..." | 🟡 |
| 10 | `tool-design.md` L520-633 | Tool 10 缺 Handler 逻辑伪代码(仅 Schema) | 🟡 |
| 11 | `plugin-architecture.md` L136 | supplement.py 描述未提维度追踪/覆盖度 | 🟡 |
| 12 | `implementation-plan.md` | 底部日期 v2.4 | 🟡 |
| 13 | `supplement-mechanism.md` L863 | L2 v2.4 章节未标记 deprecated | 🟡 |

## 典型不一致模式

| 模式 | 现象 | 审计方法 |
|------|------|---------|
| **数字漂移** | 文档说 N 个 Tool，实际 N+1 个 | 数 `provides_tools` / `SCHEMAS` / `HANDLERS` |
| **残留引用** | 注释/架构图引用已移除功能 | grep 功能名 → 确认源码是否还存在 |
| **版本链断裂** | README v2.4 → 实际 v3.1 | 全局搜索版本号，与 `plugin.yaml` 对齐 |
| **deprecated 未标记** | 已归档代码的设计文档仍在正文 | 检查归档文件对应章节 |
| **缺失设计段** | 新 Tool 只有 Schema 无 Handler | 对比旧 Tool 的三段式结构 |

## 修复摘要

| 文件 | 改动数 |
|------|--------|
| `plugin.yaml` | 1 (description) |
| `tools.py` | 1 (_wrap 注释) |
| `plugin-architecture.md` | 4 (架构图 + _wrap + config + 底部) |
| `README.md` | 4 (supplement 描述 + config 注释 + 策略版本 + 日期) |
| `supplement-mechanism.md` | 2 (v2.3 + v2.4 标记已归档) |
| `tool-design.md` | 1 (Tool 10 Handler 逻辑) |
| `implementation-plan.md` | 1 (日期) |
| **合计** | **14 处修改** |

## 审计流程

```bash
# 1. 加载 skill
skill_view("bkn-plugin")

# 2. 并行读取所有设计文档
read_file("<repo>/bkn/hermes-bkn-plugin/README.md")
read_file("<repo>/bkn/hermes-bkn-plugin/plugin-architecture.md")
read_file("<repo>/bkn/hermes-bkn-plugin/tool-design.md")
read_file("<repo>/bkn/hermes-bkn-plugin/supplement-mechanism.md")
read_file("<repo>/bkn/hermes-bkn-plugin/implementation-plan.md")

# 3. 读取关键源码
read_file("<repo>/demo-product-bkn/plugin/plugin.yaml")
read_file("<repo>/demo-product-bkn/plugin/schemas.py")
read_file("<repo>/demo-product-bkn/plugin/tools.py")
read_file("<repo>/demo-product-bkn/plugin/config.yaml")

# 4. 逐项对照 12 条检查清单
# 5. 一次性 patch 所有不一致
```

## 教训

1. 每次 supplement 管道重构后，必须同步更新架构图
2. 版本号建议统一使用 plugin.yaml 的 version 作为主版本
3. 功能移除时不只删代码，设计文档对应章节加 `[已归档]` 标记
4. 新增 Tool 时，设计文档应包含 Schema + Handler 逻辑 + 返回示例三段
