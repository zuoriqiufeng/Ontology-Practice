---
name: bkn-updater
---
# 登记完整性 checklist（模块 3/3）

> 应拒绝场景 / 登记完整性 checklist / 接线判据 / 注意事项。

---

## 应拒绝或升级人工确认的场景

1. 要求**删除**已有条目或整个 .bkn 文件
2. 更新内容与现有 BKN **明显矛盾**（同一 capability 对应不同 skill）
3. 涉及**版本回退**或大量重写（>50% 文件内容）
4. 文档格式混乱，无法提取结构化信息
5. 要求修改 `relations/` 中多个已有关系
6. 要求**为每个错误码/症状/表现新建独立 `.bkn` 段 / 新建 `index`·`matrix` 段 / 新建维度**（如 `## 错误码 xxx` 段、`## 症状 yyy` 段）——26 号方案后实例走**边 + 常量**（`process_topology.bkn` 补 `suspected_in` 边 + `constants` 别名，BKN 不建清单），登记是默认动作**不需升级确认**；只有「建独立段/建废止类型段/扩维度」才是拒绝项，须与用户确认改为登记制或落 `dimension:unknown`。

> 以上情况应告知用户风险，建议人工审核后再执行。

---


---

## 登记完整性 checklist（2026-08-15 实测）

新增 Action 必须同步以下全部位置，缺一不可（23 号方案：导航/索引已下延，登记点收敛为 10 处）：

1. `bkn/actions/<file>.bkn`：Action 段（capability/object/access_type/implements/params/...）——**26 号零元信息**：不写 `> 来源:`/演进注记，迭代记录写 `CHANGELOG.md`
2. `bkn/relations/action_routing.bkn`：`implements_skill` 段加 `action:<capability> → skill:<skill-name>` 边（关系类型是 `implements_skill`，非旧 `implements`）
3. `bkn/relations/references.bkn`：`has_action` 段加 `object → has_action → <capability>` 边
4. `plugin/skill_manifest.yaml`：新增/改名的负责 Skill 登记（`id`/`entry`/`capability`/`load_criterion`）——lint 双向校验（悬空 = error / 孤儿 = warning）
5. `plugin/schemas.py` + 对应 Tool：若 capability 进入 Tool 枚举/分支，**同批**调整（P-A：Tool 是投影）
6. 前置条件（批 2-1 派生模型，**不再往 prerequisites.bkn 加逐 action 段**）：**约束类** → `bkn/risks/constraints.bkn` 登记表加约束ID 行（**4 列，无关联列；只登记动作级**）+ `bkn/relations/action_routing.bkn` 补 constrained_by 边（25 号：不补边 = lint 警告 + risk_guard 不装配；全局/对象级约束进「全局约束」KV 段）；**非约束类业务前置** → 写进负责 Skill 的 `SKILL.md`
7. 危险操作（dangerous: true）额外：`bkn/risks/constraints.bkn` 加约束ID + `action_routing.bkn` 加 constrained_by / risks_of 边（**不刷新段计数**——HIGH/MEDIUM 条数等计数按 P-B 原则已移除）
8. **诊断域登记项（23 号方案，涉及诊断内容时必须同步）**：
   - 新增错误码/症状 → `bkn/relations/process_topology.bkn` 补 `suspected_in`（或 `has_class`）边 + `plugin/constants.py` 别名常量（26 号：BKN 不建清单）；完整属性查库（`store:log_patterns_collection#错误码`）；
   - 新增库 → `plugin/constants.py::KNOWN_DBS`/`DB_ALIASES` 登记 + `objects/database.bkn` 加对象段 + `plugin/config.yaml` 核对连接参数；逐库检查点下延 `skill:demo-product-db-diagnostics/references/db-checkpoints.md`（**不进 BKN**）；
   - 扩维度（新增 `dimension:*`）→ **默认不做**，`dimension:unknown` + gap_log 反复证明才评审（`_check_namespace_registry_consistency` 有牙齿）
9. 完成后跑 `python3 plugin/scripts/lint_bkn.py --error-only` 验 errors=0（再跑全量逐条判定 warning）；改 `.bkn` 后**重启服务进程**生效（`reload.py` 只重建执行它的短命进程的全局，常驻服务不生效）
10. **BKN 接线检查**：新 Skill 落地后 `grep -r "skill:<name>" {BKN_ROOT}` ≥1 命中——0 命中 = 未接线，按「值委托型接线」流程补（纯值 Skill）或补 action 型登记；确有意不接线时在 Skill 内显式记录"有意不接"及理由

> 当前 relations 已按域拆为 6 个 .bkn（topology / process_topology / scenario / action_routing / references / mechanism_causality）+ `RELATION_TYPES.md` 字典，**无单一 relations.bkn**；action→skill 用 `implements_skill`（29 种关系类型之一），不是旧 `implements`。2026-09-20 已将上文各步骤/示例/注意事项的旧 `relations.bkn` + `implements` 口径**全文统一**为 relations/ 各域文件 + `implements_skill`（本 checklist 仍为权威）。

### 接线判据（Skill 是否进 BKN 值委托/动作路由）

> 2026-09-24：原 `skill:bkn-plugin/references/related-skills-index.md`（Skill 全集路由索引）已删除
> ——「清单随 Skill 数增长」属索引，改由 `plugin/skill_manifest.yaml`（有 BKN 引用的 Skill）+ 各 Skill
> 自身 frontmatter `triggers:`（无 BKN 引用者）承载；**判据**保留如下。

**A 类（应接线）**：Skill 面向**产品运维/诊断**，能被现场问题直接触发 → 在语义最近的锚点文件写指针
（或建 action capability），并在 `plugin/skill_manifest.yaml` 登记语义 ID。典型：部署安装、按库运维、
链路诊断、容量与系统配置、控制台与许可。

**B 类（有意不接线，五组理由）**：

| 组 | 理由 | 例 |
|----|------|----|
| BKN 自身维护 | 维护 BKN/知识库自身，非产品运维路由目标 | bkn-plugin、bkn-updater、log-pattern-modeler |
| Qdrant 巡检 | BKN 内部数据质量审计，非用户运维场景 | 诊断数据审计类 |
| 报告回传 | 报告 API 回传链路，与诊断路由无关 | report_sender |
| Agent 平台自身 | Agent 会话/平台监控，非产品运维 | i2agent-* 监控类 |
| 测试造数 | 测试环境造数，非生产运维 | obora-diff-testing、SQL 造数类 |

**判定顺序**：先问「现场问题会不会自然触发它」；会 → A 类接线（≥1 处 `skill:` 指针 + manifest 登记）；
不会但确属产品能力 → B 类并在 Skill 内显式记录「有意不接」及理由。


---

## 注意事项

- ⚠️ **新增知识三问（23 号方案）**：动手前先问「能否抽象为类/属性/关系/实例」「是否随实例或客户/版本增长」「不能抽象则下延哪一层」。禁止 `index`/`matrix` 段与定义段内说明性表格；实例登记是默认动作（见「写之前先判」节）。
- ⚠️ **并发更新风险**：多会话同时改同一 .bkn 文件可能覆盖彼此内容。每次只追加单个条目，避免长时间持有文件。
- BKN 文件 UTF-8 编码
- 新增条目追加到文件末尾，不覆盖
- action→skill 关系写在 `relations/action_routing.bkn`，关系类型用 `implements_skill`（29 种关系类型之一），不是旧 `implements`
- 操作类更新必须同步更新对应 Skill 的 `actions.yaml`

---
