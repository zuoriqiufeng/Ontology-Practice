---
name: bkn-updater
---
# 更新工作流（模块 1/3）

> 工作流程 Steps 1-8 + 更新类型详解（新增 Skill/操作/值委托型接线）。

---

## 工作流程

```
用户提供更新描述或文档
  → Step 1: 确定 BKN_ROOT（询问 / 从上下文推断）
  → Step 2: 探索 BKN 与 Skill 结构
  → Step 3: 识别更新类型（决策树）
  → Step 4: 提取关键信息 + 查重
  → Step 5: 信息完整性检查 → 不足则提问
  → Step 6: 安全写入（备份 → diff → 确认 → 追加）
  → Step 7: 格式验证
  → Step 8: 重启生效
```

---


---

## Step 1: 确定 BKN_ROOT

默认路径：`<repo>/demo-product-bkn/bkn/`

如用户未指定且上下文不明确，询问：
> 请确认 BKN 根目录路径（默认 `<repo>/demo-product-bkn/bkn/`）？

---


---

## Step 2: 探索 BKN 与 Skill 结构

```
search_files(pattern="*.bkn", path={BKN_ROOT}, target="files")
search_files(pattern="actions.yaml", path={BKN_ROOT}/../skill, target="files")
```

识别 `actions/` `risks/` `objects/` `relations/`（6 个 .bkn：topology / process_topology / scenario / action_routing / references / mechanism_causality + `RELATION_TYPES.md` 字典）以及 `skill/<name>/actions.yaml`。
诊断相关更新识别：`objects/`（7 个进程对象、`dimensions.bkn` 的 8 个维度）+ `relations/process_topology.bkn` 的 `suspected_in`/`has_class` 边 + `plugin/constants.py` 的别名 + `plugin/error_semantics.yaml` 的码含义规则。

---


---

## Step 3~5: 识别类型 → 提取信息 → 完整性检查

按决策树确定类型和目标文件。从用户描述/文档中提取关键字段。

**信息不足时的提问策略**：
- 每次只问 1-2 个最关键缺失项
- 模糊描述时先问「这属于哪种类型？」
- 不要一次性把所有问题抛给用户

| 缺失项 | 提问 |
|--------|------|
| capability | "这个操作的英文标识是什么？" |
| 所属 Skill | "应该由哪个 Skill 执行？" |
| 参数 | "需要哪些参数？" |
| 约束条件 | "有什么操作限制？" |
| 错误码 | "错误码是多少？" |
| 修复步骤 | "怎么修复？" |

---


---

## Step 6: 安全写入

### 6.1 查重

```bash
search_files(pattern="{capability}", path={BKN_ROOT}, target="content")
search_files(pattern="{capability}", path={BKN_ROOT}/../skill, target="content")
```

已存在 → 告知用户，询问覆盖还是追加。**禁止自动覆盖已有内容。**

### 6.2 备份

```bash
cp {target_file} {target_file}.bak.{YYYYMMDD}
```

### 6.3 Diff 预览 + 确认

读取目标文件末尾 50 行，生成追加内容预览，向用户展示：

> 将在 `{file}` 末尾追加以下内容，是否确认？

**禁止自动删除已有内容。覆盖/修改已有条目必须用户明确确认。**

### 6.4 写入

追加模式，使用 `write_file` 或 `patch` 追加到对应文件。

---


---

## 更新类型详解

### 新增 Skill

新增 Skill 需要同时创建/更新以下文件：

1. `skill/<skill-name>/SKILL.md`：触发条件、用途、命令示例、安全警告
2. `skill/<skill-name>/actions.yaml`：具体命令模板、参数、安全级别（如为操作类 Skill）
3. `skill/<skill-name>/README.md`：安装、运行环境、配置、action 索引
4. `bkn/actions/<skill-name>.bkn`：BKN action 定义（capability/object/implements/params/...）
5. `bkn/relations/`：references.bkn 加 `object → has_action → capability`；action_routing.bkn 加 `action:<capability> → implements_skill → skill:<skill-name>`
6. 若与诊断/错误码相关：涉及新错误码/症状 → `bkn/relations/process_topology.bkn` 补 `suspected_in` 边 + `plugin/constants.py` 别名常量加行（26 号：BKN 不建清单）；新增/改名 Skill 须在 `plugin/skill_manifest.yaml` 登记（`id`/`entry`/`capability`/`load_criterion`，lint 双向校验）

### 新增操作

新增操作需要同时更新：

1. `bkn/actions/<object>_*.bkn`：追加 Action 条目
2. `bkn/relations/`：references.bkn 追加 object → has_action → capability；action_routing.bkn 追加 `action:<capability> → implements_skill → skill:<skill-name>`
3. `skill/<skill-name>/actions.yaml`：追加 capability 命令模板
4. `skill/<skill-name>/SKILL.md`：可选补充人类可读说明

### 新增操作 Step1–6 全链（add-skill.md 完整路径）

> 场景：业务新增一个操作（如「重置同步规则」），要让 Agent 能执行它。
> 依据：demo-product-iadebug 接入流程（2026-07）实际踩过的完整路径。

**Step 1 在 bkn/actions/ 加 Action 段**（例：rule_lifecycle.bkn 末尾追加）：

	## Action: 重置同步规则

	- capability: reset_sync_rule
	- object: syncrule
	- implements: skill:demo-product-rule-manager
	- params: 具体字段由 Skill 定义
	- prerequisites: [rule must be STOPPED]
	- constraints: [cannot reset RUNNING rule, must confirm]
	- risks: [data loss if done during sync]
	- notes: 重置后规则回到初始状态, 需重新全量同步
	- aliases: reset_rule

要点：
- capability 是**唯一注册键**（`resolver.py` 的 `_register_actions` 自动扫描所有 `actions/*.bkn`，**无需改 Plugin 代码**）；
- aliases 用于桥接 capability 与 Skill `actions.yaml` 键名差异（例：BKN `iadebug_resumeforce` ↔ Skill 键 `resumeforce_track`）；lookup_operation 按 **capability > alias > name** 优先级匹配；
- constraints / risks / prerequisites 必写全（constraints、risks 的内联 KV 会被 `resolve_operation` 直接返回）；
- 若工具有使用边界（如面向用户的 Demo Console 页面操作 vs 运维 / 研发底层工具），在文件头部写「使用边界:」说明。

**Step 2 在 bkn/relations/ 加边**（旧 `bkn/relations.bkn` 箭头格式已废弃；改 KWeaver 段落格式，每段「## Relation:」内的「- **关系类型**: <snake_case>」才是机器可读 key）：

- `bkn/relations/references.bkn` 的 has_action 段「映射规则」区追加：`syncrule` → `reset_sync_rule`
- `bkn/relations/action_routing.bkn` 的 implements_skill 段追加：`action:reset_sync_rule` → `skill:demo-product-rule-manager`
- 危险操作另需在 constrained_by / risks_of 段追加（**不刷新段头计数**——HIGH / MEDIUM 条数等计数按 P-B 原则已移除）

**Step 3 危险操作补 constraints.bkn 条目**：`bkn/risks/constraints.bkn` 的 L2 HIGH / MEDIUM 表追加约束行（关联列沿用 `SyncRule.xxx` 词表）；若引入新 Skill，在「## 排查入口」追加一行 Skill 指针。

**Step 4 登记 Skill 语义 ID**（**条件必做**）：`plugin/skill_manifest.yaml` 写 `id` / `entry` / `capability` / `load_criterion`；lint 双向校验（悬空 ＝ error / 孤儿 ＝ warning）。

- **反向纪律**：生命周期 / 工具链类 Skill（不被任何 `.bkn` 引用）**不要登记**——孤儿 warning 的立法目的正是**防清单膨胀**（11 号规则 16 第 4 条）。
- 新 actions 文件：动作本体分组加一行导航。
- 新操作有口语化表达：写进 Action 段内的 `- aliases:` **同址字段**（不建中央同义词表）。

**Step 5 在对应 Skill 加实现**：`skill/<name>/actions.yaml` 追加 capability（description / safe / command_type / command / requires / output_interpretation / notes）；`SKILL.md` 追加 capability 说明即可——**命令本身只维护在 actions.yaml，BKN 不得回流入命令模板**。

**Step 6 热重载 + 验证**：

	python3 plugin/scripts/reload.py                      # 只作用于执行它的进程；常驻服务需重启（见 release-flow.md §3.2）
	python3 -m pytest plugin/tests/test_relations.py -v   # 图边改动必须跑

端到端断言（Python）：

	BKNResolver().lookup_operation("reset_rule")                   # alias 命中
	RelationTraverser().get_skills_for_action("reset_sync_rule")   # → skill:demo-product-rule-manager

完整「改了什么」表与常见新增操作清单见本文件 §1 与 `references/formats.md`（原 `doc/update/add-skill.md`，2026-10-15 随该目录清理）。

### 关系条目格式

`relations/` 各域文件中统一使用（has_action → references.bkn；implements_skill → action_routing.bkn）：

```bkn
object:syncrule → has_action → {capability}
action:{capability} → implements_skill → skill:{skill-name}
```

关系类型名用 `implements_skill`（29 种关系类型之一），不是旧的 `implements`。

### 值委托型接线（新增运维知识 / 纯值 Skill）

适用：新 Skill 不暴露 action capability，只提供**值与知识**（端口矩阵、检查命令、部署步骤、环境分层思路、渲染能力）——典型如 `demo-product-product-deploy` / `db-deploy` / `demo-product-addons-deploy`。与 action 型接线**二选一**：Skill 动作确属 action capability 才走上方 action 路径，纯值 Skill 走本流程（对应 bkn 扩展指南第 6 步）。

流程 5 步：

1. **锚点指针**：在语义最近的锚点文件正文写"…由 `skill:<name>` 提供（原 xxx，YYYY-MM-DD 接线）" —— 只写思路/骨架/指针，**禁命令/参数值/路径**（BKN 边界硬约束）
2. **注册登记**：需要用户词路由时，把词写进该 Skill 自己 `SKILL.md` frontmatter 的 `triggers:`；Skill 语义 ID 登记进 `plugin/skill_manifest.yaml`（23 号：本体层不再有 `network.bkn` 索引区）
3. **action 判别**：Skill 若同时暴露 action capability，这些 action 照常走 action 型登记 6 项；纯值 Skill 跳过
4. **接线验证**：`grep -r "skill:<name>" {BKN_ROOT}` ≥1 命中（**0 = 未接线**，回到第 1 步）
5. **质量闸门**：`python3 {BKN_ROOT}/../plugin/scripts/lint_bkn.py --error-only` errors=0（再跑全量逐条判定 warning）→ **重启服务进程**生效（`reload.py` 只重建执行它的短命进程的全局）

完整示例：`skill:demo-product-product-deploy` 的值委托接线——`objects/database.bkn` 的源端配置指针、
`objects/host.bkn` 的节点审计委托（`skill:demo-product-node-inspection`），以及 23 号新增的
`references/compatibility.md`（版本表/对象兼容/按库约束）与 `skill:demo-product-db-manager/references/charset.md`（字符集）。

> 设计依据：`<repo>/bkn/bkn-ops-semantics-extension-design.md` §4 U2；
> 该流程正是为"三个部署 skill 落地时只接线 1 个"的缺口补的。

---

### 改 Skill 实现（不动 BKN）

> 场景：脚本路径变了 / Python 环境换了 / SDK 版本升级了 / 多了个坑。
> **不影响 BKN**，只改 Skill 文本——依据件 `原 doc/update/change-skill.md（2026-10-15 清理）`。

四个常见场景，各自改哪里：

| 场景 | 改什么 | 例子 |
|---|---|---|
| 脚本路径变更 | SKILL.md / actions.yaml 里的 `script:` | `rule_create.py` → `rule_create_v2.py` |
| 环境变量变更 | `env:` 段 | 控制台迁移 ⇒ `DEMO_CONSOLE_API_HOST` 改址；目录重构 ⇒ `PYTHONPATH` |
| SDK 版本升级 | SKILL.md 的「版本差异」小节加行 | 9.2.0 参数由 `--rule-name` 改 `--name` |
| 新增已知问题 | SKILL.md 的「注意事项」小节加行 | 9.2.0 补丁已内置 / 403 已修复 |

**不需要做的事**：不改 `bkn/actions/`、不改 `bkn/relations/`、不重载 Plugin。

> ⚠️ **「不需要重启」有前提**——只适用**纯 Skill 文本**改动。
> 若同批改了 BKN 数据，热重载的作用域见 `skill:bkn-release/references/release-flow.md` §3.2：
> `reload.py` 只重建**执行它的那个进程**，**常驻服务进程需重启**。

---


---

## Step 7: 格式验证

写入后逐项检查：

1. 文件仍为 UTF-8 可正常读取
2. BKN Action 条目含 `capability` `object` `implements` 三个必需字段
3. Skill `actions.yaml` 中每个 action 含 `command` 和 `safe` 字段
4. 风险条目含 `错误码` `原因` `修复` 三个必需字段
5. 关系条目格式为 `A → rel → B`
6. 新增内容不破坏已有条目的结构边界
7. 跑 `python3 plugin/scripts/lint_bkn.py --error-only`，必须 errors=0

**验证失败 → 从 `.bak` 恢复并告知用户。**

---


---

## Step 8: 重启生效

```bash
# 重启常驻服务进程（reload.py 只重建执行它的短命进程的全局，常驻服务不生效）
```

生效后验证：`search_files(pattern="{capability}")` 确认新条目可被检索。

---

## P-A 判据：BKN 结构变了，Plugin 必须同批改

> 依据：`skill/bkn/references/ontology-basics.md` 的「工具跟随（P-A）」；
> 口径来源 `doc/optimize/22-bkn-lifecycle-gate.md` §3 批 2-2（修正原文「永远不需要改 Plugin 代码」的绝对表述——它与 P-A 及上方「改了什么」表自相矛盾）。

**工具是 BKN 的投影，不是 BKN 的适配器。**

| 你改了什么 | 是否需要改 Plugin | 具体改哪 |
|---|---|---|
| 只加 / 改**实例数据**（登记表加行、加别名、加边） | ❌ 不需要 | 自动发现（resolver 扫描 `actions/*.bkn`） |
| 加新 Action 段（capability 已在既有白名单内） | ❌ 不需要 | — |
| **结构类**：新关系语义、新段类型、新命名空间前缀 | ✅ **必须同批** | `plugin/relations.py` 的 `RELATION_TYPES`＋`plugin/constants.py` 的 `RELATION_TARGET_NAMESPACES` / `VALID_SECTION_TYPES`（及相关注册集）＋ `plugin/schemas.py`（如 `resolve_relation.relation_type` 的 enum）＋ `bkn/SCHEMA.md` §0.1（段类型枚举，4 种）与 `bkn/relations/RELATION_TYPES.md` 同步计数与表格 |

**漏登记的后果：边被静默丢弃。**（`lint_bkn.py` 的 `_check_namespace_registry_consistency` 已把「该登记而没登记」升级为 error。）

**收尾命令（无论哪类，改完都跑）**：

	bash scripts/gate.sh

---