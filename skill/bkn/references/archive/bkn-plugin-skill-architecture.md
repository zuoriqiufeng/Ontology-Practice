# BKN-Plugin-Skill 三层架构

> 会话验证 (2026-07-03): Demo Product BKN + Plugin 完整实现
> 持续演进 (2026-08-05): 36+ 文件 BKN（含 SCHEMA/SYNONYMS/templates）+ Plugin 12 Tool（含 RiskGuard/usage_log/lint）

## 三层分工

```
┌─────────────────────────────────────────────┐
│ BKN (知识层)                                 │
│  生成方法: bkn Skill                 │
│  回答: 业务里有什么? 能做什么? 有什么约束?     │
│  格式: .bkn Markdown 文件                   │
│  存放: objects/ actions/ risks/ relations   │
│       + diagnostics/ (诊断路由层，19 号方案)  │
│       + SCHEMA.md / SYNONYMS.md / templates │
│  特性: 稳定不变 (业务语义)                    │
├─────────────────────────────────────────────┤
│ Plugin (查询层)                              │
│  生成方法: 参考 <repo>/demo-product-bkn/plugin/ │
│  回答: 怎么高效查 BKN 数据?                   │
│  格式: Python 模块 + config.yaml             │
│  组件: resolver / relations / supplement     │
│        context_loader / BM25+BGE hybrid      │
│        risk_guard（BKN 驱动护栏）/ usage_log │
│        lint_bkn（质量闸门）/ reload（watch）  │
│  特性: 自动适配 BKN 结构变化                  │
├─────────────────────────────────────────────┤
│ Skill (执行层)                               │
│  回答: 具体怎么操作? (脚本/命令/参数)          │
│  格式: SKILL.md                              │
│  内容: 脚本路径 + 环境 + 参数模板 + 操作经验   │
│  特性: 随版本变化 (SDK/环境/路径)             │
└─────────────────────────────────────────────┘
```

## 模型调用链

```
用户请求
  │
  ├─ Plugin Tool (function calling)
  │   ├── query_product / explain_architecture / ...
  │   ├── resolve_operation("创建规则")
  │   │     → capability + implements: skill:xxx
  │   │
  │   └── return → 模型拿到 Skill 名
  │
  ├─ skill_view("skill_name")
  │     → script / workdir / env / command_template
  │
  └─ terminal(command)
```

## 关键设计决策

1. **Action 只引用 Skill, 不放命令**: implements: skill:xxx
   - BKN 稳定 (capability + params + constraints)
   - Skill 可变 (script + workdir + env)

2. **Plugin 自动发现**: resolver 扫描 *.bkn 文件
   - 新增 Action → 自动注册 capability
   - 不需要改 Plugin 代码

3. **Plugin Tool ≠ Skill**: 
   - Plugin Tool = 查数据的函数 (function calling)
   - Skill = 教模型的文档 (prompt injection)

4. **Qdrant 作为补充搜索**: 
   - BKN confidence=none → Qdrant 混合搜索 (BM25+BGE→RRF)
   - BKN 给骨架, Qdrant 给血肉

## Demo Product 实现参考

- BKN: <repo>/demo-product-bkn/bkn/ (36 文件，含 SCHEMA/SYNONYMS/templates)
- Plugin: <repo>/demo-product-bkn/plugin/ (12 Tool + risk_guard + usage_log + lint/reload 脚本)
- Skills: <repo>/demo-product-bkn/skill/ (操作执行)
- ContextLoader: plugin/context_loader.py（内置 Trim+Toon + 输出预算）
- 配置: config.yaml (Qdrant/Embedding/BKN路径/chunk_mode/risk_guard)
