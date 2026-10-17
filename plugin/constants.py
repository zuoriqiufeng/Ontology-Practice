"""constants.py — Demo Product 跨模块共享常量

统一维护已知数据库列表、别名映射和噪声变体。
新增数据库只需在此文件改一处。
"""

# 已知支持的数据库列表 (用于兼容性检查 + 噪声推导)
# 2026-09-10 按业务实际支持清单补齐: 磐维DB/Datahub/DWS/PolarDB-X/PolarDB-pg/MogDB/ClickHouse/AnalyticDB
KNOWN_DBS = [
    "Oracle", "MySQL", "SQL Server", "PostgreSQL", "DB2",
    "达梦", "OceanBase", "GaussDB", "TDSQL", "GoldenDB",
    "KingBase", "YashanDB", "VastBase", "Kafka", "Hive",
    "HBase", "Doris", "Starrocks", "TiDB", "MongoDB", "Redis",
    "MariaDB", "Sybase", "Informix",
    "MogDB", "PolarDB-X", "PolarDB-pg", "磐维DB",
    "ClickHouse", "DWS", "AnalyticDB", "Datahub",
]

# 别名映射: 短写/英文名 → 规范名
DB_ALIASES = {
    "dm": "达梦",
    "mssql": "SQL Server",
    "sqlserver": "SQL Server",
    "pg": "PostgreSQL",
    "ob": "OceanBase",
    "kingbase": "KingBase",
    "vastbase": "VastBase",
    "gauss": "GaussDB",
    # 业务清单中的复合/变体写法 (2026-09-10)
    "panwei": "磐维DB",
    "panweidb": "磐维DB",
    "polardb-x": "PolarDB-X",
    "polardb-pg": "PolarDB-pg",
    "oceanbase@mysql": "OceanBase",   # OB MySQL 模式写法, 归 OceanBase
    "tdsql for pg": "TDSQL",          # TDSQL PG 版业务写法
    "mogdb": "MogDB",
    "datahub": "Datahub",
    "dws": "DWS",
    "clickhouse": "ClickHouse",
    "adb": "AnalyticDB",
    # 批 3-1：原 network.bkn「数据库同义词」中央表迁入（同址宿主 = 生产链路 DB_ALIASES）。
    # 大小写变体（ORACLE/Postgres/…）由 normalize_db 的 lower() 归一，不逐条登记。
    "ora": "Oracle",
    "甲骨文": "Oracle",
    "oracle database": "Oracle",
    "my": "MySQL",
    "mysqld": "MySQL",
    "mariadb": "MariaDB",
    "postgres": "PostgreSQL",
    "pgsql": "PostgreSQL",
    "db/2": "DB2",
    "ibm db2": "DB2",
    "dm8": "达梦",
    "dameng": "达梦",
    "达梦数据库": "达梦",
    "ocean base": "OceanBase",
    "gauss": "GaussDB",
    "华为gaussdb": "GaussDB",
    "yashan": "YashanDB",
    "崖山数据库": "YashanDB",
    "卡夫卡": "Kafka",
    "pingcap tidb": "TiDB",
}

# 噪声变体: 某些 DB 在 Qdrant 文档中可能有多种写法 (key 为规范名)
DB_NOISE_VARIANTS = {
    "PostgreSQL": ["Postgres", "psql", "public schema", "search_path"],
    "达梦": ["DM同步规则", "DM数据库"],
    "SQL Server": ["MSSQL"],
}

# 错误码前缀 → 数据库 (值为小写标识, 与 diagnose_db_link 历史返回值一致)
# 新增数据库错误码族只在此处加一行; 匹配时按前缀长度降序, 避免短前缀抢占。
# 未核实的错误码族 (达梦/KingBase/GaussDB) 核实前禁止猜测添加——错前缀会引向错误路由。
# OceanBase 无需独立前缀: ora 模式错误码 ORA- 兼容、mysql 模式 MySQL 兼容, 靠别名/显式参数覆盖。
DB_ERROR_PREFIXES = {
    "ORA-": "oracle",
    "YAS-": "yashandb",
    "PG-": "postgresql",
    "DB2": "db2",
    "MSSQL": "sqlserver",
    # "MSG ": "sqlserver",  # SQL Server 消息头 (待核实后启用)
    "MYSQL": "mysql",
}

# ── 诊断域值数据（25 号：自 BKN 别名下沉，与 DB_ALIASES 同层）─────────────
#
# 25 号方案：`objects/diagnostics.bkn` 的「错误码锚点 / 症状锚点」两张表已删除——
#   · 「触发进程」列 = `relations/process_topology.bkn` 的 suspected_in 边（本体形态，权威）；
#   · 「检索指引」列 = 一条规则常量（DIAG_RETRIEVAL_GUIDE）；
#   · 「别名」列 = 值数据（现场口语 → 规范 ID 的归一映射）→ 下沉到本层。
# 规范 ID 空间（有哪些码/症状）由**边**承载；本表只做「口语 → ID」的归一映射。
# 机械变体（4073 → -4073、错误4073、ORA1555 → ORA-01555）由 resolver._error_code_variants 派生，不在此登记。

ERROR_ALIASES = {
    "日志解析异常": "-4073",
    "REDO位点异常": "-4002",
    "崖山增量异常": "YAS-02276",
    "工作节点离线": "-4016",
    "数据库未打开": "ORA-01109",
    "登录失败": "ORA-01017",
    "用户名/密码错误": "ORA-01017",
    "无监听": "ORA-12541",
    "目标端无监听器": "ORA-12541",
    "连接标识符无法解析": "ORA-12154",
    "TNS": "ORA-12154",
    "通用失败": "-1",
    "运行中操作冲突": "-4071",
    "ABNORMAL禁止重启": "-4031",
    "装载进程异常": "-4046",
    "snapshot too old": "ORA-01555",
    "快照过期": "ORA-01555",
    "表不存在": "ORA-00942",
    "对象缺失": "ORA-00942",
    "PL/SQL编译错误": "ORA-24344",
}

SYMPTOM_ALIASES = {
    # 现场说法 → 规范症状 ID（值为 `symptom:` 后的裸 ID）
    "增量卡住": "incremental_stuck", "同步卡住": "incremental_stuck",
    "同步不动了": "incremental_stuck", "位点不推进": "incremental_stuck",
    "规则变红": "incremental_stuck", "同步停滞": "incremental_stuck",
    "增量延迟": "incremental_stuck", "同步延迟大": "incremental_stuck",
    "卡住不动": "incremental_stuck", "同步没同步": "incremental_stuck",
    "增量没同步": "incremental_stuck",
    "数据对不上": "data_mismatch", "数据错乱": "data_mismatch",
    "两端不一致": "data_mismatch", "校验不一致": "data_mismatch",
    "数据不一致": "data_mismatch", "数据不同步": "data_mismatch",
    "数据校验失败": "data_mismatch", "数据差异": "data_mismatch",
    "崩溃重启": "crash_loop", "起不来": "crash_loop", "反复重启": "crash_loop",
    "进程挂了": "crash_loop", "崩溃循环": "crash_loop", "进程崩溃": "crash_loop",
    "挂了": "crash_loop", "报错": "crash_loop", "出错": "crash_loop",
    "失败": "crash_loop", "crash": "crash_loop", "进程退出": "crash_loop",
    "连不上库": "connection_error", "连接超时": "connection_error",
    "认证失败": "connection_error", "端口不通": "connection_error",
    "连接失败": "connection_error", "连接异常": "connection_error",
    "无法连接": "connection_error", "连不上": "connection_error",
    "连不通": "connection_error", "不通": "connection_error",
    "超时": "connection_error",
    "变慢了": "performance_degradation", "延迟大": "performance_degradation",
    "追不上": "performance_degradation", "队列堆积": "performance_degradation",
    "性能下降": "performance_degradation", "性能问题": "performance_degradation",
    "同步慢": "performance_degradation", "延迟高": "performance_degradation",
    # 表现型（无标准错误码的现场表现）
    "脏数据": "dirty_data_rejected", "装载拒绝": "dirty_data_rejected",
    "断点续传": "resume_from_breakpoint_failed", "续传失败": "resume_from_breakpoint_failed",
    "TrackIPC": "track_ipc_rule_not_found", "rule not found": "track_ipc_rule_not_found",
}

# 检查维度旧称/口语 → `dimension:` 后的裸 ID（21 号前 `class:*` 命名空间退场后的旧名同址化）
# 注意：与 SYMPTOM_ALIASES 冲突的键（「数据差异」）以症状优先——索引构建顺序症状在前，setdefault 不覆盖。
DIMENSION_ALIASES = {
    "资源压力": "resource", "resource_pressure": "resource",
    "数据差异": "consistency", "data_diff": "consistency",
    "状态冲突": "state_machine", "state_conflict": "state_machine",
    "未归类": "unknown",
}

# 诊断检索指引（一条规则，替代原锚点表逐行重复的「检索指引」列）
DIAG_RETRIEVAL_GUIDE = "store:log_patterns_collection#错误码"

# ── 检索源单点表（38 号批 1：自 resolver.get_evidence_sources 的分支表收拢）──────
# 口径与收敛前**逐字一致**（21/25 号接线不变）：源端进程（iatrack/iadumper/ialoader）
# 与两个「跨切面」维度（consistency/state_machine）以日志模式库为先，其余进程/维度走主集合。
# 键＝带命名空间的目标 ID；未列出的 `process:*`/`dimension:*` → 默认主集合；其它前缀 → 空。
# 边界：这是**值数据**（检索源顺序），BKN 不承载 `store:` 引用（内容文件零使用，仅模板占位）；
# 若将来改"边驱动"，须先动本体（另立项，见 doc/optimize/38 号 §0.2-1）。
EVIDENCE_SOURCES_DEFAULT = ["store:demo_product_collection"]
EVIDENCE_SOURCES = {
    # 对象轴：源端进程 → 日志模式库优先（20 号方案）
    "process:iatrack": ["store:log_patterns_collection#日志模式", "store:demo_product_collection"],
    "process:iadumper": ["store:log_patterns_collection#日志模式", "store:demo_product_collection"],
    "process:ialoader": ["store:log_patterns_collection#日志模式", "store:demo_product_collection"],
    # 跨切面维度：数据一致性/状态机 → 主集合优先
    "dimension:consistency": ["store:demo_product_collection", "store:log_patterns_collection#日志模式"],
    "dimension:state_machine": ["store:demo_product_collection", "store:log_patterns_collection#日志模式"],
}

# 场景提示词表 (21 号 2C：单一事实源) —— design_solution 的 scenario_hint enum、
# tools 的 hint→场景名映射、resolver 路由规则的中文场景名，三处由本表派生/对齐。
# 新增场景：在 _SCENARIO_ROUTING_RULES（resolver.py）登记中文场景名 + 在此加一行，enum 自动跟上。
SCENARIO_HINTS: dict = {
    "migration": "跨平台迁移",
    "dual_active": "数据库双活",
    "bigdata": "大数据采集分析",
    "disaster_recovery": "两地三中心",
    "auto": "",  # 自动匹配（按源/目标路由规则），无固定场景名
}

# ── BKN 类型枚举 (v1.5, P0-5) ─────────────────────────────
# 与 bkn/SCHEMA.md 保持一致, lint_bkn.py 从此处导入

# Object 属性类型 (objects/*.bkn 属性表「类型」列)
VALID_ATTRIBUTE_TYPES = [
    "string", "decimal", "integer", "boolean", "datetime",
    "enum", "object", "array", "json",
]

# Section 块类型 (`<!-- type: xxx -->` 标注, resolver._parse_section_type 消费)
# 26 号（四元收敛终态）：段类型白名单 **4 种**，与 KWeaver 四元（Object/Relation/Action/Risk）一一对应。
# `index`/`matrix`（23 号）、`symptom`/`class`（24 号）、`scenario`（26 号，归档为 entity 类定义，
# `scenario:` 命名空间保留供边引用）均已退场——历史类型见 `CHANGELOG.md` 归档表。
# 与 bkn/SCHEMA.md「0. 段类型」逐字对齐（唯一口径源）
VALID_SECTION_TYPES = [
    "entity", "action", "relation", "risk",
]

# 运行时进程对象注册集（24 号：目录不再是语义信号——原 bkn/processes/ 已并入 objects/）
# 用途：resolver 识别进程对象、lint 做「常量集 ↔ objects/<id>.bkn 存在性」一致性校验。
PROCESS_IDS = [
    "iatrack", "iadumper", "ialoader", "iahelper", "iamonitor", "iadiff", "iaproxy",
]

# 9.0 版本之前的进程名（用户 2026-10-13 口径）——**不是** PROCESS_IDS 的成员：
#   iawork = 9.0 前源端全量程序；iaback = 9.0 前 Oracle 链路的备端。
# 用途：日志模式库/提取脚本归一 component 时区分「历史名」与「拼写错误」，避免被硬映射到某个 9.0 进程。
LEGACY_COMPONENTS = ("iawork", "iaback")

# 关系类型 → 目标对象命名空间前缀白名单 (lint_bkn 校验映射规则目标写法)
# 入表口径（2026-10-14 实测校准）：目标**同时**满足两条的关系才入表——
#   ① 目标带受控命名空间前缀；② 目标是 snake_case 标识符。
# 目标是对象裸名、或**人类可读名**（中文名 / 括号注记）的关系**不入表**：
#   runs_on / registered_on / references / reads_from / writes_to / has_action / consumes / produces /
#   monitors / connects_to / subclass_of / triggers / amplifies / mitigated_by / constrained_by /
#   implements / requires / constrains / prerequisite / supports（末 5 种的目标是可读名——见下 ⚠️②）。
#
# ⚠️ 2026-10-14 更正（两条，均经实测）：
#   ① 原注释记「其余关系的目标为对象/动作裸名」——**理由写错了**。`implements` / `requires` /
#      `constrains` / `prerequisite` / `supports` 的目标**是带命名空间的**，但用的是**中文可读名**
#      （`architecture:全量同步`、`operation:Oracle开启归档(abstract)`、`target:Kafka` 等）。
#      一旦入表，lint 立刻报 **45 条** warning（非 ASCII 实例名 / 标识符混入括号注释）——**实测**。
#      结论：它们不是「登记漏了」，而是**按值数据分工制（SCHEMA §0.5 / 24 号 §2.5）应当下延**的项，
#      登记为漂移 **R-12**，**不靠入表掩盖**（入表只会把 45 条 warning 转成常态噪声）。
#   ② `implements_skill` 是**真漏登记**：目标是 `skill:<snake_case>`（干净），入表后 0 warning，
#      已补登 ⇒ 机检对「action 绑定 Skill」从此强制。命名空间全集见 `bkn/SCHEMA.md` §0.1。
# 依据: doc/optimize/14-symptom-ontology-design.md + doc/optimize/15-ontology-conformance-audit.md §4.1
RELATION_TARGET_NAMESPACES = {
    "has_class": ["dimension:"],       # 症状 → 跨切面检查维度（21 号方案：class:* 退场，目标改 dimension:）
    "diagnosed_by": ["skill:"],         # 诊断类 → Skill
    "observed_in": ["log:"],            # 诊断类 → 日志
    "risks_of": ["risk:"],              # 动作/场景 → 无码风险（38 号批 1：`error:` 随 Q27 去码后零使用，已删）
    # 20 号方案: 运行时对象域——进程拓扑边
    "feeds": ["process:"],              # 进程 → 进程（数据流下游）
    "supervises": ["process:"],         # 进程 → 进程（生命周期管理）
    "suspected_in": ["process:"],
    # C-20261012-14：机制「表现为」——目标带命名空间前缀（symptom:/dimension:），故需登记
    "manifests_as": ["symptom:", "dimension:"],       # 症状 → 进程（嫌疑进程）
    # 2026-10-14 补登（真漏登记，见 ⚠️②）：目标 `skill:<snake_case>`，入表后 0 warning
    "implements_skill": ["skill:"],                    # 动作 → 绑定 Skill（actions/*.bkn 的 implements 字段同址）
    # consumes/produces/monitors 目标是 dbnode 裸名（与 references 同规，不入此表）
}

# Risk 风险类型 (risks/*.bkn 的 risk_type / 约束表格「类型」列)
VALID_RISK_TYPES = [
    "threshold", "state_prerequisite", "param_constraint", "forbidden_sequence",
    "resource_limit", "compatibility", "data_loss", "performance",
]

# Risk 严重程度 (severity / 风险级别)
VALID_SEVERITY = ["info", "warning", "critical"]

# 历史严重程度写法 → 标准枚举 (用于 lint 归一提示)
SEVERITY_LEGACY_MAP = {
    "CRITICAL": "critical",
    "HIGH": "warning",
    "MEDIUM": "info",
}

# Action 访问类型 (actions/*.bkn 的 access_type, P1 启用)
VALID_ACCESS_TYPES = ["read", "write", "admin"]

# Action 绑定类型 (actions/*.bkn 的 binding_type, P3 预留)
# 当前仅 "skill" 启用; 预留 "mcp"/"local"/"api" 为未来直连执行留扩展口
VALID_BINDING_TYPES = ["skill"]

# chunk_mode (search_qdrant)
VALID_CHUNK_MODES = ["auto", "mini_first", "parent_expand", "standard_image", "large_only"]

# confidence (Tool 返回)
VALID_CONFIDENCE = ["full", "partial", "none"]


def normalize_db(name: str) -> list[str]:
    """将数据库名展开为规范名列表, 消除别名歧义

    支持复合名: "达梦 DM" → ["达梦 DM", "达梦"]
    别名映射:  "DM" → ["DM", "达梦"], "pg" → ["pg", "PostgreSQL"]
    """
    name_stripped = name.strip()
    name_lower = name_stripped.lower()
    result = [name_stripped]

    # 1. 整体别名匹配
    canonical = DB_ALIASES.get(name_lower, "")
    if canonical and canonical != name_stripped:
        result.append(canonical)

    # 2. 分词别名匹配 (处理 "达梦 DM" 这种复合名)
    for word in name_lower.split():
        canonical = DB_ALIASES.get(word)
        if canonical and canonical not in result:
            result.append(canonical)

    return result


def is_db_match(candidate: str, db_target: str) -> bool:
    """检查 db (规范名) 是否匹配候选名 (含别名展开)"""
    variants = normalize_db(candidate)
    return any(db_target.lower() in v.lower() for v in variants)
