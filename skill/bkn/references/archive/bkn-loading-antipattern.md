# BKN 加载反模式 (Anti-Patterns)

> 记录 Demo Product BKN 实践中发现并修正的错误设计。

---

## 反模式 1: BKN 注入 Persona SOUL.md

**现象**: 将 Demo Product 术语表(53条) + 架构移植到 `~/.hermes/SOUL.md`，文件从 21 行→156 行。

**后果**: 每次请求多消耗 ~2000 token，不管用户问什么。10 轮对话净增 20000 token 系统开销。

**修正**: Persona 文件只放人格/执行规则，不放领域知识。领域知识放在独立参考文件。

---

## 反模式 2: BKN 强制加载

**现象**: Skill SKILL.md 要求每次操作必须 read_file BKN 文件（"禁止跳过BKN直接执行脚本"）。

**后果**: 只读查询（查规则列表）也要多 2-3 次 read_file，每次 60-130 行额外上下文。

**修正**: BKN 改为"查漏补缺的参考"。报错必查、写入先查、不懂就查、熟悉跳过。

---

## 反模式 3: 全量合并所有对象

**现象**: 一个 `platform.bkn` 放 WorkerNode + DatabaseNode + SyncRule + CompareRule + License，131 行。

**后果**: 查节点状态也带入 SyncRule 定义，利用率仅 23%。

**修正**: 每个对象独立文件。workernode.bkn(7行)、syncrule.bkn(22行)、dbnode.bkn(8行)。

---

## 反模式 4: 操作型和知识型混在一个文件

**现象**: risk 约束（"禁止restart RUNNING"）和风险诊断（"-4073: 源端日志不可读"）放在同一个 risks.bkn。

**后果**: 查操作约束时也看到诊断细节，查诊断时也看到操作禁止项。上下文浪费。

**修正**: 操作型（`risks/constraints.bkn`，操作约束 + 约束ID）和知识型（`diagnostics/error-codes.bkn` 错误码实例表 + `diagnostics/routing.bkn` 归类边）分开。两者互补但场景不同。

---

## 反模式 5: 知识型 BKN 不挂 Qdrant 引用

**现象**: BKN 文件纯文本，没有标注 Qdrant 搜索词。

**后果**: Agent 从 BKN 得到"需要查归档日志"但不知道用什么关键词查 Qdrant。

**修正**: 每条 BKN 知识项标注 `Qdrant("关键词")`，让 Agent 知道精准的 Qdrant 搜索词。
