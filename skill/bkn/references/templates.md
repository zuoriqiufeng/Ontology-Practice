---
name: bkn
description: BKN (Business Knowledge Network) 业务+运维双问题域知识网络生成器 — 基于 KWeaver 官方 BKN 规范（Object/Relation/Action/Risk），为数据库同步等业务场景自动生成 Markdown 格式的业务本体定义，作为 AI Agent 的 Source of Truth。将自然语言需求编排为 Agent 可渐进式披露的结构化业务知识网络。生成前经 Step 0 与用户确认问题域（仅业务 / 仅运维 / 业务+运维，不默认绑定）。
version: 2.4.0
author: Info2Soft AI Team
dependencies: []
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [BKN, KWeaver, Agent Context, Ontology, Database Sync, Business Knowledge Network, Context Engineering]
---

# BKN 生成模板（模块 3/5）

> 7 个业务模板 + 补充模式（D/E/G/H/I/Ops）。**模式 Net 已于 23 号废止**（`network.bkn` 已删除，见文末）。

---

## 数据库同步场景 — BKN 生成模板

### 模板 1: database.bkn — 数据库实例对象

> 模板用 KV 对，不用属性表；具体 host/port/version 用 `<占位>`，真实值由对应 Skill 提供。

```markdown
# Object: Database

## Object: <源数据库对象名>

- **标识**: <source_db_id>
- **描述**: <一句话描述，不含具体 IP/实例名>
- type: <ORACLE | MYSQL | SQLSERVER | OCEANBASE | ...>
- version: <版本，由 {db_manager_skill} 校验>
- host: <host>                      ← 占位，真实地址由 Skill/注册信息提供
- port: <port>                      ← 占位，默认端口由 {db_manager_skill} 提供
- charset: <字符集>
- is_archivelog: <Oracle 源端必须为 true>
- role: <SOURCE | TARGET>
- **数据源**: <数据库节点注册信息>
```

如需在同一份 BKN 中区分多个对象，新增 `## Object:` 节即可，不要在 KV 里写死实例 IP。

### 模板 2: sync_task.bkn — 同步任务对象

> 属性用 KV 对；状态字段只列枚举值；实例 ID 用占位，不写死业务编号。

```markdown
# Object: SyncTask

## Object: <同步任务对象名>

- **标识**: <task_id>
- **描述**: <源端 → 目标端 同步任务，一句话>
- id: <task_id>                                  ← 占位
- name: <任务名称>
- source: 源端数据库节点引用 → dbnode          ← 源/目标角色由**边类型**承载（reads_from / writes_to），**不写 role=**
- target: 目标端数据库节点引用 → dbnode
- mode: <FULL_ONLY | CDC_ONLY | FULL_THEN_CDC>
- status: <IDLE | CONFIGURING | READY | FULL_SYNC | FULL_VERIFY | CDC_RUNNING | LAG_WARNING | ERROR | AUTO_RETRY | HUMAN_OPS | PAUSED | CANCELLED>
- tables: List→TableMapping
- priority: <1-10>（默认值由产品 skill 提供）
- **数据源**: <同步规则配置>
```


---

## 状态机定义 (补充)

**状态机不写表格**——转换条件属说明性内容，下延负责 Skill；本体只在状态字段列枚举值：

```markdown
- status: <IDLE | CONFIGURING | READY | FULL_SYNC | FULL_VERIFY | CDC_RUNNING | LAG_WARNING | ERROR | AUTO_RETRY | HUMAN_OPS | PAUSED | CANCELLED>
```

> 「当前状态 → 目标状态 + 触发条件」的转换矩阵属说明性表格，**违反** `bkn/SCHEMA.md` 载荷硬规则，lint `_check_no_explanatory_tables` 会报 **error**。

### 模板 3: topology.bkn — 对象关系

> **缺 `- **关系类型**:` 的段会被解析器静默跳过、不入图**（不报错）；每段必须给 `关系类型`（29 种白名单内）+ `中文名`。

```markdown
# Relation: 数据同步拓扑

## Relation: 源端读取

- **关系类型**: reads_from
- **中文名**: 读取自
- **源对象**: SyncTask
- **目标对象**: dbnode
- **类型**: N:1 (多个任务可读取同一源库)
- **描述**: 同步任务从源端数据库读取变更数据

## Relation: 目标端写入

- **关系类型**: writes_to
- **中文名**: 写入
- **源对象**: SyncTask
- **目标对象**: dbnode
- **类型**: N:1
- **描述**: 同步任务向目标端数据库写入数据

## Relation: 表归属任务

- **关系类型**: references
- **中文名**: 引用
- **源对象**: TableMapping
- **目标对象**: SyncTask
- **类型**: N:1
- **描述**: 表映射归属于特定同步任务

## Relation: 列归属表

- **关系类型**: references
- **中文名**: 引用
- **源对象**: ColumnMapping
- **目标对象**: TableMapping
- **类型**: N:1
- **描述**: 列映射归属于特定表映射
```

### 模板 4: task_lifecycle.bkn — 任务生命周期操作

```markdown
# Action: 任务生命周期操作

## Action: 创建同步任务

- capability: create_sync_task
- object: SyncTask
- access_type: write
- binding_type: skill
- implements: skill:{sync_manager_skill}
- params: task_name(string,required) source_id(string,required) target_id(string,required)
- prerequisites: [source_registered, target_registered]
- constraints: [source NORMAL, target NORMAL, dry-run first]

## Action: 启动同步

- capability: start_sync_task
- object: SyncTask
- access_type: write
- binding_type: skill
- implements: skill:{sync_manager_skill}
- params: task_id(string,required)
- constraints: [task_ready, cannot_restart_running]

> 实例注记：`implements: skill:{sync_manager_skill}`；约束用**约束ID**表达（不写错误码与命令）。

## Action: 暂停同步

- capability: pause_sync_task
- object: SyncTask
- access_type: write
- binding_type: skill
- implements: skill:{sync_manager_skill}
- params: task_id(string,required)
- constraints: [status IN (CDC_RUNNING, LAG_WARNING)]
- notes: 暂停后状态变为 PAUSED

## Action: 恢复同步

- capability: resume_sync_task
- object: SyncTask
- access_type: write
- binding_type: skill
- implements: skill:{sync_manager_skill}
- params: task_id(string,required)
- constraints: [status == PAUSED]
- notes: 恢复后状态变为 CDC_RUNNING

## Action: 数据校验

- capability: verify_sync_task
- object: SyncTask
- access_type: read
- binding_type: skill
- implements: skill:{sync_manager_skill}
- params: task_id(string,required) checks(List[ROW_COUNT,MD5_CHECKSUM,SCHEMA],required) tables(List[String])
- constraints: [status IN (FULL_VERIFY, SCHEDULED_VERIFY)]
- notes: 返回校验报告；不指定 tables 则校验全部表
```

### 模板 5: performance.bkn — 性能风险边界

```markdown
# Risk: 性能风险

## Risk: 同步延迟超限

- **关联对象/动作**: SyncTask (CDC模式)
- **风险级别**: critical
- **触发条件**: 增量同步延迟 > <延迟阈值>
- **约束行为**: 禁止对源端执行任何 DDL 操作
- **处置策略**: 自动重试 (最多 <重试次数> 次，指数退避 <退避序列>)
- **告警规则**: 延迟 > <LOW 阈值> 发送 LOW 告警；> <CRITICAL 阈值> 发送 CRITICAL 告警并触发自动重试

## Risk: 大表全量同步性能

- **关联对象/动作**: TableMapping (rows > <大表行数阈值>)
- **风险级别**: warning
- **触发条件**: 全量同步阶段，源表行数 > <大表行数阈值>
- **约束行为**: 
  - 禁止使用默认并行度（必须 ≥ <最小并行度>）
  - 禁止在目标端保留索引
- **处置策略**: 
  - 强制启用分区拆分 + <并行度>
  - 目标端先删索引 → 批量写入 → 重建索引
- **告警规则**: 吞吐量 < <吞吐量阈值> 时发送 HIGH 告警

## Risk: 网络带宽不足

- **关联对象/动作**: SyncTask (异地链路)
- **风险级别**: info
- **触发条件**: 目标端位于异地，网络延迟 > <网络延迟阈值>
- **约束行为**: 
  - 禁止使用大包直传（batch_size 必须 ≤ <批量上限>）
  - 必须启用压缩传输
- **处置策略**: 自动启用压缩（<压缩级别>），减小批量大小
```

### 模板 6: data_safety.bkn — 数据安全与脱敏

```markdown
# Risk: 数据安全风险

## Risk: 个人敏感信息泄露

- **关联对象/动作**: ColumnMapping (含脱敏列)
- **风险级别**: critical
- **触发条件**: 目标端为风控库时，同步了身份证/手机号/卡号等敏感列
- **约束行为**: 
  - **禁止**将原始敏感数据写入风控库
  - **必须**应用脱敏规则
- **处置策略**:
  | 字段 | 脱敏方式 | 可逆 |
  |------|---------|------|
  | ID_CARD | MD5哈希 | 不可逆 |
  | PHONE | 掩码 138\*\*\*\*1234 | 不可逆 |
  | CARD_NO | AES加密(key:RISK_ENCRYPT_KEY) | 可逆 |
  | BALANCE | 四舍五入到千位 | 不可逆 |
- **告警规则**: 检测到未脱敏敏感数据 → 立即暂停任务 + CRITICAL告警

## Risk: 全量校验未通过时切换

- **关联对象/动作**: SyncTask (状态切换)
- **风险级别**: critical
- **触发条件**: FULL_VERIFY 状态中校验失败
- **约束行为**: **禁止**从 FULL_VERIFY 切换到 CDC_RUNNING
- **处置策略**: 任务切换到 FULL_FAILED，发出 CRITICAL 告警，等待人工处理
```

### 模板 7: operational.bkn — 运维操作约束

```markdown
# Risk: 运维操作风险

## Risk: 自动重试耗尽

- **关联对象/动作**: SyncTask (AUTO_RETRY)
- **风险级别**: critical
- **触发条件**: 自动重试达到上限（<重试次数>）仍未成功
- **约束行为**: **禁止**继续自动重试
- **处置策略**: 
  - 状态切换为 HUMAN_OPS
  - 发送 CRITICAL 告警："同步任务已自动重试至上限，需要人工介入"
  - 自动收集诊断日志并附在告警中

## Risk: 生产库 DDL 变更

- **关联对象/动作**: dbnode（源端生产库；角色由 `reads_from`/`writes_to` 边承载，不写 `role=`）
- **风险级别**: critical
- **触发条件**: Agent 尝试在源端生产库执行 DDL 操作
- **约束行为**: **绝对禁止**在生产源库执行任何 DDL（ALTER/DROP/TRUNCATE）
- **处置策略**: 立即拦截，回复 "生产库禁止执行DDL，请联系DBA手动操作"
```

---


---

## 补充模式模板（产品级 BKN 扩展）

除 Object/Relation/Action/Risk 四要素外，产品级 BKN 还有以下结构性模式。生成对应文件时按下列模板写。

### 模式 D：实例登记表型（原「常数矩阵型」，23 号改造）

矩阵（`matrix`）段已废止。**有限注册集 + 每行一个带命名空间 ID 的实例** = 合法的「实例登记表」；
随客户/版本/竞品增长的多维对照表 → **下延 Skill references**。

```markdown
<!-- type: entity -->
## <注册集名>注册集

> 行 = `<ns>:*`（<注册集名>，BKN 内登记于本文件）实例表｜列 = <字段1> / <字段2> / 别名（同址词表）

| <ns> ID | 名称 | 关注什么 | 别名 |
|---------|------|---------|------|
| `<ns>:<id>` | <中文名> | <一句话> | <旧称, 同义词> |
```

判据：**行的集合有限且缓慢变化**（维度 8 个、约束 ~20 条、原则 5 条）→ 登记；错误码/症状**不在登记之列**（Q27，码不进任何一层）；
**行随客户/版本增长**（逐库检查点 9×5、版本对照 28 行、竞品对比）→ 下延 Skill references。
说明性/对照性表格（「方案优势」「比对机制」「性能指标」）一律下延。

### 模式 E：诊断边 + 指引型（原「锚点登记型」，25 号改造）

**错误码/症状不进 BKN 清单**（用户裁定：实际问题清单不算本体，本体给的是指引）：

```bkn
<!-- type: relation -->
## Relation: 症状/错误码 嫌疑进程
- **关系类型**: suspected_in
- **映射规则**:
  - `error:<码>` → `process:<进程>`   # ← 规范 ID 空间由边承载（有哪些码 = 边上有什么）
  - `symptom:<id>` → `process:<进程>`
```

- **归一（值数据）**：现场口语 → 规范 ID 的别名在 `plugin/constants.py`
  （`ERROR_ALIASES` / `SYMPTOM_ALIASES`，与 `DB_ALIASES` 同层）；机械变体由代码派生。
- **指引（执行层）**：四步诊断指引（归一→定位→取证→兜底）在 `{log_analyzer_skill}`；码含义按**日志消息文本**命中 `plugin/error_semantics.yaml` 的 8 个 `dimension:*` 语义类别（查不到 → `dimension:unknown`，不猜），语义类别权威见 `bkn/objects/dimensions.bkn`——
  归一 → 定位（边）→ 取证（进程属性 + 检索源）→ 兜底（`dimension:unknown` + gap_log）。
- **完整定义**：查库（`store:log_patterns_collection#错误码`），任何时候不入 BKN。
- **lint 牙齿**：别名常量里出现边上没有的 ID → error（`_check_alias_constants`）。

跨切面（无法定位单进程）→ `has_class` 边指向 `dimension:*`。归不进任何维度 → `dimension:unknown` + gap_log。

### 模式 G：值委托指针型（原「工具索引型」，23 号改造）

任何「值/命令/参数/完整定义」都不进本体；本体只留**一行指针**：

```markdown
- **运维**: <能力范围> 由 `skill:<name>` 提供（值委托）。

> <维度>关注项明细 / 判定纪律 / 命令: `skill:<name>/references/<file>.md`。
```

下延四去向（三问之③）：值数据 → Skill references；路由/规则 → Tool 常量或 `plugin/skill_manifest.yaml`；
全量知识 → Qdrant（`store:*`）；叙述/原理 → `doc/`。
指针必须 ≥1 处可被 `grep -r "skill:<name>" bkn/` 命中（0 命中 = 未接线）。

### 模式 H：进程对象型（`objects/*.bkn（进程对象）`，20 号方案）

**运行时对象域**——进程拓扑为主干，替代「按错误分类」的分类轴。只收该产品规范定义的进程集（清单见产品 skill），**进程是常数集，不随现场增长**：

```markdown
# Process: <进程名> (<中文名>)

> 运行时对象 — <一句话定位>。
> 本文件只给「是什么、连什么、看哪个日志、查哪类工具」；具体路径/命令由 Skill 提供。

## 定义
<进程职责、源端/目标端归属、由谁拉起>

## 关键属性
- **规范名**: `process:<name>`
- **角色**: <增量/全量/装载/守护/监控/对比/代理>
- **链路阶段**: <源端-增量/源端-全量/目标端-装载/节点-守护/节点-监控/节点-对比/控制机-代理>
- **语言**: <C++/Java>（语言决定工具类别）
- **排查频度**: <高/中/低>（问题发生频度，决定先看谁）
- **日志自证性**: <自证/需关联>（单进程日志能否独立定位；需关联 = 必须与上下游综合看）
- **日志标识**: <文件名模式，版本代际映射>；具体路径由 `skill:<对应 skill>` 提供
- **启动者**: `process:<启动者 id>` 或 人工

## 工具类别（语言属性推导）
C++ → core dump/stderr/动态库；Java → JDK 工具链（jstack/jmap）

## 关联
→ 上下游进程（feeds）/ 管理进程（supervises）/ 库（consumes/produces/monitors）/ Skill
```

**新进程 → 不登记**：进程是常数集（由产品规范定义，清单见产品 skill），**产品没加进程就不要新建进程对象**；未纳入本体的旧版/窄适用进程一并见产品 skill。拓扑边加在 `relations/process_topology.bkn`（`feeds`/`supervises`/`consumes`/`produces`/`monitors`/`suspected_in`）。

### 模式 I：检查维度型（`objects/dimensions.bkn`，20 号方案）

**WHAT 轴**——检查维度是有限枚举（log_readable/permission/connectivity/resource/time_sync/consistency/state_machine/unknown），与进程对象（WHERE 轴）正交：

```markdown
<!-- type: entity -->
## dimension 检查维度注册集

> 行 = `dimension:*`（检查维度注册集，BKN 内登记于本文件）实例表｜列 = 名称 / 关注什么 / 典型触发 / 别名

| dimension ID | 名称 | 关注什么 | 典型触发 | 别名 |
|-------------|------|---------|---------|------|
| `dimension:<id>` | <中文名> | <检查什么> | <何时用> | <旧称> |
```

**边界（硬约束）**：只做**形态无关层**（资源限制/安全与编码/时间/磁盘）；**形态层（物理机/VM/云/容器）禁止入 BKN**——形态开放不可穷尽且依赖现场探测，归 `{deploy_skill}` 的 env-issues.md（值委托）。阈值与命令一律由 Skill 提供。

### 模式 Ops：运维补充型（24 号起并入 `objects/` 与 `risks/`）

- `objects/<x>.bkn`：对象级运维差异（如各 DB 源端要求），**KV 属性 + 实例登记表**；多维对照（逐库 DDL/无主键/权限）→ 下延 Skill references，本体只留一行指针。
- `risks/prerequisites.bkn`（原 `operations/actions/`）：per-Action 前置条件清单，per-DB 细节用嵌套 bullet 写在对应 Action 下：

```markdown
## Action: <操作名>

- **归属对象**: <Object>
- **描述**: <一句话>
- **需要确认的前置条件**:
  1. <条件 1>
  2. <条件 2>
- **约束**: <约束>
- **负责 Skill**: `<skill>`

# 同一 Action 内，DB 特定细节用嵌套 bullet，不开顶级 "Oracle:/MySQL:" 节：
- 源端日志配置就绪（具体参数值由 {db_manager_skill} 按数据库类型验证）:
  - Oracle: 归档/强制写日志/附加日志配置合规性由 {db_manager_skill} 验证
  - MySQL: binlog 格式与行图像配置合规性由 {db_manager_skill} 验证
```

### 模式 Net：~~路由索引型（`network.bkn`）~~ —— **23 号已废止**

`network.bkn`（路由索引 / 实体语义索引 / BKN 文件导航 / 同义词中央表）**已删除**：
- **文件导航** → 下延 `bkn/SKILL.md`（.md 规范文件，非本体段）；
- **实体清单索引**（对象/动作/风险三段清单）→ 由 `objects/` `actions/` `risks/` 目录 + 关系图派生（Tool 投影）；
- **同义词/别名** → 同址字段（见 `bkn/SYNONYMS.md` 宿主表）；
- **Tool → 文件映射** → `plugin/resolver.py` 的加载逻辑 + `plugin/skill_manifest.yaml`。

> 教训（写进 23 号反模式表）：索引段/导航段/中央同义词表**都随实例增长**，是本体层最典型的退化形态。


---

## SKILL.md 生成模板

```markdown
# 数据库同步运维 Agent

你是一个数据库同步运维 Agent，负责管理数据同步任务。（产品名与产品专属说法由产品 skill 提供。）

## BKN 按需参考

常规操作直接执行内建知识。仅遇到以下情况时查阅对应 BKN 文件：

| 遇到问题时 | 参考文件 |
|-----------|---------|
| 不确定对象属性 | objects/ (数据库、任务、表映射、列映射) |
| 不确定命令/参数 | 命令与参数值不在 BKN，查对应 Skill（值委托指针见 objects/ 段内正文） |
| 写操作风险评估 | risks/ (性能、安全、运维) |
| 排查依赖关系 | bkn/relations/*.bkn |

## 核心规则 (来自 Risk)

1. 状态变更必须符合 Object.SyncTask 状态机
2. 不确定风险时查阅 risks/ 对应文件
3. 触发 Risk 条件时禁止操作并告警
4. 自动重试达到上限（<重试次数>）→ 必须升级人工
```

---


---

## Action 绑定模式: implements

BKN 定义 **稳定的业务语义**，Skill 提供 **可变的实现细节**：

```bkn
## Action: 创建同步规则

- capability: create_sync_rule
- object: syncrule
- access_type: write
- binding_type: skill
- implements: skill:{sync_manager_skill}   ← 只引用 Skill，不放命令
- params: rule_name(string,required) src_db_uuid(uuid,required) tgt_db_uuid(uuid,required)
- prerequisites: [activate_node, register_source_db, register_target_db]
- constraints: [source NORMAL, target NORMAL, dry-run first]
- risks: [<该产品的错误码/症状别名>]
- notes: 必须先 dry-run 预览，确认后执行（具体预览方式由 Skill 提供）
```

**为什么不能在 BKN 里写 command**: 脚本路径/环境/PYTHONPATH 随版本变化，BKN 应该稳定。BKN 只定义 capability + params + constraints，Skill 提供 script + workdir + env + command_template。

**扩展时改什么**: 新增操作 → 改 BKN Action。改脚本路径 → 只改 Skill。两者独立演进。
