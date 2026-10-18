# Ontology-Practice

> **状态：v0.1.0-alpha（本地已就绪，待推送远端）**。绿名单迁出、全仓去产品化、规范 7 篇、示例本体、上手文档与 CI 齐备。

**BKN（Business Knowledge Network，业务知识网络）** 的工程实践套件：规范（spec）、可运行参考实现（runtime）、治理工具链（governance）。

BKN 是给 Agent 用的**领域知识层**：
用「类 · 边 · 实例登记」描述一个产品的世界模型，让 Agent 先「想对」再「动手」。
本仓要发布的是 **SPEC ＋ 可运行参考实现 ＋ 治理工具链**（不是又一个 skill 集）。

## 计划中的结构

| 目录 | 内容 | 状态 |
|---|---|---|
| `bkn/` | 格式规范（SCHEMA/SYNONYMS）＋ 模板 ＋ 骨架 | 已迁（待去产品化） |
| `plugin/` | 运行时：BKN 解析、13 个 Tool、图推理、混合检索、可观测 | 已迁（140 文件含产品名，待改写） |
| `skill/` | 7 个通用 `bkn-*` skill（生成/更新/推理/发布/测试/接入/本体） | 已迁（待去产品化） |
| `scripts/` | 治理工具：lint / 版本 / 变更集 / 门禁 / 待审 / 回放 | 已迁 |
| `tools/` | 开源前工具（敏感扫描 `redact.py` 与报告） | 已有 |
| `spec/` | 理论：为什么 BKN / 本体模型 / 格式 / 推理语义 / 治理 / 边界 | ✅ 初稿 7 篇（中文；英译 P4） |
| `docs/` | quickstart / 接入 Agent / 写第一个本体 / FAQ | ✅ 4 篇 |
| `examples/` | 示例本体 `example-product`（2 对象 + 动作/关系片段） | ✅ |
| `tests/` | 测试集（保留运行时通用测试；产品内容相关测试属实例仓，见 `plugin/tests/README.md`） | ✅ |
| `.github/workflows/` | CI（lint ＋ pytest；不依赖 Qdrant） | **待写（P2）** |

## 与 OpenBKN Engineering 的关系

同域已有 [OpenBKN Engineering](https://github.com/)（Apache-2.0，方法论＋skills）。
本仓与其**互补**：它给「怎么做」的技能与方法，本仓给「**可运行、可门禁验证**的工程闭环」——
格式规范、图推理语义、lint/门禁/候选/版本/回滚、可观测与参考实现。

## 许可（拟）

- 代码：Apache-2.0；文档：CC-BY-4.0。
- 本仓**不含**任何厂商官方文档、内部过程记录、现场日志与产品专有技能。

## 维护者须知

```bash
python3 tools/redact.py --root . --report tools/redact-report.md   # 敏感扫描（只读）
```

当前扫描：产品名 140 文件 / 内网 IP 4 文件 / 内部痕迹 41 文件 ⇒ 均为 P2 改写清单（见内部计划 76 号）。
