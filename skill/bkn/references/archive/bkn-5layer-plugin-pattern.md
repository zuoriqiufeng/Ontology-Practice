# BKN 五层 + Plugin 查询引擎模式

> 从「文档驱动的 5 层 BKN」到「Plugin 封装 Tool API」的架构演进

## 背景

2026-06-30 ~ 07-01，在 Demo Product BKN 设计过程中，经历了三个阶段:

### 阶段 1: 纯 Skill 模式 (当前)
```
Agent → Skills 加载 .bkn 文件 → Agent parse + 推理
```
- Token 消耗大 (200-500行/次)
- 跨层关联靠模型推理，不稳定
- 适用于 BKN 规模小的场景

### 阶段 2: 五层业务网络 (设计完成)
BKN 升级为产品级业务网络，覆盖:
- L1 产品名片 → L2 技术架构 → L3 方案场景 → L4 兼容性 → L5 操作运维
- relations.bkn 提供跨层关联
- 双轨合并 (操作型 + 知识型)
- 设计文档: `doc/build/demo-product-bkn/`

### 阶段 3: Plugin 查询引擎 (已实施，持续演进)
```
Agent → Plugin Tools → BKN 解析引擎 → 返回精准数据
       ↑ 12个Tool API  ↑ 确定性推理    ↑ 30-80行/次
```
- 模型从「资料阅读者」变为「方案顾问」
- Plugin 内置: 关系推理、约束验证、三层补充机制、RiskGuard 护栏、块感知检索
- 实现: `<repo>/demo-product-bkn/plugin/`

## 核心洞察

### BKN 是数据事实源，Plugin 是查询引擎

> 19 号方案：「本体」称谓仅属业务域；诊断域为**诊断路由层**（程序式/检索式）。BKN 整体是数据事实源
> （业务本体 + 诊断路由层），Plugin 是其投影查询引擎。

```
BKN 文件 (~/.hermes/demo-product/bkn/)     ← 静态知识，独立维护
    ↕ 软链
Plugin Tools (hermes-demo-product-bkn)     ← 动态查询，Tool API
    ↕ function calling
模型 (Agent)                            ← 方案顾问，推理表达
```

### 三层补充策略

BKN 不充分是常态。Plugin 内置闭环:
- L1: confidence=partial/none + gaps 标记 → gap_log 自动记录
- L2: Qdrant 回退 → web_search → 用户实时补充
- L3: scan_gaps.py → 用户确认 → 回写 .bkn → 向量化

### 文档源分析方法

从产品文档生成 BKN 时，区分两种类型:
- **业务层资料** (白皮书/实现原理/官网): → L1-L4 业务知识
- **操作层资料** (配置手册/界面手册/安装手册): → L5 运维知识

不要把所有操作步骤都注入 BKN — BKN 是业务网络，不是操作手册。

## 适用场景

- 当 BKN 规模 > 500 行时，考虑 Plugin 封装
- 当跨层关联复杂时 (5+ 关联类型)，Plugin 的确定性推理价值显著
- 当 BKN 数据频繁缺失时，三层补充机制自动闭环

## 参考

- Demo Product BKN 5层设计: `doc/build/demo-product-bkn/24-bkn_ontology.md`
- Demo Product Plugin 设计: `doc/build/demo-product-bkn/01-architecture.md`
