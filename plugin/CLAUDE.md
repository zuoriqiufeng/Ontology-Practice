# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Quick links

- Build & deploy: `../doc/build/demo-product-bkn/40-build.md`
- Architecture: `../doc/build/demo-product-bkn/01-architecture.md`
- Module responsibilities: `../doc/build/demo-product-bkn/30-modules.md`
- Design constraints: `../doc/build/demo-product-bkn/10-design_constraints.md`
- Config reference: `../doc/build/demo-product-bkn/41-config_reference.md`
- Tool details: `../doc/build/demo-product-bkn/31-tools.md`
- Design rules checklist: `../doc/build/demo-product-bkn/11-design_rules_checklist.md`
- Review checklist: `../doc/build/demo-product-bkn/42-review_checklist.md`

## What you need to know before changing code

demo-product-bkn Plugin is a Hermes knowledge plugin for the Demo Product data replication product. It exposes 13 Tools for product knowledge, architecture, solution design, compatibility checks, diagnostics, prerequisites, relation traversal, operation resolution, vector search fallback, multi-DB link diagnostics, action risk checking, and mechanism attribution. **v3.5**: BKN partial 时 Skill 与 Qdrant 同级并列（`_skill_recommendation` + `ACTION_REQUIRED`）。

### High-level flow

```
Hermes calls Tool
    ↓
Tool handler (tools.py)
    ↓
BKNResolver / RelationTraverser / supplement.search_qdrant
    ↓
assess_confidence() + fallback_to_qdrant()
    ↓
ContextLoader.process()
    ↓
return to Hermes
```

### Highest priority principle: BKN gives ideas, Skill gives concrete design

- **BKN (`.bkn` files in `bkn/`) only contains human-readable ideas, analysis directions, risk context, and Skill pointers.**
- **Skill (`skill/*/`) owns concrete command templates, parameter details, output interpretation, and execution decisions.**
- **Plugin (`plugin/`) only routes queries to BKN and returns structured data + recommended Skill names. It never returns executable command strings.**

When editing BKN files, never add command templates, parameter explanations, SQL snippets, or step-by-step execution trees. If you find such content in BKN, move it to the relevant Skill.

### Key abstractions

- **BKN**: `.bkn` Markdown files in `bkn/` — the stable semantic layer.
- **Plugin**: Python code in `plugin/` — parses BKN, registers Tools, performs queries and fallback search.
- **Skill**: `SKILL.md` files in `skill/` — declares how an operation is executed (script, env, command template).

**Boundary note for `diagnose_db_link`**: The Tool only resolves the database type, assembles the error-code diagnosis guide from ontology edges + constants (`_extract_bkn_context`: `suspected_in` / `has_class` / retrieval guide), and recommends required/optional Skills (derived from the ontology + skill manifest). It does **not** return action lists or concrete command strings. Symptom/error-code → action routing and executable command building are owned entirely by the Skill (`skill/demo-product-db-diagnostics/{db}.md` markdown sub-skills, sharded by DB; frontmatter declares `symptoms_covered` / `dangerous_actions`, validated by `skill/demo-product-db-diagnostics/scripts/lint_db_skills.py`).
- **Capability → Skill mapping**: BKN Actions declare `implements: skill:xxx`; `RelationTraverser.get_skill_for_action()` resolves it.

### Key constraints

- **Handler signature must include `**kwargs`**. Hermes injects internal params like `task_id`; missing `**kwargs` breaks all Tools.
- **`search_qdrant_handler` must return `json.dumps(...)`**, not a dict. It bypasses `_wrap()` to avoid supplement loops.
- **All outgoing data flows through `_wrap()`** for the first 10 Tools. `_wrap()` runs `assess_confidence()`, logs gaps, triggers Qdrant fallback, and compresses output.
- **Process objects self-declare via the `# Process:` heading**. `bkn/objects/*.bkn` marks process objects (`constants.PROCESS_IDS`) with `# Process: <name> (<cn>)`; other object families use their own heading (`# Object:` / `# Product:` / `# Dimensions:` / `# Scenario:` / `# Topology:`). `lint_bkn.py::_check_process_registry` reads that heading to tell process from non-process objects: a `PROCESS_IDS` member missing it is an **error**; a `# Process:` object absent from `PROCESS_IDS` is an info. This replaced the hardcoded non-process name list (the 丙-8 fix, `C-20261013-11`).
- **Lazy initialization**: `_resolver`, `_traverser`, `_loader`, Qdrant client, embedding model, and BM25 index are initialized on first use.
- **Qdrant dimension must match the embedding model**. Default model is `BAAI/bge-large-zh-v1.5` (1024 dims). Default collection name is `demo-product_collection`.
- **BKN updates require a service-process restart to take effect on the serving instance**. `python3 scripts/reload.py` only rebuilds globals **in the process that runs it** (`reload.py:108-110`); the serving process's module-level handles (`tools.py:31-33`, created once by `_init()` at `tools.py:101-105`, with no invalidation path) keep the old objects. See `../skill/bkn-release/references/release-flow.md` §3.2.
- **Plugin code changes require Hermes restart**.

### When in doubt

- For deployment, installation, and verification commands, see `../doc/build/demo-product-bkn/40-build.md`.
- For data flow, design patterns, and the 13 Tools overview, see `../doc/build/demo-product-bkn/01-architecture.md`.
- For per-file responsibilities, see `../doc/build/demo-product-bkn/30-modules.md`.
- For handler signatures, fallback modes, config precedence, and dimension rules, see `../doc/build/demo-product-bkn/10-design_constraints.md`.
- For config sections and environment variable overrides, see `../doc/build/demo-product-bkn/41-config_reference.md`.
- For detailed Tool descriptions and output strategies, see `../doc/build/demo-product-bkn/31-tools.md`.
- Before committing, run through `../doc/build/demo-product-bkn/42-review_checklist.md`.

## 迁移后边界速查

- `skill:demo-product-product-deploy`（原 `demo-product-env-validator`，2026-09-18 并入）：承载 `env_matrix.bkn` 迁出的端口矩阵、系统参数默认值、防火墙检查命令。
- `skill:demo-product-product-deploy`（原 `demo-product-topology-visualizer`，2026-09-18 并入）：承载 `topology.bkn` 迁出的具体端口、路径与进程矩阵渲染。
- `skill:demo-product-db-diagnostics`：维护 dump 工具别名、症状/错误码 → action 路由、诊断命令模板。
- 具体命令/参数/默认值不得回退到 BKN；BKN 只保留语义与 Skill 指针。

`plugin/tools.py` 的 `_filter_command_fields` 在 `_wrap()` 中做兜底过滤：键级黑名单 + 值级 SQL/路径/端口/`--force`/可执行命令扫描，命中即脱敏并在 `gaps` 记录。

## Collaboration Rules

When working with this codebase:

1. **Plan before code.** For non-trivial changes, enter plan mode and get approval before writing code. If the implementation becomes complex, stop and return to plan mode.
2. **Understand before changing.** Study existing implementations first; follow established patterns and reuse existing functions.
3. **Fix root causes.** Don't apply surface patches. Identify the underlying issue and verify the fix with a reproduction or build.
4. **Rewrite elegantly when needed.** If the current approach is wrong, throw it away and produce a clean solution.
5. **Quiz me before big moves.** Before a PR or significant change, ask clarifying questions to confirm the implications are understood.
6. **Review plans for risks.** Audit plans for hidden edge cases, missing tests, and operational concerns.
7. **Prove no regressions.** Compare against `main` or baseline behavior when existing functionality could be affected.
8. **Impact analysis.** Before deleting a function or changing an interface, identify all callers and failure points.
9. **Use subagents.** For complex multi-part tasks, spawn multiple subagents to work in parallel.
10. **Use diagrams.** Draw architecture diagrams when they help clarify the codebase or a change.
11. **Keep progress notes.** For complex tasks, create a note directory and update it after each significant step.
12. **Review uncommitted changes.** Before commit or PR, review diffs and flag risky or unintended changes.
13. **Interview before new features.** For new features, interview the user first to understand behavior, interactions, and edge cases.
14. **Learn from mistakes.** When corrected or a bug is found, update this file or `../doc/build/common/collaboration_patterns.md` with the lesson.
15. **Just fix it.** When given a complete error and context, fix the root cause directly.
16. **只负责当前项目（2026-10-09 用户裁定，最高优先级边界）。** 本仓库（demo-product-bkn）是唯一职责范围。其它项目——包括与本项目**共享同一份 BKN 数据、`logs/` 目录或 `constants.py` 的其它实现**——不读、不改、不追根因、不做迁移对齐。遇到跨项目数据混入（如 `logs/` 下出现非本插件写入的条目）时，**只在本项目侧做过滤与标注**：分诊/统计前按格式与字段排除外来条目，并在本文件或相关文档记一条数据卫生说明即可，**不越界处理对方**。依据：多实现并存是迁移期的常态，跨项目治理会引入本项目无法验证的改动，且与本项目"每批独立提交、可 git revert"的纪律冲突。

17. **文档引用纪律（R-1）**：写文档**不写跨文档 markdown 链接**（归档 / 改名 / 删除即死链），引用一律用纯文本「编号 ＋ 名称 / 文件名」。全文与理由见根目录 `AGENT.md`，此处只留指针（单一事实源 D5）。

Full list: `../doc/build/common/collaboration_patterns.md`.

18. **元数据键清单单一源（D5，2026-10-13）。** 检索侧透传的模式库字段**只在 `plugin/bm25.py` 定义一次**（`PATTERN_META_KEYS`；`_DOC_META_KEYS` 由它拼接）。**禁止在 `tools.py` ／ `supplement.py` 等处再抄一份键清单。**定价：2026-10-13 前该清单有 **6 处**（1 规范 ＋ 5 副本），加 `dimension` 时只改了规范表 ⇒ `supplement.py` 的 3 条与 `tools.py` 的 1 条检索路径**即使 payload 里有该字段也传不回**（在役缺陷）。**新增字段须同时改**：`PATTERN_META_KEYS` ＋ `skill/demo-product-log-pattern-modeler/SKILL.md` 的字段表与骨架。
## 经验（v3.9，2026-09-22）

**1. 不要在脑子里重跑代码——真的跑它。**
排查 `ContextLoader` 截断时，我按 `_fmt_scalar` 的规则手工建模「哪些字符串会被截到 80」，
算出「67 条长串、55 条被截、损失 1,186 字符」。实际给 `_fmt_scalar` 打桩跑一遍后发现：对象数组走
`_fmt_object_array()`，用的是 `str()`，**从不截断**。真实受损是 **4 条、165 字符**——条数错
13.75 倍（55 → 4）、字符数错约 7.2 倍（1,186 → 165），而且错在结论的**形状**上
（「一片都被截」vs「就 4 条」）。凡是「这个函数会怎么处理我的数据」的问题，答案只能来自
调用它，不能来自读它。
（*本条数字于 v3.10 复核时修正：初稿写的是「3 条、138 字符 / 错 23 倍」，漏统计了 `note`
107→80 这一条。**测量本身也要复核。***）

**2. 白名单按 key 名匹配 = 对嵌套结构失效，而且静默失效。**
`_FULL_CONTENT_KEYS` 原先只在当前层比对 key 名。`_skill_enforcement.reason` 承载「禁止在
required skill 未加载前输出方案」这条指令，但 `reason` 不在白名单里，于是被无声截到 80 字符——
不报错、不记日志、不产生 gap。修法是让判定沿祖先链走（`_is_protected(key, ancestors)`）。
**判断一个白名单是否够用时，必须问「有没有内容是在白名单字段的『里面』」。**

**3. 豁免路径上的修复是「潜在」的，别当成已修复。**
三个豁免 `_wrap()` 的 handler 直接 `json.dumps`，**从不经过 ToonFormatter**。所以 v3.9 的
路径感知白名单对它们当前输出**逐字节零影响**——它修的是「哪天被接上 toon 策略就会立刻坏」。
报告一个修复时必须同时报告它在哪条路径上生效；「已修复」和「已生效」是两件事。

## 经验（v3.10，2026-09-22）

**1. 删字段前先查谁在读它。**
`diagnose_error` / `get_prerequisites` 输出里有一个与命名字段**逐字节相同**的 `raw`，
删掉它看起来是零风险的纯体积优化（不丢信息，字段本身冗余）。但
`supplement._extract_skill_from_result()` 的取文兜底链正是 `raw → diagnosis`，而
`fallback_to_qdrant()` 明确把 `get_prerequisites` 路由进这个函数——**即有人正在读我们要删的东西**。
实测 32 例（8 operation × 4 db_type）结果 0 例变化，因为全部命中了函数第一条分支（`kv` 里含
"Skill" 的键）。**改前是「碰巧安全」，不是「可证安全」**：哪天某个 operation 的 skill 只写在正文里，
就会静默失效。既然是我删的 `raw`，就该顺手把兜底链补全，让「行为不变」可证。
→ 删任何字段前，先 grep 谁在读它；「实测没变化」要能说清**为什么**没变化。

**2. 同名不同型：批量改动必须扫「字段名」的所有出现处，不只扫目标 Tool。**
`prerequisites` 在本仓库不是到处都为字符串——`design_solution` 的 `prerequisites` 是一个
operation **列表**。给 `_extract_skill_from_result` 加兜底链时，第一版写成
`a or b or result.get("prerequisites","")`，非空 list 为真值，直接被喂给 `re.search()` 抛
`TypeError`，打红 3 个既有用例（`test_design_solution::test_auto_hint_matches_migration` 等）。
修法是逐项 `isinstance(_value, str)`。
→ 我当时的 32 例验证集**只覆盖了 `get_prerequisites`**，所以完全没碰到这个坑。**验证集的宽度
决定了改动的安全边界，而不只是覆盖率的数字。**

**3. 「白名单够不够」有两个方向的问题，别只问一个。**
v3.9 的经验是「有没有内容是在白名单字段的**里面**」（→ 路径感知）。
v3.10 补上另一半：**「还有没有承载正文的字段名不在名单里」**。
同一段文本叫 `raw` 被完整保留、叫 `prerequisites` 就被截到 80——保护的是 **key 名，不是内容**。
本轮全量扫 schema enum 的 7 个 operation，**全部**被真实截断：正文 234~724 字符 → 80，
切在列表中间，每次丢 154~644 字符（含末尾那行 `负责 Skill` 指针）。两条路径都中招：
格式化路径截到 80，预算路径（`SEARCH_OUTPUT_MAX_CHARS > 0`）由 `_enforce_budget` 第 2 轮
**整个 key 删掉**。
（**现状注 · 2026-09-24**：上段数字是 v3.10 当时的。批 2-1 后 enum 扩为 8 个 operation、
正文改由 `constrained_by` 边派生，实测正文 **234~509 字符**；**截断形状不变**——把
`prerequisites` 移出白名单复测，8/8 丢失尾部 `负责 Skill` 指针、总输出少 **2,314 字符**。）
→ 顺带记一条**副作用（知情）**：第 2 轮按 key 排序逐个删，`prerequisites` 入白名单后，
同样预算下被删的会换成别的 key（`confidence` / `operation`）。这是「受保护内容最后才动」的
既定语义，但**淘汰顺序确实变了**。

**4. 修剪补白名单和删冗余字段是有顺序依赖的，必须一起做。**
`raw` 与 `prerequisites` 逐字节相同 ⇒ 删 `raw` 前，`prerequisites` **必须**先入白名单。
否则这次改动会把一个「显示不全」（Agent 仍能从 `raw` 拿到全文）**升级成真正的数据丢失**。
→ 删掉某字段的备份角色之前，先确认主字段已被完整性机制覆盖。

**5. 跑了 ≠ 跑对了：测试参数必须来自 schema，不能凭印象。**
本轮最丢人的一处：第一版实测脚本把 `get_prerequisites` 写成
`HANDLERS["get_prerequisites"]({"scenario": s})`——**`scenario` 根本不是它的入参**
（schema 只有 `operation` / `db_type`，后者已于批 2-1 随派生实现废弃）。于是「7 个场景」实际是同一个 `operation=""` 调用，
返回的是 `prerequisites.bkn` 的**文档头**（138 字符），不是任何操作的前置条件。
据此写出的「7/7 场景、长度恒为 138」全部是假的，还被同步进了代码注释和文档。
换成 schema enum 的真实 operation 重测后，结论**更大**而非更小：7 个 operation 全部被截，
234~724 字符 → 80。（**现状注 · 2026-09-24**：批 2-1 后 enum 为 8 个、正文由 `constrained_by`
边派生，实测 234~509 字符；上段的 7 / 724 / 644 是 v3.10 当时的历史数字，保留备查。）

这是**同一类错误的第二次**：v3.9 是「用脑子代替运行」，这次是「跑了但传错参数」。
两次都栽在同一个地方——**没有把「被测系统的真实接口」当成前提去核对**。
→ 跑测量脚本前，先对着 schema/handler 签名核一遍每个入参名是否真实存在；
→ 看到「N 个场景结果完全一致」这种**过于整齐**的结果，先怀疑参数没生效，而不是先高兴。
