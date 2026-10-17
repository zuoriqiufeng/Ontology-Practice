# BKN 构建工作流 (2026-07-02 实战总结)

> **已废止，勿引用**：本文的诊断域写法（`classes.bkn` / `symptom-router.bkn` / `class-db-matrix.bkn`）已于 19/20 号收敛——现行＝`dimension:*`（`bkn/objects/dimensions.bkn`）+ 边（`bkn/relations/process_topology.bkn`）。

> ⚠️ **2026-09-24 更新（23 号方案）**：`index` / `matrix` 段类型已废止；本体层只留定义（KV）+ 关系（边）+ 实例登记（带命名空间 ID 的表）。值数据（版本表/矩阵/命令/参数）下延 Skill references，路由下延 Tool 常量（`plugin/*.py` 或 `skill_manifest.yaml`），叙述下延 `doc/`。基准见 `doc/build/demo-product-bkn/24-bkn_ontology.md`；本文中出现的旧文件路径（diagnostics/、env_matrix.bkn、compatibility.bkn、architecture.bkn）与矩阵/索引段写法均以 23 号为准。



## 标准流程

```
1. 收集源资料 (官网/白皮书/手册/运维环境)
2. 分析→提取结构化知识
3. 设计BKN结构 (要素 × 段形态 × 域, 符合KWeaver规范 + 19 号方案双层定位)
4. 编写.bkn文件 (Markdown表格 + section + kv + frontmatter)
5. 构建relations/ (12种关系: requires/implements/constrains/constrained_by/prerequisite/risks_of/has_action/references/runs_on/registered_on/supports/implements_skill，字典见 bkn/relations/RELATION_TYPES.md)
6. 构建Plugin (resolver→relations→context_loader→tools→schemas→supplement)
7. 验证一致性 (lint_bkn.py 结构校验 + 设计文档↔实际文件 双向对账, 修复偏差)
```

## 结构规范

```
bkn/
├── SKILL.md           入口 (触发条件+加载策略)
├── network.bkn         路由索引
├── objects/            根级 (KWeaver 四要素)
│   ├── Object1.bkn     本体定义 (状态机/属性/关联)
│   └── Object2.bkn
├── actions/            根级 (implements: skill:xxx)
│   ├── lifecycle.bkn   Action=capability+params+constraints+notes
│   └── lifecycle2.bkn
├── risks/              根级
│   └── constraints.bkn 操作约束
├── diagnostics/        诊断路由层 (19 号方案: 症状/诊断类/错误码/矩阵收拢于此)
│   ├── classes.bkn     诊断类定义 (class:*)
│   ├── routing.bkn     类定义表 + 4 组路由边
│   ├── error-codes.bkn error:* 实例表 (错误码唯一权威源)
│   ├── symptom-router.bkn  症状定义 + 分析思路
│   ├── class-db-matrix.bkn 诊断类 × 库差异矩阵
│   ├── store-registry.bkn  检索源注册集
│   ├── log-map.bkn / related-skills.bkn  边视图
├── relations/          根级 (4 文件: topology/scenario/action_routing/references)
├── topology.bkn        进程矩阵
├── product.bkn         上下文层 (产品特有)
├── architecture.bkn
├── compatibility.bkn
├── objects/scenario-*.bkn
└── （O-域互补细节已于 24 号并入 objects/ 与 risks/）
```

## 关键决策

- **Action 不绑定命令**: capability + implements: skill → Skill 提供 script/command/版本差异
- **四要素在根级**: objects/actions/risks/relations 符合 KWeaver；诊断域与运维细节按其语义类别并入四目录（24 号）
- **relations 用 KWeaver 段落格式**: `## Relation:` 段 + `**关系类型**:` 字段 + `映射规则` 区逐行 `` `src` → `tgt` ``（旧箭头语法 `A → rel → B` 已废弃）
- **设计文档与实际文件对齐**: 每次变更后同步更新设计文档

## 示例: Demo Product BKN

- 46个.bkn文件（含 SCHEMA.md/SYNONYMS.md/templates/ 等规范成员）
- 5个Object (syncrule/dbnode/worknode/compare/env_matrix)
- 7组Action (rule/node/db/compare lifecycle + iadebug + failover + proxytest) → 对应 Skill
- 1个风险文件 (risks/constraints.bkn，含约束ID机器可读列)；诊断内容在 objects/（进程对象与归路边）与 risks/constraints.bkn（诊断原则）；清单在边里，别名在 constants
- 来源: 技术白皮书 + 实现原理汇总 + 9.1.4使用指引/配置手册 + 官网
