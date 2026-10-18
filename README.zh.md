# Ontology-Practice（BKN 本体工程实践套件）

**BKN（Business Knowledge Network，业务知识网络）** 是给 Agent 用的领域知识层：
用「类 · 边 · 实例登记」描述一个产品的世界模型，让 Agent 先「想对」再「动手」。

本仓提供三样东西：

| 组成 | 内容 |
|---|---|
| **SPEC**（规范） | 为什么这么设计、本体模型、`.bkn` 格式、图推理语义、治理模型、BKN 与 Skill 的边界 |
| **运行时**（可跑） | `plugin/`：BKN 解析、13 个 Tool、图遍历推理、混合检索（可降级）、可观测 |
| **治理工具链** | `scripts/`：lint、版本与变更集、候选/待审、回滚演练、日志统计、回放门禁 |

## 快速开始

```bash
pip install -e .
bkn-lint --error-only bkn/        # 校验本体骨架
```

完整上手（写第一个本体、接入 Agent）见 `docs/`。

## 与 OpenBKN Engineering 的关系

[OpenBKN Engineering](https://github.com/)（Apache-2.0）提供 BKN 的**方法论与技能**；
本仓提供**可运行、可门禁验证的工程闭环**：格式规范、推理语义、lint/门禁/候选/版本/回滚、可观测与参考实现。两者互补。

## 许可

代码 Apache-2.0，文档 CC-BY-4.0。本仓不含任何厂商官方文档、内部过程记录或产品专有技能。
