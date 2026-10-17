# 文档驱动 BKN 设计方法论

> **已废止，勿引用**：`diagnostics/` 八文件清单已整体退场——现行四元见 `bkn/SCHEMA.md`。

> ⚠️ **2026-09-24 更新（23 号方案）**：`index` / `matrix` 段类型已废止；本体层只留定义（KV）+ 关系（边）+ 实例登记（带命名空间 ID 的表）。值数据（版本表/矩阵/命令/参数）下延 Skill references，路由下延 Tool 常量（`plugin/*.py` 或 `skill_manifest.yaml`），叙述下延 `doc/`。基准见 `doc/build/demo-product-bkn/24-bkn_ontology.md`；本文中出现的旧文件路径（diagnostics/、env_matrix.bkn、compatibility.bkn、architecture.bkn）与矩阵/索引段写法均以 23 号为准。



> 本次会话 (2026-07-01) 从 8 份源文档生成 BKN 的完整方法论
> 持续演进 (2026-08-05): 当前 36 文件（含 SCHEMA/SYNONYMS/templates 等规范成员）

## 源文档分析方法

对每份文档标注覆盖的 BKN 层和价值密度:

| 文档类型 | 典型覆盖层 | 价值密度 | 处理方式 |
|---------|-----------|:--:|------|
| 技术白皮书 | L1-L4 | ★★★★★ | 结构化提取核心定义 |
| 实现原理汇总 | L2 | ★★★★★ | 扩展原理矩阵 |
| 版本使用指引 | L4-L5 | ★★★★ | 精确版本+端口矩阵 |
| 配置手册 | L5 | ★★ | 仅提取业务约束 |
| 界面操作手册 | L5 | ★ | 确认流程,不提取细节 |

## 生成顺序

1. **先独立后关联**: product.bkn → compatibility.bkn → architecture.bkn (不依赖其他)
2. **再场景**: objects/scenario-*.bkn (依赖 product + architecture + compatibility)
3. **再关系**: relations/ (跨层关联,依赖所有文件；4 文件 topology/scenario/action_routing/references)
4. **最后路由**: network.bkn (索引,依赖所有文件)
5. **补入口**: SKILL.md (最后,汇总全局)
6. **诊断域（有诊断内容时）**: diagnostics/ 八文件（classes/routing/error-codes/symptom-router/class-db-matrix/store-registry/log-map/related-skills；tools-index 已删并入 Skill，20 号方案清理）

## 结构对齐检查清单

- [ ] objects/ 是否完整覆盖所有业务实体（带 frontmatter）?
- [ ] actions/ 每个 Action 是否绑定到 Object + access_type + binding_type?
- [ ] risks/ 是否只含 constraints.bkn（约束ID 机器可读列）? 诊断内容（错误码/症状/诊断类）是否收拢在 `diagnostics/`?
- [ ] diagnostics/（诊断域时）是否含 classes.bkn（诊断类定义）+ routing.bkn（归类/取证/路由边）+ error-codes.bkn（错误码唯一权威源）?
- [ ] relations/ 是否只用 12 种关系类型（见 RELATION_TYPES.md）且每段带中文名?
- [ ] 对象层 (product/scenario-*/四要素) 是否互补、值数据是否已下延 Skill?
- [ ] SKILL.md 是否定义触发条件 + 渐进式加载?
- [ ] network.bkn 是否完整索引所有文件 + 实体语义索引?（别名走同址字段，不建中央同义词表）
- [ ] 有无重复文件 (如两个 rule_lifecycle.bkn)?
- [ ] 路径引用是否一致?
- [ ] lint_bkn.py 是否无 error?

## 本次会话产物

- BKN 文件: <repo>/demo-product-bkn/bkn/
- 设计文档: doc/build/demo-product-bkn/
- Plugin 实现: <repo>/demo-product-bkn/plugin/
- ContextLoader: plugin/context_loader.py（内置）
