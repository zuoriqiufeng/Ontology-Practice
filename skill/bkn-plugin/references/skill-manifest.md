# ID → 实现 / 检索源（`plugin/skill_manifest.yaml`）

> **权威文件只有一份**：`plugin/skill_manifest.yaml`（+ `plugin/constants.py` 的常量表）。本页是说明。

## 1. 它解决什么

本体里只写 **ID**（`skill:xxx` / `store:xxx` / `process:xxx`）：
「本体只给思路」的前提是 —— **ID 背后是什么**（哪个集合、哪个 Skill 目录、哪个进程）**不写进 `.bkn`**，而在 Tool 层登记。
这就是**值数据分工制**（02 号 §0.1；24 号 §2.5）。

## 2. 三类 ID

| 前缀 | 是什么 | 权威定义处 |
|---|---|---|
| `skill:*` | 运维 Skill 名 | `skill/` 目录 + 本 manifest |
| `store:*` | 检索源（集合，可带 `#维度` 切片） | `plugin/config.yaml` 的集合名 + 本 manifest |
| `process:*` | 运行时进程对象（7 个） | `plugin/constants.py::PROCESS_IDS` |

## 3. 证据源顺序

38 号批 1 把分支表**收拢到单点**：`constants.EVIDENCE_SOURCES`（+ `EVIDENCE_SOURCES_DEFAULT`）。

| 入参 | 顺序 | 理由 |
|---|---|---|
| `process:iatrack` / `iadumper` / `ialoader` | `store:log_patterns_collection#日志模式` → `store:demo-product_collection` | 源端进程首查日志模式库 |
| `dimension:consistency` / `dimension:state_machine` | `store:demo-product_collection` → `store:log_patterns_collection#日志模式` | 跨切面维度首查主集合 |
| 其它 `process:*` / `dimension:*` | `EVIDENCE_SOURCES_DEFAULT` | 兜底主集合 |
| 其它前缀（如 `class:`） | `[]` | 显式返回空（不再有死分支） |

`BKNResolver.get_evidence_sources()` 已退化为**纯查表**（返回值与收敛前逐字一致）。

## 4. BKN 侧红线

- `.bkn` **可以引用** `store:log_patterns_collection#日志模式` 这类 ID；
- `.bkn` **不得登记** `store:` 命名空间（lint 有检查）；
- 新增集合 = 改 `config.yaml` + 本 manifest + `EVIDENCE_SOURCES`，**不动本体**。

## 5. 常见坑

- 别把 Handler 名当 ID（`search_qdrant` 是 Handler，不是技能身份）；
- `store:集合#维度` 的切片语法必须与 chunk 项目一致，否则**静默落空**；
- 集合改名 / 重建后**必须**同步这里，否则证据源指向不存在的集合。
