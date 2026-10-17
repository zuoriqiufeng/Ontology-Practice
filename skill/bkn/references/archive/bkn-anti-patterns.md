# BKN 反模式与避坑

> 本季实践中发现的 BKN 设计陷阱

## 陷阱1: Persona 膨胀

**症状**: 把术语表(53条) + 架构 移植到 `~/.hermes/SOUL.md`, 文件从 21行→156行

**后果**: 每次请求多消耗 ~2000 token。10轮对话净增 20000 token 系统开销。

**原则**: Persona 文件只放人格/执行规则。领域知识放独立参考文件, 需要时 search_files 按需加载。

**修正**: 回退 SOUL.md 为 21行, 知识放 `~/.hermes/demo-product/` 独立文件。

---

## 陷阱2: 强制加载

**症状**: SKILL.md 写 "**强制**: 禁止跳过BKN直接执行脚本"

**后果**: 每次操作多 2-3 次 read_file, 只读查询也强制加载。

**原则**: BKN 是按需参考, 不是必选项。只读不查, 写入先查约束, 出错查诊断。

**修正**: 将所有 skill 的 "渐进式加载" 改为 "BKN 按需参考", 移除 "强制" 条款。

---

## 陷阱3: 全量合并对象

**症状**: 一个 `platform.bkn` 放 5 种对象 (131行)

**后果**: 查节点也带入 SyncRule/License, 利用率 23%。

**原则**: 一个对象一个文件。查节点只用 workernode.bkn(7行)。

---

## 陷阱4: 只有 BKN 无 Qdrant

**症状**: BKN 定义了错误码, 但排查步骤只说 "查日志", 没有具体方法。

**原则**: BKN 给骨架(diagnostic steps), Qdrant 填内容(detailed how-to)。每个 Risk 排查步骤嵌入 Qdrant search query。
