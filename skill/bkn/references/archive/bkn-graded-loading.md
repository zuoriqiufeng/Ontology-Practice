# BKN 信息分级 (按需参考)

> **已废止，勿引用**：`bkn/diagnostics/classes.bkn` / `class:*` 已收敛——现行＝`dimension:*`（`bkn/objects/dimensions.bkn`）。

BKN 文件按信息重要性分 L0/L1/L2 三级。这不是强制加载流程，而是告诉 Agent "需要查什么时去哪个文件找"。

## 核心原则

**BKN 是查漏补缺的参考，不是每次操作的必选项。**

- 常规操作：直接执行，不加载任何 BKN（skill 内建信息已足够）
- 遇到不确定：按以下分类精准定位对应文件

## 分级定义 (信息优先级)

| 层级 | 含义 | 内容 | 体积 |
|------|------|------|------|
| **L0** | 内建常驻 | 状态机、全局硬约束（已在 SKILL.md 内） | ~12行 |
| **L1** | 按需查证 | 对象属性、命令参数、操作步骤 | ~20-60行 |
| **L2** | 风险咨询 | 写操作风险边界、异常处置策略 | ~20行 |

## 什么时候该查 BKN

| 信号 | 查哪里 |
|------|--------|
| "这个参数是什么意思" | L1 objects |
| "这个命令怎么用" | L1 actions |
| "这样做有没有风险" | L2 risks |
| "为什么操作失败了" | L1 → L2 关联排查 |
| (正常操作,没遇到问题) | **不查** |

## SKILL.md 参考表模板

```markdown
## BKN 按需参考

| 遇到问题时 | 参考文件 | 内容 |
|-----------|---------|------|
| 不确定对象定义 | bkn/objects/X.bkn | X对象属性 |
| 不确定操作命令 | bkn/actions/X.bkn | 命令参数表 |
| 写操作风险评估 | bkn/risks/constraints.bkn | 风险边界（L0/L2 分级 + 约束ID） |
```

## L0 内容选择原则

只保留**写操作硬约束**（违反会出事的）：
- 状态机速查（5条转换规则）
- CRITICAL 级风险（7条）
- 操作的全局禁止项（跳dry-run/直接restart RUNNING）

不放：
- 脚本路径（L1 action 中有）
- 参数详情（L1 object 中有）
- MEDIUM 级风险（只读操作无关）

## 文件拆分粒度

**差**: 一个 `platform.bkn` 放 5 种对象（131行，查节点也带入 SyncRule/License，利用率 23%）

**好**: 每个对象独立文件：
```
objects/workernode.bkn  (7行)   ← 查节点只用这个
objects/syncrule.bkn    (22行)  ← 查规则只用这个
objects/dbnode.bkn      (8行)
```

## 跨 Skill 共享

共享内容放统一的 `bkn/risks/`（业务约束）与 `bkn/diagnostics/`（诊断路由层），各 Skill 通过 BKN Plugin Tool 或直接 read_file 引用：

```
bkn/risks/constraints.bkn      ← 操作约束唯一定义（L0/L2 分级 + 约束ID）
bkn/diagnostics/error-codes.bkn  ← 错误码属性唯一权威源（error:* 实例表，批 5a-5 聚合）
bkn/diagnostics/classes.bkn      ← 4 个跨切面维度类（class:*，20 号方案）
bkn/diagnostics/routing.bkn      ← 类定义表 + 归类/取证/路由边
skill SKILL.md:
  → 通过 Plugin Tool 查询，或 read_file("bkn/risks/constraints.bkn") # L2段
```

## 上下文效益分析

BKN 的效益来自"多读文件但少读垃圾"：

```text
传统全量: SKILL.md 377行 → 其中 85% 行与当前操作无关
BKN 按需: SKILL.md 内建行 + 仅在不确定时 read_file 对应文件
```

**核心优势**：BKN 让 Agent 有"知道去哪查"的能力，而非每次操作必须查。

| 维度 | 传统 | BKN |
|------|--------|--------|
| SKILL 体积 | 377行/19.6KB 全量 | 102行/4.4KB 内建 + 按需查 |
| 首次注入 | 19.6KB | 4.4KB（**-78%**） |
| 遇到不确定 | 可能瞎猜 | 精准查对应文件 |
| 风险可见性 | 散落各处 | L0/L1/L2 分级 |
| 跨 skill 共享 | 重复定义 | shared/ 一处修改全局生效 |
| 额外调用成本 | 0 | 仅在不确定时 1-2 次 read_file |

## 按需加载优化：三种一级检索方案

大文件（如 SOUL.md 158 行）查单个术语时，`read_file` 按行号截取仍浪费。三种渐优方案：

| 方案 | 做法 | 单术语 | 架构/批量 | 改动 |
|------|------|--------|----------|------|
| **C: search_files** | `search_files("iatrack", path="SOUL.md", context=2)` | 1次, ~5行, **最省** | 不适用(需语义) | 零 |
| **B: TOC索引** | 文件顶部加行号目录 → 先读TOC → 精确定位 | 2次, ~30行 | 1次, ~48行 | 改文件 |
| **A: 拆分文件** | term.md + arch.md | 1次, ~68行 | 1次, ~48行 | 建文件 |

**决策**: C 优先（单术语），B 次选（需要批量语义理解时），A 兜底（文件太大 300+ 行时）。

```text
# TOC 索引格式（方案B）
术语表始5  架构始71  附录始121
```

## 陷阱：Persona SOUL.md 膨胀

**现象**: 把 Demo Product 术语表(53条) + 架构 移植到 `~/.hermes/SOUL.md`，文件从 21 行→156 行。

**后果**: 每次请求多消耗 ~2000 token，不管用户问什么。10 轮对话净增 20000 token 系统开销。

**原则**: Persona 文件只放人格/执行规则，不放领域知识。领域知识放在独立参考文件，需要时用 `search_files` 或 `read_file` 按需加载。
