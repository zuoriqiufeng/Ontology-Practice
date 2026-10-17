# 速查：改什么文件、是否需生效（updater 侧）

> **定位**：updater（本体/Skill/Plugin 三层）改动时的「按场景查表」页。内容取自
> 原 doc/update/quick-reference.md（2026-10-15 清理）（全表逐字搬运），并**补入热重载作用域更正**（见「三」）。
> **一句话结论**：凡是 **BKN 数据** 或 **Plugin 代码** 的改动，**以重启服务进程为准**；
> 只改 **Skill 文本**（机制/脚本/环境/版本差异）不进 reload 链，也不需要重启。

---

## 一、结论前置：三层各自怎么生效

| 改动层 | 改什么 | 生效方式 |
|---|---|---|
| **BKN 数据** | bkn/ 下的 .bkn（动作、关系、风险、对象） | 重启服务进程（reload.py 只重建执行它的那个进程，见「三」） |
| **Skill 文本** | skill/<name>/SKILL.md、references/*.md、actions.yaml | 无需 reload、无需重启（消费方按需读取文本） |
| **Plugin 代码** | plugin/*.py | 重启 Hermes（即重启服务进程） |
| **配置** | plugin/config.yaml | 重启 Hermes |

---

## 二、按场景速查（含表头 21 行 / 20 条场景，对应原文行 7–28）

| 我想... | 改什么 | 需要热重载? |
|--------|------|:--:|
| 新增一个操作 (如"重置规则") | bkn/actions/ + bkn/relations/（references + action_routing）+ Skill SKILL.md | ✅ |
| 改脚本路径 | Skill SKILL.md | — |
| 换控制台 IP | Skill SKILL.md (env) | — |
| 升级 SDK 版本 | Skill SKILL.md (notes) | — |
| 新增错误码 | bkn/relations/process_topology.bkn 补 suspected_in 边 + plugin/constants.py::ERROR_ALIASES 加别名（25 号：BKN 不建清单，完整属性查库） | ✅ |
| 新增症状 | bkn/relations/process_topology.bkn 补 suspected_in/has_class 边 + plugin/constants.py::SYMPTOM_ALIASES 加别名 | ✅ |
| 新增操作约束 | bkn/risks/constraints.bkn + bkn/relations/action_routing.bkn | ✅ |
| 新增数据库兼容性/版本 | ❌ 不进 BKN——写 skill:demo-product-migration-designer/references/compatibility.md（值数据） | — |
| 新增场景 | bkn/objects/scenario-*.bkn（xxx.bkn + bkn/relations/scenario.bkn | ✅ |
| 补充产品信息 | bkn/objects/product.bkn | ✅ |
| 补充架构原理 | ❌ 不进 BKN（叙述层）——写 skill:demo-product-product-knowledge/references/architecture.md | — |
| 新增诊断工具能力 | 不写 BKN——能力定位并入 skill:demo-product-db-diagnostics（原 tools-index.bkn 已删，20 号方案清理） | — |
| 新增库 | plugin/constants.py（KNOWN_DBS/别名）+ bkn/objects/database.bkn 加对象段；逐库检查点下延 skill:demo-product-db-diagnostics/references/db-checkpoints.md | ✅ |
| 新增网络链路 | bkn/objects/netlink.bkn 注册集加行 + bkn/relations/topology.bkn 的 connects_to 补两端边（端口值仍由 Skill 提供） | ✅ |
| 控制机/许可/控制台认证 | bkn/objects/controlnode.bkn + skill:demo-product-list-lic / demo-product-proxytest（值委托） | — |
| 进程诊断（进程挂死/无错误码） | **不写 BKN**（进程是常数集）——用 diagnose_db_link(process=进程名) 走进程推导链（20 号方案） | — |
| 新增对象类型 | bkn/objects/xxx.bkn + bkn/relations/references.bkn | ✅ |
| 修改 Plugin 代码 | Plugin *.py | 重启 Hermes |
| 更新配置文件 | plugin/config.yaml | 重启 Hermes |
| 更新 BKN 后验证 | — | ✅ reload.py |

> ⚠️ 上表末行「更新 BKN 后验证 → ✅ reload.py」**与「三」的更正冲突**：reload.py 对**常驻服务进程不生效**，
> 它只适合**一次性新进程**自验。常驻进程以重启为准。此行为原文保留，**按「三」执行**。
> ⚠️ 「新增场景」一行原文为 bkn/objects/scenario-*.bkn（xxx.bkn，括号未闭合，疑为笔误，**待确认**；此处逐字保留。

---

## 三、热重载作用域更正 ★（本页最重要的一节）

**旧表述**（原文 原 doc/update/quick-reference.md（2026-10-15 清理）「热重载命令」节、plugin/CLAUDE.md:60 旧句）：
「改完 BKN 跑 reload.py 即生效」。

**更正后的本仓口径**：

| 场景 | reload.py 生效吗 |
|---|---|
| 一次性新进程（如每次都是新进程的 CLI 调用） | ✅ 生效（新进程自己加载） |
| **常驻服务进程（已注册的插件实例）** | ❌ **不生效**——它仍持旧对象 |

**原因（代码证据）**：reload.py 只重建**执行它的那个进程**里的全局对象
（plugin/scripts/reload.py:93,108-110 重建 tools._resolver / tools._traverser / tools._loader），
而 python3 scripts/reload.py 是**短命进程**——跑完即退出。常驻服务进程持有自己的一组句柄：
plugin/tools.py:31-33 是模块级全局，plugin/tools.py:101-105 的 _init() **只在句柄为 None 时创建，
此后没有任何失效或重建路径**。--watch 模式同理（plugin/scripts/reload.py 的 _watch() 也是独立进程）。

**危险点**：这条命令的输出与「成功生效」**完全一样**，**退出码也是 0**——不改代码分辨不出来。

**结论**：要让改动对**常驻服务进程**生效，**以重启服务进程为准**。

**复现实验（2026-10-10，隔离副本，原文照录）**：

	[常驻进程] _init() 后已解析文件数 = 34
	[磁盘] 新增 bkn/objects/_drill_probe.bkn（模拟本体内容变化）
	[独立进程] python3 plugin/scripts/reload.py → 退出码 0；首行：BKN 数据已重新加载
	[常驻进程] 独立进程 reload 之后 = 34（期望 == 34，即不生效）
	[常驻进程] 进程内 reload() 之后 = 35（期望 == 35，即生效）
	结论：✅ 复现——独立进程 reload 不影响常驻进程；进程内 reload 生效

**证据出处**：`skill:bkn-release/references/release-flow.md` §3.2（本仓实测，该节明确「更正一处旧表述」）；
plugin/CLAUDE.md:61（"BKN updates require a service-process restart to take effect on the serving instance"）。

**进程层自检（证明「进程与磁盘一致」）**：

	python3 plugin/scripts/check_loaded_version.py   # 0=一致；1=磁盘已改、进程未加载（重启）；2=无记录

**BM25 边界（顺手更正）**：.bkn 文本改动**不需要**重建 BM25（BM25 语料是 Qdrant collection 文档，
本仓没有把 bkn/ 送进 Qdrant 的代码路径）。只有 Qdrant 语料本身更新过才需要
python3 scripts/reload.py --with-bm25；且它同样只清**调用进程**的内存索引，常驻进程重启即重建。

---

## 四、文件改动范围（原文照录）

	操作相关:
	  bkn/actions/rule_lifecycle.bkn     ← 规则操作定义
	  bkn/actions/node_lifecycle.bkn     ← 节点操作定义
	  bkn/actions/db_lifecycle.bkn       ← 数据库操作定义
	  bkn/actions/compare_lifecycle.bkn  ← 表比较操作定义
	  bkn/relations/references.bkn       ← 关系: Object→Action
	  bkn/relations/action_routing.bkn   ← 关系: Action→Skill / constrained_by

	知识相关 (23 号：本体层只留定义/关系/实例登记；值数据下延 Skill):
	  bkn/objects/product.bkn            ← 产品本体（定位/核心能力/适用场景；对比/指标下延 Skill）
	  bkn/risks/constraints.bkn          ← 操作约束登记
	  bkn/objects/scenario-*.bkn（*.bkn  ← 方案场景骨架（优势/拓扑选择下延 Skill）
	  bkn/objects/*.bkn                  ← 业务对象
	  bkn/objects/database.bkn           ← DB 对象定义事实（版本表下延 Skill）

	诊断相关 (23 号：根级入口 + 注册集):
	  risks/constraints.bkn                     ← 约束登记 + 全局约束与诊断原则（rule:*）
	  bkn/objects/dimensions.bkn                ← 检查维度注册集（dimension:* 8 个）
	  bkn/relations/process_topology.bkn        ← 归路边（suspected_in / has_class）

	运行时对象 (20 号方案，进程拓扑为主干):
	  bkn/objects/*.bkn                ← 9.0 规范 7 进程对象（iatrack/iadumper/ialoader/iahelper/iamonitor/iadiff/iaproxy）
	  bkn/relations/process_topology.bkn ← 进程拓扑边（feeds/supervises/consumes/produces/monitors/suspected_in）
	  bkn/objects/dimensions.bkn       ← 检查维度注册集（L1-L4，WHAT 轴）
	  bkn/objects/host.bkn             ← 主机对象

	实现相关:
	  Skill SKILL.md                     ← 命令/脚本/环境/版本差异

	基础设施:
	  plugin/config.yaml                 ← Qdrant/Embedding/Search 配置
	  plugin/*.py                        ← Plugin 代码 (极少改动)

> ⚠️ 原文树中有两处不一致，逐字保留并标注：① bkn/objects/scenario-*.bkn（*.bkn 括号未闭；
> ② 「诊断相关」段写 risks/constraints.bkn（缺 bkn/ 前缀）。两处**待确认**，以生效树实际路径为准。

---

## 五、热重载命令（原文照录）

	# 改完 BKN 文件后执行:
	cd <repo>/demo-product-bkn/plugin
	python3 scripts/reload.py

	# 预期输出:
	# BKN 数据已重新加载
	# 已加载 N 个操作: 创建同步规则, 启动同步规则, ...

> **使用范围警告**：上列命令与「成功」输出只对**一次性新进程**有效；常驻服务进程**不刷新**，
> 以上面的「三」为准——**以重启服务进程为准**。

---

## 六、验证命令（原文照录）

	# 验证 BKN 加载
	python3 -c "
	import sys; sys.path.insert(0, '<repo>/demo-product-bkn/plugin')
	from resolver import BKNResolver
	r = BKNResolver(bkn_root='<repo>/demo-product-bkn/bkn')
	print(f'文件: {len(r.cache)}, 操作: {len(r._operations)}')
	print(r.list_operations())
	"

	# 验证 Qdrant 搜索
	python3 -c "
	import sys; sys.path.insert(0, '<repo>/demo-product-bkn/plugin')
	from supplement import search_qdrant
	hits = search_qdrant('Oracle OceanBase 兼容性', top_k=3)
	for h in hits: print(f'[{h.get(\"score\",0):.4f}] {h[\"content\"][:100]}')
	"

**收尾门禁**（任何改动落盘后）：

	bash scripts/gate.sh

---

*来源：原 doc/update/quick-reference.md（2026-10-15 清理）（逐字搬运）＋ 原 doc/update/release-flow.md（2026-10-15 清理） §3.2 ＋ plugin/CLAUDE.md:61（作用域更正）。*
