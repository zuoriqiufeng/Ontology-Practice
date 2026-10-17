# BKN 同义词维护规范（SYNONYMS）

> **中央表已删除，别名全部同址化。**
>
> 曾经的中央表做法（同义词集中在单一宿主的 7 张子表里）已废止——类别划分保留，别名与
> 它映射的「基点」**同址存放**。
>
> **理由**：① 中央分表随现场实例**无上界增长**（新对象/新动作/新症状各占一行），违反本体判据
> （段数应由语义骨架决定，不由实例数决定）；② 归一化实际由 **LLM 在上下文完成**——LLM 要输出
> 规范 ID 就得知道「有哪些规范 ID 可选」，候选来自检索回来的 BKN 文本，**同址 = 同 chunk =
> 一起被召回**。**同址字段首先是给 LLM 的提示材料，其次才被 `resolve_synonym()` 读取**；
> 放中央表反而与基点不同段。
>
> **现状**：`_build_synonym_index()` 扫同址字段构建索引，`resolve_synonym()` 已在
> `diagnose_error` / `get_prerequisites` / `resolve_operation` / `resolve_relation`
> 四个 Tool 入口接线（不再是死代码）。

---

## 类别与宿主（同址位置）

| 类别 | 宿主（同址位置） | 基点 | 示例 |
|------|----------------|------|------|
| 对象（业务/主机/DB 等） | `objects/*.bkn` frontmatter `aliases:` | frontmatter `id` | 规则 → syncrule |
| 动作 | `actions/*.bkn` 段内 `- aliases:` | `capability` | 创建规则 → create_sync_rule |
| 症状 | `plugin/constants.py::SYMPTOM_ALIASES`（值数据层） | `symptom:*`（ID 空间 = `suspected_in` 边） | 同步卡住 → incremental_stuck |
| 错误码 | `plugin/constants.py::ERROR_ALIASES` | 规范码（ID 空间 = `suspected_in` 边） | 登录失败 → ORA-01017 |
| 场景 | `objects/scenario-*.bkn` 的「关键词」行 | `场景 ID` | 双活 → dual_active |
| 组件（进程） | `objects/*.bkn`（进程对象）frontmatter `aliases:` | `process:*`（进程名；注册集 `PROCESS_IDS`） | 装载进程 → ialoader |
| 检查维度 | `plugin/constants.py::DIMENSION_ALIASES` | `dimension:*`（类集 = `objects/dimensions.bkn`） | 状态冲突 → state_machine |
| 数据库 | `plugin/constants.py::DB_ALIASES`（已在生产链路，`normalize_db()` 消费） | 规范库名 | pg → PostgreSQL |
| 运维（Skill 名） | 各 `skill/*/SKILL.md` frontmatter `triggers:` | Skill 名 | 装机 → demo-product-product-deploy |

**机械变体不进 BKN**：错误码的口语/不规范写法（`4073` / `错误4073` / `ORA1555` / `YAS-2276`）
由 `BKNResolver._error_code_variants()` 从规范码**派生**；数据库大小写变体由 `normalize_db()`
的 `lower()` 归一。BKN 里只写**有语义的别名**（如 `日志解析异常`、`崖山增量异常`）。

## 维护规则

1. 同址字段内同义词用英文逗号或中文逗号分隔，解析时统一小写匹配；
2. 规范ID 必须与 objects/actions 中的实际 ID 一致（lint 做孤儿校验）；
3. 错误码：登记表「别名」列写语义别名；格式归一由 `normalize_error_code()` 负责
   （4 位数字补负号、`ORA-?01555` → `ORA-01555`），检索命中由 `_extract_exact_terms()` 负责；
4. 底层诊断工具别名（dumpredo / dumptxn / ...）不在此维护，由 `skill:demo-product-db-diagnostics` 管理；
5. **运维类（Skill 名）不进 BKN 索引**：宿主是 Skill 自己的 `triggers:`，由 Agent 侧的
   Skill 选择机制消费，不属于 BKN 的规范 ID 空间——原中央表把「数据不一致」覆盖成 skill 名
   正是这样造成的冲突（既有 `test_symptom_synonyms` 失败）；
6. **未入表的新口语叫法不入任何表**，靠 BM25 / 向量检索兜住；高频且 **LLM 拿不准**
   （检索命中分散在多个实体，或 top-1 分数持续偏低）的，从 `gap_log.jsonl` 反哺回同址字段
   （`params` 存用户原文且未归一化，天然是采集器）。

## 归一化的两条通道

归一化只在**精确键查询**通道上必要（如 `resolve_operation` 查 `_operations[cap]`）；
**检索通道**（`search_qdrant` 及所有工具的降级路径）走 BM25 + 向量，**不需要归一化**，天然接住没见过的说法。

```
精确键通道：用户输入 → resolve_synonym() 精确匹配（小写，读同址字段）
                    → 无匹配 → normalize_error_code() 格式归一（若像错误码）
                    → 仍无匹配 → 返回原文 → 后续查空 → gap_log 留证

检索通道：  用户输入 → bm25_search() + BGE 向量 + RRF 融合 → 无需归一化
```

## 接线点

| Tool | 归一化入参 |
|------|-----------|
| `diagnose_error` | `error_code`（先 `normalize_error_code` 再 `resolve_synonym`） |
| `get_prerequisites` | `operation` |
| `resolve_operation` | `operation` |
| `resolve_relation` | `source_entity`（含 `:` 的 O-域命名空间节点不归一） |

---

