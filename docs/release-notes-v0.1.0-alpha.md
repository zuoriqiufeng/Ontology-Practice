# Release v0.1.0-alpha — Ontology-Practice

**BKN（Business Knowledge Network，业务知识网络）的工程实践套件**：规范 ＋ 可运行参考实现 ＋ 治理工具链。

## 这个版本有什么

- **规范 `spec/` 7 篇**：为什么 BKN（三个不变量：方法/事实分离、值委托、可推可溯）、本体模型（四元终态/命名空间/TBox-ABox）、`.bkn` 格式、推理语义（边语义/遍历边界/能推推不出/L0–L4）、治理模型（候选/审批/门禁/版本/回滚/可观测）、BKN 与 Skill 的边界。
- **运行时 `plugin/`**：BKN 解析、13 个工具、图遍历推理、混合检索（无 Qdrant 自动降级）、可观测（`mention_resolve` / `reasoning_path` / `answer_source`）。
- **治理工具链 `scripts/`**：lint、版本身份（文件清单哈希）、变更集、候选/待审、回滚演练、日志统计、案例回放门禁。
- **示例 `examples/example-product/`**：2 个对象 ＋ 动作/关系片段，演示别名同址与值委托。
- **上手 `docs/` 4 篇**：quickstart、接入 Agent、写第一个本体（含常见 lint 报错）、FAQ（Q27/边界/降级/版本/候选/别名）。

## 设计取舍（先说清，避免误读）

1. **码不进本体**：错误码空间无上界，码只作入口，语义类别 + 边推理才是本体该管的事。
2. **BKN 不返回命令**：本体给「做什么、看哪、找谁」，命令由 Skill 提供。
3. **测试只带运行时通用部分**：断言具体产品本体的测试属实例仓（清单见 `plugin/tests/README.md`）。
4. **包名暂用 `plugin`**：历史命名，v0.2 计划改为 `bknkit`。

## 与 OpenBKN Engineering 的区别

理念原型是**爱数（AISHU）的 BKN 本体理论**；本项目是它在**产品运维**场景的工程实践（可运行、可机检）。
与 OpenBKN Engineering（方法论 ＋ 技能集）**互补不替代**，本仓未复制其源码。

## 验收（发布前实测）

```
双根 lint rc=0（errors 0 / warnings 0）｜ pytest 268 passed
redact 五类 0（产品名/厂商/内网IP/邮箱/内部痕迹）｜ compileall 0 错
```
