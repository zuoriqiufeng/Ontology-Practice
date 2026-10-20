"""schemas.py — 13 个 Tool 的 JSON Schema 定义"""

from .constants import SCENARIO_HINTS  # 21 号 2C: scenario_hint enum 单一事实源

SCHEMAS = [
    {
        "name": "query_product",
        "description": "查询 Demo Product 产品本体（定位、核心能力、适用场景）。"
                       "当用户问 Demo Product 是什么、有什么优势时调用；"
                       "竞品对比/行业覆盖/信创适配等值数据不在本体层（23 号下延），"
                       "返回 delegated_to 指针（skill:demo_product-product-knowledge/references/product.md）。",
        "parameters": {
            "type": "object",
            "properties": {
                "aspect": {
                    "type": "string",
                    "enum": ["overview", "positioning", "advantages", "competitors", "industries", "xinchuang", "all"],
                    "description": "查询方面: overview=概述, positioning=产品定位, advantages=核心优势（本体层）, "
                                   "scenarios=适用场景（本体层）; competitors/industries/xinchuang/performance 等返回值委托指针"
                },
                "competitor": {
                    "type": "string",
                    "description": "竞品名, 如 OGG/DSG/Kettle。仅 aspect=competitors 时需要"
                }
            },
            "required": ["aspect"]
        }
    },
    {
        "name": "explain_architecture",
        "description": "查询 Demo Product 技术原理: 全量同步、增量同步、拓扑模式、事务一致性、数据校验、性能特性、各数据库实现细节。当用户问原理/架构/如何实现时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "enum": ["full_sync", "incremental_sync", "topology", "transaction", "validation", "performance", "oracle_log", "mssql_mode", "all"],
                    "description": "主题: full_sync/incremental_sync/topology=本体派生（进程链与拓扑边）; "
                                   "transaction/validation/performance/oracle_log/mssql_mode=值委托指针"
                                   "（skill:demo_product-product-knowledge/references/architecture.md）; all=全部"
                }
            },
            "required": ["topic"]
        }
    },
    {
        "name": "design_solution",
        "description": "根据源端和目标端数据库类型, 设计完整的同步方案。返回适用场景/兼容性约束/关联拓扑/前置要求/潜在风险。当用户要求设计同步方案、做迁移规划时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "源端数据库类型: Oracle/MySQL/PostgreSQL/SQLServer/DB2/DM/OceanBase/..."},
                "target": {"type": "string", "description": "目标端数据库类型"},
                "scenario_hint": {
                    "type": "string",
                    "enum": list(SCENARIO_HINTS),
                    "description": "场景提示: auto=自动匹配(默认)"
                }
            },
            "required": ["source", "target"]
        }
    },
    {
        "name": "check_compatibility",
        "description": "检查源端到目标端的兼容性: 本体层返回「是否受支持」（注册集判定）与 DB 对象定义事实；"
                       "版本下限/对象兼容性/按库约束/字符集明细为值数据（23 号下延），返回 delegated_to 指针 + Qdrant 兜底提示。",
        "parameters": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "源端数据库类型"},
                "target": {"type": "string", "description": "目标端数据库类型"},
                "source_version": {"type": "string", "description": "源端版本(可选)"},
                "target_version": {"type": "string", "description": "目标端版本(可选)"}
            },
            "required": ["source", "target"]
        }
    },
    {
        "name": "list_scenarios",
        "description": "列出 Demo Product 支持的应用场景。当用户描述需求但不清楚对应哪个方案时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "keywords": {
                    "type": "array", "items": {"type": "string"},
                    "description": "搜索关键词: 迁移/双活/容灾/大数据/同步/..."
                }
            },
            "required": []
        }
    },
    {
        "name": "diagnose_error",
        "description": "诊断 **Demo Product 产品错误码**（产品码表 / -NNNN）。不确定码来源（如 ORA-/TNS-/SQLSTATE/1062 等数据库原生码）时，先用 bkn_ask（它会按来源分流）。",
        "parameters": {
            "type": "object",
            "properties": {
                "error_code": {"type": "string", "description": "错误码: -4073/-4016/-4071/-4031/-4046/..."},
                "message": {"type": "string", "description": "该码所在的**日志消息文本**（可选）——语义规则按文本命中，给了才能定含义类别"},
                "log_source": {"type": "string", "description": "该码出现在哪个进程的日志（可选，如 iatrack/ialoader）——给了即可确定嫌疑进程"}
            },
            "required": ["error_code"]
        }
    },
    {
        "name": "get_prerequisites",
        "description": "获取某操作的前置条件检查清单。当用户准备执行操作前需要确认准备就绪时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["activate_node", "register_db", "create_rule", "start_rule", "stop_rule", "delete_rule", "compare_table", "failover"],
                    "description": "操作名: activate_node=激活节点, register_db=注册数据库, create_rule=创建规则, start_rule=启动规则, stop_rule=停止规则, delete_rule=删除规则, compare_table=表比较, failover=灾备切换"
                }
            },
            "required": ["operation"]
        }
    },
    {
        "name": "resolve_relation",
        "description": "查询 BKN 中实体之间的关联关系。当需要确认某个关系是否存在时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "source_entity": {"type": "string", "description": "源实体: syncrule/dbnode/worknode 或 action:xxx；O-域诊断可用 symptom:xxx / error:ORA-00942 / class:xxx；运行时对象可用 process:iatrack 等"},
                "relation_type": {
                    "type": "string",
                    "enum": ["requires", "implements", "constrains", "constrained_by", "prerequisite", "risks_of", "has_action", "references", "runs_on", "registered_on", "supports", "implements_skill", "reads_from", "writes_to", "has_class", "diagnosed_by", "observed_in", "feeds", "supervises", "consumes", "produces", "monitors", "suspected_in", "connects_to", "triggers", "amplifies", "manifests_as", "mitigated_by", "subclass_of", "diagnosis_path", "process_chain", "closure", "impact", "all"],
                    "description": "关系类型: requires=依赖, implements=实现, constrains=约束(主动), constrained_by=被约束, prerequisite=前置, risks_of=风险, has_action=拥有动作, references=引用, runs_on=运行于, registered_on=注册于, supports=支持, implements_skill=绑定Skill, reads_from=读取自(源端), writes_to=写入(目标端), has_class=归类(症状→诊断类), diagnosed_by=诊断由(类→Skill), observed_in=取证于(类→日志,有序), feeds=数据流向下游(进程→进程), supervises=生命周期管理(进程→进程), consumes=读取数据(进程→库), produces=写入数据(进程→库), monitors=状态监控(进程→库), suspected_in=嫌疑进程(症状/错误码→进程), connects_to=连接(link:链路→部署单元两端), triggers=直接触发(机制→机制), amplifies=放大传导(机制→机制,间接), manifests_as=表现为(机制→症状/维度), mitigated_by=受屏障于(机制→约束/动作), subclass_of=子类(类→类,继承语义挂在父类), diagnosis_path=O-域单跳(症状/错误码→类→Skill→取证日志,一次拿全), process_chain=进程链(进程→上下游全链+日志+工具类别), closure=边语义闭包(传递/复合/对称,每跳带依据 from/edge/to;复合腿带 composition 名), impact=**影响面**(起点沿本体声明的 5 类承载边 feeds/reads_from/runs_on/registered_on/supervises **双向**展开,按受牵连单元分组并给见证路径;起点不在覆盖内时如实返回 impact_note), all=全部(按关系类型分组返回 by_relation)"
                },
                "target_hint": {"type": "string", "description": "目标实体类型(可选): skill/action/object/risk"},
                "direction": {"type": "string", "enum": ["out", "in", "both"], "description": "走图方向(可选,默认 out=顺边): in=反查(谁引用了我), both=双向; 仅 depth>1 时生效; 对称边(connects_to)无论 direction 一律双向走"},
                "depth": {"type": "integer", "minimum": 1, "maximum": 3, "description": "跳数(可选,默认 1=直查——输出与既有完全一致)。depth>1 时按边语义展开并追加 paths 段(每个可达节点一条最短见证路径,含每跳依据 from/edge/to); relation_type 此时作为可穿边过滤(all=用 walk_policy 可穿边集); diagnosis_path/process_chain 两个出口忽略 depth; impact 默认 3、上限 3"}
            },
            "required": ["source_entity"]
        }
    },
    {
        "name": "resolve_operation",
        "description": "根据操作名返回 capability + 绑定的 Skill 列表。当模型知道要执行某操作但不知道用哪个 Skill 时调用。"
                       "返回的 `implements` 保留为首个 Skill（兼容），`implements_skills` 列出所有相关 Skill 及其角色；"
                       "`prerequisite_knowledge` 提供基于 BKN + Qdrant 多维度检索的前置条件、约束与常见错误（可直接阅读）；"
                       "`skill_hint` / `hint` 仅作为需要具体命令时加载 Skill 的辅助索引，不暴露路由职责。",
        "parameters": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "description": "操作名: 创建同步规则/启动规则/停止规则/删除规则/激活节点/注册数据库/表比较/灾备切换/..."
                }
            },
            "required": ["operation"]
        }
    },
    {
        "name": "search_qdrant",
        "description": "对 Demo Product Qdrant 向量库执行语义搜索。当 BKN Tool 返回 _search_deferred=true 或 gaps 建议补查时，用精确技术术语搜索补充数据。支持 chunk_mode 块感知策略、维度标注和覆盖度追踪。BGE 按 chunk_mode 过滤到指定 chunk_level，BM25 不过滤 chunk_level 并与 BGE 结果 RRF 融合（BM25 与 BGE 始终打同一集合——collection 参数对整个检索链路生效）。两种模式：单查询传 query；批量传 queries 数组并行搜索（最多 10 项）。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "单查询模式：搜索查询文本。使用精确技术术语（如 'PostgreSQL WAL logical decoding replication slot 增量同步'），避免泛化关键词。与 queries 二选一。"
                },
                "queries": {
                    "type": "array",
                    "description": "可选：批量模式。数组，每项 {query(必填), dimension(可选), top_k(可选), chunk_mode(可选), collection(可选，覆盖批次级 collection)}，内部并行搜索，结果按原序返回（最多 10 项，超出截断）。与 query 参数二选一。",
                    "items": {"type": "object"}
                },
                "top_k": {
                    "type": "integer",
                    "description": "返回结果条数（默认 5，最大 20；compact 模式默认 3）",
                    "default": 5
                },
                "compact": {
                    "type": "boolean",
                    "description": "可选：只取要点（输出压到 ≤1200 字符，建议 top_k=3）；需要完整片段时不要传",
                    "default": False
                },
                "collection": {
                    "type": "string",
                    "description": "可选：指定 Qdrant collection 名称（默认取自 config.yaml 的 qdrant.collection，当前为 demo_product_collection）。"
                                   "已注册集合的**权威清单 = plugin/skill_manifest.yaml 的 stores:**（store: 语义 ID → 物理集合名，21 号 2C 起不再在此双登记），"
                                   "当前含文档主集合 / 配置手册 / 日志模式库（建议 chunk_mode=mini_first + dimension='日志模式'）/ 私有文档四个。"
                                   "自定义集合支持 BM25+RRF 混合搜索与 chunk_mode 路由。"
                },
                "dimension": {
                    "type": "string",
                    "description": "可选：标注本次搜索的目标维度（如 字符集/类型映射、全量同步参数、增量/日志解析、断点续传/容错 等），用于跨调用维度覆盖追踪。传 '__report__' 仅返回覆盖度报告不搜索；传 '__reset__' 清空当前任务的覆盖度记录。"
                },
                "tool_name": {
                    "type": "string",
                    "description": "可选：触发本次搜索的 BKN Tool 名（如 design_solution），用于确定维度集。默认用 design_solution 的 9 维度。"
                },
                "chunk_mode": {
                    "type": "string",
                    "enum": ["auto", "mini_first", "parent_expand", "standard_image", "large_only"],
                    "description": "块感知检索策略，由 Agent 根据查询特征选择；未指定时默认 mini_first。mini_first=默认策略，BGE 搜 mini 后回源 standard，BM25 同集合内不过滤 chunk_level 补充；auto=明确要求兼容旧行为时使用，走全量 BGE+BM25 混合搜索；parent_expand=宏观问题（原理/方案/文档归属）时使用，全量 BGE 搜索后附加 large 大块上下文，BM25 同集合补充；standard_image=查询可能涉及图片/截图/流程图时使用，BGE 搜 standard+image，BM25 同集合补充；large_only=仅需高层次总结时使用，BGE 搜 large，BM25 同集合补充。",
                    "default": "mini_first"
                }
            },
            "required": []
        }
    },
    {
        "name": "diagnose_db_link",
        "description": "根据症状和/或数据库类型，推荐用于链路诊断的 Skill 列表并返回 BKN 风险上下文。"
                       "当用户描述同步异常症状（如'增量卡住'、'数据不一致'、'连接失败'、'性能下降'）或提供错误码前缀（ORA-/PG-/DB2/MSSQL/MySQL）时调用。"
                       "`symptom` 与 `error_code` 至少提供一个；若只提供 `error_code`，工具会根据错误码前缀推断数据库类型并读取风险上下文。"
                       "返回的 `knowledge_context` 封装了可直接消费的知识：分析思路、Skill 能力概要、BKN 风险上下文与 Qdrant 各维度 snippets；"
                       "`skill_context` 明确 primary Skill、加载时机与相关 Skill 索引；"
                       "保留的 `knowledge` / `recommended_skill` / `recommended_skills` / `knowledge_snippets` 为兼容字段。"
                       "本 Tool 不返回 action 列表，也不返回具体命令；Skill 加载后由 Skill 内部路由表决定执行哪些诊断动作。",
        "parameters": {
            "type": "object",
            "properties": {
                "symptom": {
                    "type": "string",
                    "description": "症状标识（21 号 2C 对齐 constants.SYMPTOM_ALIASES 的 8 个规范 ID，新增以常量为准）: "
                                   "incremental_stuck|data_mismatch|connection_error|performance_degradation|crash_loop|"
                                   "dirty_data_rejected|resume_from_breakpoint_failed|track_ipc_rule_not_found"
                },
                "db_type": {
                    "type": "string",
                    "description": "数据库类型: auto（按 error_code 前缀自动推断）或任意库名。常见: oracle|mysql|postgresql|"
                                   "sqlserver|db2|yashandb|gaussdb|dm|oceanbase。v3.8 起不硬限制、无默认值（推断不出 = unknown），"
                                   "错误码前缀映射见 constants.DB_ERROR_PREFIXES"
                },
                "error_code": {
                    "type": "string",
                    "description": "可选错误码，如 -4002, ORA-00001。用于读取 BKN 风险上下文并辅助推断数据库类型；可单独提供"
                },
                "process": {
                    "type": "string",
                    "description": "可选进程入口（20 号方案）：进程名（iatrack/ialoader/iadumper/iahelper/iamonitor/iadiff/iaproxy）。进程挂死常无错误码，此时用进程入口定位故障；返回 process_path（数据流链 + 各段日志/工具类别/频度）"
                }
            },
            "required": []
        }
    },
    {
        "name": "check_action_risk",
        "description": "RiskGuard 风险自查：在执行 Demo Product 写操作（删除规则/注册数据库/重启规则等）前，检查对象当前状态是否违反 L0 状态前置约束。返回 passed/block_reason。当 Agent 准备执行危险操作且已知晓对象状态时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "动作名: delete_sync_rule/register_db/restart_sync_rule（支持别名 delete_rule/register_database/restart_rule）"
                },
                "current_state": {
                    "type": "string",
                    "description": "对象当前状态: RUNNING/FULLSYNC/STOPPED/ABNORMAL/OFFLINE/ONLINE"
                }
            },
            "required": ["action"]
        }
    },
    {
        "name": "diagnose_mechanism",
        "description": "机制层归因（29 号 §4.5 契约）：给现象/错误码 ＋（可选）本次已得的观测，返回**候选机制**及其判据状态（confirmed/excluded/unknown）、**下一步最小验证动作**、证据缺口，以及「哪些是事实、哪些是推测」。与 diagnose_error 的分工：diagnose_error 管「码 → 含义 → 排查线」，本入口管「现象 → 候选机制 → 收敛」。**该说不知道时就明说不知道**——unknown 是合法答案，不许用推测填空。",
        "parameters": {
            "type": "object",
            "properties": {
                    "affected_unit": {"type": "string", "description": "受影响单元（可选；68 号 E-2）。给了就能把 structural 判据的「起点到受影响单元之间存在既有关系路径」那半步**机械核验完**（checkable 由 partial 变 full，并给出见证路径）；不给则与既有行为一致"},
                "entry": {"type": "string", "description": "现象入口：症状（incremental_stuck）／错误码（-4073 或 4073）／进程（process:iatrack）／命名空间节点（symptom:xxx、dimension:xxx）"},
                "observations": {"type": "array", "items": {"type": "string"}, "description": "本次已得的观测（日志行／字段读数），**可选——允许为空**（§4.5：允许 M < 所需）。可带来源标签 [来源]观测；无标签一律视为同源（保守：宁可判 unknown，不给假 confirmed）"},
                "max_candidates": {"type": "integer", "minimum": 1, "maximum": 10, "description": "候选上限（默认 4）——候选**召回**优先于 top-1 精度（§4.5 硬要求 2）"}
            },
            "required": ["entry"]
        }
    },
{
    "name": "bkn_ask",
    "description": (
        "用一句话问本体：给错误码或症状描述，返回摘要（≤600 字：结论 + 证据 + 该找哪个 Skill + 还缺什么）。"
        "当用户问「这个报错什么意思/怎么查」「某现象该怎么排查」时优先用它；"
        "数据库原生码（ORA-/TNS-/SQLSTATE/1062…）也用它：会按来源分流到产品诊断或 DB 诊断。"
        "需要完整细节时再传 detail=ref 取全文（体积可能很大）。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "自然语言问题（含错误码或症状描述最佳）"},
            "detail": {
                "type": "string",
                "enum": ["summary", "ref"],
                "description": "summary=摘要（默认）；ref=旧工具的完整返回",
            },
        },
        "required": ["question"],
    },
},
{
    "name": "check_plan",
    "description": (
        "检查一串运维步骤是否符合本体登记的前置与约束（机械核对，不推理）。"
        "输入 steps=[{action, state?}] 与可选 states={对象: 状态}；"
        "返回 violations（硬性不满足）、advisories（约束提醒）、todo（需人工确认）。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "description": "动作名或别名（见 bkn/actions）"},
                        "state": {"type": "string", "description": "目标对象当前状态（可选）"},
                    },
                    "required": ["action"],
                },
                "description": "按顺序执行的动作列表",
            },
            "states": {"type": "object", "description": "对象当前状态，如 {\"rule\": \"STOPPED\"}"},
        },
        "required": ["steps"],
    },
},
]
