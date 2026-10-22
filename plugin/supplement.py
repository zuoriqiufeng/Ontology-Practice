"""supplement.py — BKN 数据不充分时的补充机制

三层:
  L1 降级: 标记 confidence + gaps, 自动写 gap_log
  L2 补充: Qdrant 向量语义检索 (v3.0: Hermes-native decompose; v3.1: 维度追踪)
  L3 沉淀: gap_log.jsonl 累积, scan_gaps.py 定期扫描

依赖: config.yaml (qdrant/embedding/search 配置)
      sentence-transformers (BGE 模型, 仅本地模式)
      qdrant-client
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import List, Optional

from .config import (
    QDRANT_HOST, QDRANT_PORT, QDRANT_COLLECTION, QDRANT_TIMEOUT,
    EMB_MODE, EMB_MODEL_NAME, EMB_DEVICE, EMB_HF_OFFLINE, EMB_HF_HOME,
    EMBEDDING_DIMENSION,
    SEARCH_TOP_K, SEARCH_SCORE_THRESHOLD, SEARCH_HYBRID,
    SEARCH_FALLBACK_NONE, SEARCH_FALLBACK_PARTIAL,
    SEARCH_PARTIAL_ENRICH, SEARCH_MIN_CONTENT_LENGTH,
    SEARCH_MIN_RISK_COUNT,
    # v2.0 分解配置
    SEARCH_DECOMPOSE, SEARCH_DECOMPOSE_TOP_K,
    SEARCH_DECOMPOSE_MIN, SEARCH_DECOMPOSE_MAX,
    SEARCH_DECOMPOSE_DEDUP,
    # v3.0 Hermes 原生分解
    SEARCH_DEFER_TO_HERMES,
    # v3.3 BGE miss → BM25 fallback
    SEARCH_BM25_FALLBACK_SCORE,
    # v3.4 BGE precision guard
    SEARCH_BM25_PRECISION_GUARD,
    # v3.6 chunk-aware search
    SEARCH_CHUNK_MODE, MINI_FIRST_TOP_K_MULTIPLIER, PARENT_EXPAND_LIMIT_MULTIPLIER,
    # 2A 日志路径可配置
    resolve_log_path,
)
from .knowledge_registry import (
    KnowledgeRegistry,
    BknSectionSource,
    BknRiskContextSource,
    QdrantSearchSource,
)

# gap_log 逻辑基名（2A: 可配置，默认 <repo>/logs/，env LOG_DIR 可覆盖；
# 实际文件由 log_gap 写入时按日期派生：gap_log_YYYY-MM-DD.jsonl）
GAP_LOG_PATH = resolve_log_path("gap_log.jsonl")

logger = logging.getLogger(__name__)


# ======================================================================
#  44 号 §3.3 过程级埋点（B1 检索路径 / B5 判定依据）
#  纪律：只调 observability.track()（旁路累积，无 IO），**绝不改任何返回值**；
#        取字段的表达式一律包在 try/except 里——异常只丢日志，不闹事。
# ======================================================================

#: 单条 `search_path` 事件的路径条目上限（批内多查询共享同一收集器时的兜底）
MAX_PATH_STAGES = 24

#: 本次调用的检索路径收集器（None = 不在任何检索入口内）。
#: 检索是**分层**的（search_qdrant → _search_mini_first → _search_chunk_level →
#: _precision_guard_fallback → _search_content_exact / _fallback_scroll_*），
#: 单靠某个函数的局部 list 收不齐 6 条路径，故各层各自 `_path_add`，
#: 由**最外层入口**在出口一次性 `track("search_path", ...)`（一个决策点一条事件，
#: 44 号 §3.4-1；未执行的分支不入 paths）。
#: 并发：ContextVar 只复制映射、不复制对象——tools._search_qdrant_batch_inner 的
#: 线程池里各线程拿到的是**同一个 list 对象**，list.append 原子，故不加锁。
#: 代价（已知并接受）：入口异常逃逸时收集器残留在该次调用的上下文里，该次调用后续
#: 检索不再发事件——**只丢日志，不改任何返回值**。
_PATH_SCOPE = contextvars.ContextVar("bkn_search_paths", default=None)


def _path_enter():
    """开一次检索路径收集；已是嵌套调用 → 复用最外层收集器（token=None，不重复发事件）。"""
    cur = _PATH_SCOPE.get()
    if cur is not None:
        return cur, None
    c = {"paths": [], "dropped": 0, "queries": 0, "delivered": {"self": 0, "parent": 0}}
    try:
        return c, _PATH_SCOPE.set(c)
    except Exception:
        return c, None


def _path_hits(hits) -> int:
    """命中数：列表/字典 → len；数字 → 原值；取不到 → 0（异常静默）。"""
    try:
        if isinstance(hits, (list, tuple, set, dict)):
            return len(hits)
        return int(hits or 0)
    except Exception:
        return 0


def _path_add(path: str, hits=None, t0=None, stopped: str | None = None) -> None:
    """登记一段检索路径（B1）。

    `hits` 可传命中列表（自动取条数与最高分）或条数；`t0` 传 `time.perf_counter()` 起点；
    `stopped` 是**为什么停在这条路**的短语（hit_enough / no_hit / disabled / not_triggered
    / no_client_model / no_bm25 / no_index / no_cache / http_error / error / no_parent …）。
    """
    try:
        c = _PATH_SCOPE.get()
        if c is None:
            return
        if len(c["paths"]) >= MAX_PATH_STAGES:
            c["dropped"] += 1
            return
        top = None
        if isinstance(hits, (list, tuple)):
            _scores = [float(h.get("score")) for h in hits
                       if isinstance(h, dict) and h.get("score") is not None]
            top = round(max(_scores), 4) if _scores else None
        c["paths"].append({
            "path": path,
            "hits": _path_hits(hits),
            "top_score": top,
            "ms": int((time.perf_counter() - t0) * 1000) if t0 is not None else 0,
            "stopped": stopped,
        })
    except Exception:
        pass


def _path_query(n: int = 1) -> None:
    """登记本次入口发出的检索请求数（dense ANN / BM25 / 批量 scroll / exact 索引各计 1）。"""
    try:
        c = _PATH_SCOPE.get()
        if c is not None:
            c["queries"] += int(n)
    except Exception:
        pass


def _path_count_delivered(kind: str) -> None:
    """登记一次交付（`self` = 自交付自身块 / `parent` = 父块装配）——B1 的 `delivered` 字段。"""
    try:
        c = _PATH_SCOPE.get()
        if c is not None:
            c["delivered"][kind] = c["delivered"].get(kind, 0) + 1
    except Exception:
        pass


def _path_exit(c, token, final=None) -> None:
    """最外层检索出口：复位收集器 + 一次性 `track("search_path", ...)`。

    嵌套层（token=None）什么都不做——一次调用只发一条事件（44 号 §3.4-1）。
    `final` 传最终返回值，只取条数（其它一律不碰）。
    """
    if token is None:
        return
    try:
        _PATH_SCOPE.reset(token)
    except Exception:
        pass
    try:
        from .observability import track
        _fields = {
            "paths": c.get("paths") or [],
            "queries": int(c.get("queries") or 0),
            "final_hits": _path_hits(final),
            "delivered": dict(c.get("delivered") or {}),
        }
        if c.get("dropped"):
            _fields["paths_dropped"] = int(c["dropped"])
        track("search_path", **_fields)
    except Exception:
        pass


# ========== v3.1: 会话级维度覆盖追踪 ==========

# {task_id: {dim_name: hit_count}}  按 task_id 分桶, 避免跨对话覆盖度污染;
# 无 task_id 上下文的内部调用落 _DEFAULT_DIM_KEY 桶, 不进按任务报告。
_DEFAULT_DIM_KEY = "_default"
_DIM_STORE: dict[str, dict[str, int]] = {}

# ── v3.7: 诊断专用维度（拓展 design_solution 9 维度，新增规则配置维度）──

_DIAGNOSE_DIMENSIONS = [
    "增量/日志解析",
    "规则配置/装载策略",
    "数据校验/对比",
    "源端特定配置",
    "风险/异常处理",
    "字符集/类型映射",
    "全量同步参数",
    "断点续传/容错",
    "目标端特定配置",
    "跨地域/网络优化",
]

# 症状 → 维度优先级: critical=必查, suggested=建议查, optional=可跳过
_SYMPTOM_DIMENSION_PRIORITY = {
    "data_mismatch": {
        "增量/日志解析": "critical",
        "规则配置/装载策略": "critical",
        "数据校验/对比": "critical",
        "源端特定配置": "critical",
        "风险/异常处理": "suggested",
        "字符集/类型映射": "suggested",
        "全量同步参数": "suggested",
        "断点续传/容错": "optional",
        "目标端特定配置": "suggested",
        "跨地域/网络优化": "suggested",
    },
    "incremental_stuck": {
        "增量/日志解析": "critical",
        "断点续传/容错": "critical",
        "源端特定配置": "critical",
        "风险/异常处理": "suggested",
        "跨地域/网络优化": "suggested",
        "规则配置/装载策略": "suggested",
        "数据校验/对比": "optional",
        "字符集/类型映射": "optional",
        "全量同步参数": "suggested",
        "目标端特定配置": "optional",
    },
    "connection_error": {
        "跨地域/网络优化": "critical",
        "源端特定配置": "critical",
        "目标端特定配置": "critical",
        "风险/异常处理": "suggested",
    },
    "performance_degradation": {
        "增量/日志解析": "critical",
        "全量同步参数": "critical",
        "跨地域/网络优化": "critical",
        "源端特定配置": "suggested",
        "目标端特定配置": "suggested",
    },
    "crash_loop": {
        "风险/异常处理": "critical",
        "断点续传/容错": "critical",
        "源端特定配置": "suggested",
        "增量/日志解析": "suggested",
    },
}


def _get_dimension_priority(symptom: str, dim_name: str) -> str:
    """返回某症状下某维度的优先级: critical / suggested / optional"""
    if not symptom:
        return "suggested"
    pri_map = _SYMPTOM_DIMENSION_PRIORITY.get(symptom, {})
    return pri_map.get(dim_name, "optional")


def _get_known_dimensions(tool_name: str = None) -> list[str]:
    """返回某 Tool 的已知维度名列表"""
    if tool_name == "diagnose_db_link":
        return list(_DIAGNOSE_DIMENSIONS)
    templates = _DECOMPOSE_TEMPLATES.get(tool_name) if tool_name else None
    if templates:
        return [dim_name for dim_name, _ in templates]
    # 默认: design_solution 的 9 维度（最完整的维度集）
    ds_templates = _DECOMPOSE_TEMPLATES.get("design_solution", [])
    return [dim_name for dim_name, _ in ds_templates]

def get_dimension_coverage(tool_name: str = None, task_id: str = None) -> dict:
    """返回某任务 (task_id 分桶) 的维度覆盖度报告"""
    known = _get_known_dimensions(tool_name)
    bucket = _DIM_STORE.get(task_id or _DEFAULT_DIM_KEY, {})
    covered = [d for d in known if d in bucket]
    uncovered = [d for d in known if d not in bucket]
    return {
        "total_dims": len(known),
        "covered_dims": covered,
        "covered_count": len(covered),
        "uncovered_dims": uncovered,
        "uncovered_count": len(uncovered),
        "dim_hit_count": {d: bucket[d] for d in covered},
    }

def _track_dimension(dim_name: str, hit_count: int, task_id: str = None):
    """记录某维度的搜索命中数（按 task_id 分桶累积）"""
    if dim_name:
        bucket = _DIM_STORE.setdefault(task_id or _DEFAULT_DIM_KEY, {})
        bucket[dim_name] = bucket.get(dim_name, 0) + hit_count

def reset_dimension_coverage(task_id: str = None):
    """清空指定任务的维度覆盖记录"""
    _DIM_STORE.pop(task_id or _DEFAULT_DIM_KEY, None)

# 各 Tool 必需的关键字段 (缺失任一即视为 partial)
# 21 号 2B 校准：元组 = 「任一命中即可」（any-of）；字符串 = 必须存在。
# 23 号值委托改革后，「有内容或有下延指针」都是完整契约——故 query_product 等用 any-of。
REQUIRED_FIELDS = {
    "design_solution": ["scenario", "description", "compatibility"],
    # 23 号方案：version_notes/object_compat/charset_notes 为值委托（下延 Skill），
    # 本体侧必需字段 = supported（注册集判定）+ delegated_to（下延指针）
    "check_compatibility": ["supported", "delegated_to"],
    "explain_architecture": ["raw"],
    "query_product": [("raw", "delegated_to")],  # 值委托 aspect（competitors 等）返回指针即完整
    # 25 号 get_risk 已 stub 化（error_code/retrieval_guide/suspected_process/dimensions/
    # aliases/unknown_rule），旧契约的 diagnosis 全文已不存在（21 号 2B）
    "diagnose_error": ["error_code", "retrieval_guide"],
    "get_prerequisites": ["operation", "prerequisites"],
    "list_scenarios": ["scenarios"],
    "resolve_relation": ["source"],
    # 54 号（裁 2＝C）：机制归因出口的置信度必需字段——entry 与 candidates 恒存在（可为空表，表示无候选）
    "diagnose_mechanism": ["entry", "candidates"],  # 批 0-3: all→by_relation / 指定类型→targets，仅 source 恒存在；空 targets 是无边而非缺数据
    "resolve_operation": ["operation", "capability"],
    # 22 号批 4-2（2026-10-12）：3 个豁免 Tool 的置信度判定（此前完全无判定/gap 记录）。
    # 只增 tool-keyed 条目——9 个既有 Tool 的判定逐条不变。
    # search_qdrant 的 any-of 覆盖三种形态：单查询（hits）/ 批量（results）/ 覆盖度报告（coverage）；
    # 控制类响应（__reset__ 等）带 mode，靠 _deep_check 判；错误体（error+hint）无 mode → 判缺字段。
    "search_qdrant": [("hits", "results", "coverage", "mode")],
    "diagnose_db_link": ["knowledge_context"],
    "check_action_risk": ["action"],
}

# ========== Lazy-loaded singletons ==========

_qdrant_client = None
_embedding_model = None
_init_warnings: list[str] = []  # 依赖初始化失败/降级原因, 只写一次


def _record_init_warning(msg: str):
    """记录初始化警告, 避免重复"""
    if msg not in _init_warnings:
        _init_warnings.append(msg)


def get_search_warnings() -> list[str]:
    """返回当前已记录的搜索初始化/降级警告"""
    return list(_init_warnings)


def _get_qdrant_client():
    global _qdrant_client
    if _qdrant_client is None:
        try:
            from qdrant_client import QdrantClient
            _qdrant_client = QdrantClient(QDRANT_HOST, port=QDRANT_PORT, timeout=QDRANT_TIMEOUT)
        except ImportError:
            _record_init_warning("qdrant_client 未安装, 向量搜索不可用")
            _qdrant_client = False
        except Exception as e:
            _record_init_warning(f"Qdrant 客户端初始化失败: {e}")
            _qdrant_client = False
    return _qdrant_client if _qdrant_client is not False else None


def _validate_qdrant_dimension(client, collection_name: str = QDRANT_COLLECTION):
    """校验 Qdrant collection 向量维度与 embedding 模型输出维度是否一致

    不一致时抛出清晰错误，避免底层 400 被静默吞掉。
    """
    try:
        info = client.get_collection(collection_name)
        vectors = info.config.params.vectors
        if hasattr(vectors, "size"):
            size = vectors.size
        elif isinstance(vectors, dict):
            first = next(iter(vectors.values()))
            size = first.size if hasattr(first, "size") else first.get("size")
        else:
            size = None
        if size and int(size) != EMBEDDING_DIMENSION:
            raise ValueError(
                f"Qdrant collection '{collection_name}' 向量维度为 {size}，"
                f"与 embedding.dimension={EMBEDDING_DIMENSION} 不匹配，"
                f"请检查 config.yaml 中的 embedding.dimension 或重新创建 collection"
            )
    except ValueError:
        raise
    except Exception as e:
        # 无法获取 collection 信息时不阻断搜索，由后续查询自行报错
        logger.debug("无法校验 Qdrant collection 维度: %s", e)


def _get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        try:
            import os
            if EMB_HF_HOME:
                os.environ["HF_HOME"] = EMB_HF_HOME
            if EMB_HF_OFFLINE:
                os.environ["HF_HUB_OFFLINE"] = "1"
            from sentence_transformers import SentenceTransformer
            _embedding_model = SentenceTransformer(EMB_MODEL_NAME, device=EMB_DEVICE)
        except ImportError:
            _record_init_warning("sentence_transformers 未安装, Embedding 模型不可用")
            _embedding_model = False
        except Exception as e:
            _record_init_warning(f"Embedding 模型加载失败: {e}")
            _embedding_model = False
    return _embedding_model if _embedding_model is not False else None


# ========== L1: 置信度评估 ==========

def assess_confidence(result: dict, args: dict, tool_name: str = None) -> tuple[str, list[str]]:
    # ── B5（44 号 §3.3 `confidence_why`）：把「是哪个检查点判的 partial」旁路记下来 ──
    # **不改 gaps 文本**——改一个字，measure_confidence 的 45 例基线全漂、门禁 ④ 会红；
    # checkpoints 只进事件流，不进返回值。三个提前 return 处各发一次事件（一个决策点一条）。
    checkpoints: list[dict] = []

    def _emit_conf(conf: str, gaps_now) -> None:
        """出口埋点：confidence + 检查点清单 + gap 条数。任何异常只丢日志。"""
        try:
            from .observability import track
            track("confidence_why", confidence=conf,
                  checkpoints=list(checkpoints), gap_count=len(gaps_now or []))
        except Exception:
            pass

    gaps = []
    if not result or result == {}:
        checkpoints.append({"check": "empty", "verdict": "fail", "detail": ""})
        _emit_conf("none", ["BKN 未找到相关数据"])
        return ("none", ["BKN 未找到相关数据"])
    has_content = False
    for v in result.values():
        if v and v != {} and v != [] and v != "":
            has_content = True
            break
    if not has_content:
        checkpoints.append({"check": "empty", "verdict": "pass", "detail": ""})
        checkpoints.append({"check": "no_content", "verdict": "fail", "detail": ""})
        _emit_conf("partial", ["返回数据为空"])
        return ("partial", ["返回数据为空"])
    # 走到这里 = empty / no_content 两个检查点都过了（如实记 pass，便于统计误报率）
    checkpoints.append({"check": "empty", "verdict": "pass", "detail": ""})
    checkpoints.append({"check": "no_content", "verdict": "pass", "detail": ""})
    raw_text = json.dumps(result, ensure_ascii=False)
    if len(raw_text) < SEARCH_MIN_CONTENT_LENGTH:
        gaps.append(f"返回内容过短({len(raw_text)}字符 < {SEARCH_MIN_CONTENT_LENGTH}), 可能不充分")
        checkpoints.append({"check": "too_short", "verdict": "fail",
                            "detail": f"<{SEARCH_MIN_CONTENT_LENGTH}"})
    else:
        checkpoints.append({"check": "too_short", "verdict": "pass", "detail": ""})
    if tool_name and tool_name in REQUIRED_FIELDS:
        required = REQUIRED_FIELDS[tool_name]
        if required:
            for field in required:
                # 21 号 2B: any-of 语义——元组中任一字段命中即视为该组完整
                if isinstance(field, tuple):
                    if not any(
                        result.get(f) not in (None, "", [], {}) for f in field
                    ):
                        gaps.append(f"缺少关键字段(任一): {'/'.join(field)}")
                        # B5：detail 只写字段名，**不写字段值**（避免把用户数据写进日志）
                        checkpoints.append({"check": "required_field", "verdict": "fail",
                                            "detail": "/".join(field)})
                    else:
                        checkpoints.append({"check": "required_field", "verdict": "pass",
                                            "detail": "/".join(field)})
                    continue
                val = result.get(field)
                if val is None or val == "" or val == [] or val == {}:
                    gaps.append(f"缺少关键字段: {field}")
                    checkpoints.append({"check": "required_field", "verdict": "fail",
                                        "detail": field})
                # 长度下限 4：只拦「近乎空」的内容；error_code('-4073')、operation('failover')、
                # scenario('跨平台迁移') 等合法短标识符不再是误报（旧阈值 10 全部误伤，21 号 2B）
                elif isinstance(val, str) and len(val) < 4:
                    gaps.append(f"关键字段 {field} 内容过短({len(val)}字符): '{val[:30]}...'")
                    checkpoints.append({"check": "required_field", "verdict": "fail",
                                        "detail": f"{field}(too_short)"})
                elif isinstance(val, list) and len(val) == 0:
                    gaps.append(f"关键字段 {field} 为空列表")
                    checkpoints.append({"check": "required_field", "verdict": "fail",
                                        "detail": f"{field}(empty_list)"})
                else:
                    checkpoints.append({"check": "required_field", "verdict": "pass",
                                        "detail": field})
    gaps += _deep_check(result, tool_name, checkpoints=checkpoints)
    if gaps:
        _emit_conf("partial", gaps)
        return ("partial", gaps)
    _emit_conf("full", [])
    return ("full", [])


def _deep_check(result: dict, tool_name: str, checkpoints: list | None = None) -> list[str]:
    """深检（返回 gaps 文本，**逐字不变**）。

    B5（44 号 §3.3）：可选传入 `checkpoints` 收集判定依据——detail 只写**关键词/检查点名**
    （如缺少 `requires`），不写任何字段值；`checkpoints=None`（老调用方/测试直调）时静默跳过，
    返回的 gaps 文本与旧实现逐字一致。
    """
    gaps = []

    def _cp(verdict: str, detail: str) -> None:
        """记一个 deep_check 检查点（异常只丢日志）。"""
        try:
            if checkpoints is not None:
                checkpoints.append({"check": "deep_check", "verdict": verdict, "detail": detail})
        except Exception:
            pass

    if tool_name == "design_solution":
        rels = result.get("relations", {})
        if isinstance(rels, dict):
            if not rels:
                gaps.append("relations 为空, 缺少拓扑/约束/前置/风险信息")
                _cp("fail", "relations_empty")
            else:
                all_rel_text = json.dumps(rels, ensure_ascii=False).lower()
                for keyword in ["requires", "constrains", "prerequisite", "risks_of"]:
                    if keyword not in all_rel_text:
                        gaps.append(f"relations 中缺少 {keyword} 信息")
                        _cp("fail", keyword)          # B5：detail = 缺失的关键词名
                    else:
                        _cp("pass", keyword)
                risk_count = _count_risks(rels)
                if risk_count < SEARCH_MIN_RISK_COUNT:
                    gaps.append(
                        f"风险条目过少(仅{risk_count}条 < {SEARCH_MIN_RISK_COUNT}), "
                        "建议查 Qdrant 补充数据库特定/跨地域/版本兼容等风险"
                    )
                    _cp("fail", "risk_count")
                else:
                    _cp("pass", "risk_count")
            compat = result.get("compatibility", {})
            if compat and isinstance(compat, dict):
                # 23 号方案：值数据（版本/对象兼容/字符集）已下延 → delegated_to 指针即有效载荷
                has_notes = bool(
                    compat.get("delegated_to")
                    or compat.get("bkn_db_facts")
                    or compat.get("risks")
                )
                if compat.get("supported") and not has_notes:
                    gaps.append("兼容性确认但缺少版本/限制说明及其下延指针（delegated_to）")
                    _cp("fail", "compat_notes")
                else:
                    _cp("pass", "compat_notes")
        else:
            gaps.append("relations 格式异常, 非字典类型")
            _cp("fail", "relations_type")
    # （21 号 2B 校准）两处旧规则已删，依据如下：
    # 1) diagnose_error 的 diagnosis 全文检查——25 号 get_risk 已 stub 化，diagnosis 全文不再存在；
    #    stub 完整性由 REQUIRED_FIELDS（error_code + retrieval_guide）承载。
    # 2) 「无 enrichment/fallback_hint 一律 partial」通用骨架规则——写于值委托改革之前，
    #    与现行架构矛盾（23/26 号：BKN 返回骨架+指针就是完整契约）。defer 模式下 enrichment
    #    永不发生，该规则使 9 个 Tool 100% partial（40/40 实测），每次调用背 _instruction 固定税。
    #    真缺字段的场合仍由 REQUIRED_FIELDS/_deep_check 判 partial。
    # 22 号批 4-2（2026-10-12）：3 个豁免 Tool 的 tool-keyed 分支（只影响这 3 个 Tool）
    if tool_name == "search_qdrant":
        hits = result.get("hits")
        if isinstance(hits, list) and not hits:
            gaps.append("检索无命中（0 条）")
            _cp("fail", "no_hits")
        else:
            _cp("pass", "no_hits")
    elif tool_name == "diagnose_db_link":
        # knowledge_context 的内容桶（tools.py 的 _DIM_TO_KC_KEY 映射 + summary）——
        # 全部为空才判「未命中知识」（此前误用 dimensions 键：该键本题材下不存在）
        kc = result.get("knowledge_context")
        if isinstance(kc, dict):
            _buckets = ("common_causes", "recommended_steps", "configuration_checks",
                        "logs_and_tools", "summary")
            if not any(kc.get(k) for k in _buckets):
                gaps.append("无检索到的知识片段（BKN/Qdrant 均未命中）")
                _cp("fail", "no_knowledge")
            else:
                _cp("pass", "no_knowledge")
    elif tool_name == "check_action_risk":
        if result.get("passed") is not None and not result.get("rule_id"):
            gaps.append("未命中任何约束规则（动作未登记或该状态无需约束）")
            _cp("fail", "no_rule")
        else:
            _cp("pass", "no_rule")
    # B5：本节一次都没判 fail → 记一条 pass（回答「partial 是谁判的」时
    # 「不是 deep_check」同样是有效信息）。**只有真跑了本节分支的 Tool 才记**——
    # tool_name 不在下面这四类里等于没跑，不记（避免伪造「deep_check 通过」）。
    if not gaps and tool_name in ("design_solution", "search_qdrant",
                                  "diagnose_db_link", "check_action_risk"):
        _cp("pass", "")
    return gaps


def _count_risks(rels: dict) -> int:
    count = 0
    for entity, relations in rels.items():
        if isinstance(relations, dict):
            risks = relations.get("risks_of", [])
            if isinstance(risks, list):
                count += len(risks)
            elif isinstance(risks, str) and risks.strip():
                count += 1
    return count


def log_gap(tool: str, params: dict, confidence: str, gaps: list[str], extra: dict | None = None,
            task_id: str | None = None):
    """写入一条缺口记录。

    extra: 可选附加字段，合并进 entry 顶层。O-域诊断类闭环用它挂 `classes`——
    gap 因此可按诊断类聚合（见 scripts/scan_gaps.py「按诊断类聚合」段），
    从而产出「『源端日志不可读』类缺口 41 次」这类数据驱动的类扩充依据。
    默认 None = 完全保持原有字段与行为。

    task_id: 批 U-0（2026-10-11）：Hermes 会话标识（**kwargs 通道）。非空才写入条目——
    「会话内缺口」聚合与真假流量分离的依据；缺省（裸调用）保持旧条目形状。
    """
    entry = {
        "tool": tool,
        "params": params,
        "confidence": confidence,
        "gaps": gaps,
        "timestamp": int(time.time()),
        "user_supplied": None,
        "resolved": False,
    }
    if extra:
        entry.update(extra)
    if task_id:  # 批 U-0（2026-10-11）：会话标识；非空才写 → 旧条目形状不变
        entry["task_id"] = task_id
    try:
        # 2026-09-30: 日期+大小双维轮转（同 usage_log），追加写到当日文件
        from .log_rotate import rotate_day_file
        from .config import LOG_ROTATE_GAP_MAX_BYTES, LOG_ROTATE_BACKUPS, LOG_ROTATE_RETENTION_DAYS
        path = rotate_day_file(GAP_LOG_PATH, LOG_ROTATE_GAP_MAX_BYTES, LOG_ROTATE_BACKUPS,
                               retention_days=LOG_ROTATE_RETENTION_DAYS)
        # 目录自愈：基名路径可被 mock.patch.object 换掉，目录可能尚不存在
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning("写入 gap_log 失败: %s", e)


# ========== L2: Qdrant 向量语义检索 ==========

_GAP_KEYWORD_MAP = {
    "风险": "风险 故障 异常 处理 约束",
    "跨地域": "跨地域 异地 远程 网络 延迟 带宽",
    "版本兼容": "版本 兼容性 限制 要求 不支持",
    "数据库特定": "数据库 同步 配置 源端 目标端 兼容性",
    "限制说明": "限制 约束 注意事项 不支持",
    "排查步骤": "排查 步骤 修复 处理 解决方案",
    "修复方案": "修复 处理 解决方案 操作",
    "前置条件": "前置条件 准备工作 环境要求",
    "内容过短": "配置 参数 步骤 操作 注意事项",
    "内容可能不完整": "配置 参数 步骤 注意事项 兼容性",
    "建议查 Qdrant": "配置 参数 操作 步骤 注意事项",
}


def _extract_gap_keywords(gaps: list[str]) -> list[str]:
    keywords = set()
    for gap in gaps:
        for topic, keyword_str in _GAP_KEYWORD_MAP.items():
            if topic in gap:
                for kw in keyword_str.split():
                    keywords.add(kw)
    return sorted(keywords)


def _build_query(args: dict, gaps: list[str] = None) -> str:
    parts = []
    priority_keys = ["source", "target", "error_code", "operation", "topic"]
    for k in priority_keys:
        v = args.get(k)
        if v and isinstance(v, str):
            parts.append(v)
    for k, v in args.items():
        if k not in priority_keys and v and isinstance(v, str):
            parts.append(v)
    if gaps:
        gap_keywords = _extract_gap_keywords(gaps)
        if gap_keywords:
            parts.append(" ".join(gap_keywords))
    return " ".join(parts)


# ── 内容质量过滤: 图片占位符、空内容等 ──

_IMAGE_PLACEHOLDER_PATTERNS = [
    "[嵌入图片:", "[圖片:", "[image:", "[Picture:",
]

# VLM 未识别出内容时的拒答话术（实测样例：`[图片: image40.png]\n由于您没有提供具体的图片内容…`）
_VLM_REFUSAL_PATTERNS = [
    "没有提供具体的图片内容", "无法为您提取", "如果您能上传图片", "无法识别图片",
    "抱歉，我无法", "图片内容为空",
]


def _is_valid_content(text: str) -> bool:
    """过滤无效内容: 图片占位符、纯空白、极短噪声

    21 号 2F：中文 `[图片: xxx.png]` 块是 VLM 识别的产物，**不能整体拉黑**——实测
    700 条 image 块里 661 条（94%）带 `[图片内容]` 正文（p50 292 字）是有效知识；
    真正的失败态只有两类：缺 `[图片内容]` 标记（截断/空），或 VLM 拒答话术。
    故改用失败态判定：前缀是 `[图片:`/`[图片：` 时要求正文有效才放行。
    （不做长度门槛：失败态 23/71 字与成功态下界 24 字完全重叠，设阈值会误杀短描述。）
    """
    text = text.strip()
    if len(text) < 20:
        return False
    for pat in _IMAGE_PLACEHOLDER_PATTERNS:
        if pat in text:
            return False
    if text.startswith(("[图片:", "[图片：")):
        # 必须带 [图片内容] 标记，且标记后有有效正文（排除 VLM 拒答话术）
        marker = "[图片内容]"
        idx = text.find(marker)
        if idx < 0:
            return False
        body = text[idx + len(marker):].strip()
        if not body:
            return False
        if any(refusal in body[:80] for refusal in _VLM_REFUSAL_PATTERNS):
            return False
    return True


def _payload_content(payload: dict) -> str:
    """从 payload 提取优先内容字段 (content > blurb > text)"""
    return (
        payload.get("content")
        or payload.get("blurb")
        or payload.get("text")
        or ""
    )[:600]


# ======================================================================
#  v3.6: Chunk-aware search helpers
# ======================================================================


def _search_chunk_level(
    query: str,
    top_k: int,
    levels: list[str],
    client=None,
    model=None,
    hybrid: bool = True,
    collection: str = None,
) -> list[dict]:
    """按 chunk_level 过滤执行 ANN 搜索，并与全库 BM25 做 RRF 融合。

    Args:
        query: 查询文本
        top_k: 返回条数上限
        levels: chunk_level 白名单，如 ["mini"], ["standard", "image"]
        client: QdrantClient，传 None 时懒加载
        model: Embedding 模型，传 None 时懒加载
        hybrid: 是否启用 BM25 全库搜索 + RRF 融合（默认 True）
        collection: 目标集合（默认 None=主集合 QDRANT_COLLECTION）
    """
    from qdrant_client.http.models import Filter, FieldCondition, MatchAny

    # B1：standard_image / large_only 路由的**检索入口**（嵌套调用只登记、不重复发事件）
    _pc, _ptok = _path_enter()
    if client is None:
        client = _get_qdrant_client()
    if model is None:
        model = _get_embedding_model()

    if client is None or model is None:
        _path_add("bge_dense", 0, stopped="no_client_model")
        _path_exit(_pc, _ptok, [])
        return []

    target_collection = collection or QDRANT_COLLECTION

    # 默认集合强校验维度；自定义集合容忍（旧行为不校验，维度不符由 Qdrant 查询自身报错）
    try:
        _validate_qdrant_dimension(client, target_collection)
    except ValueError:
        if collection is None:
            raise
        _record_init_warning(f"自定义 collection '{target_collection}' 维度校验已跳过")
    emb = model.encode(query).tolist()

    # ── BGE dense 搜索（按 chunk_level 过滤）──
    _t_dense = time.perf_counter()
    _path_query()
    if hasattr(client, "query_points"):
        res = client.query_points(
            collection_name=target_collection,
            query=emb,
            limit=top_k,
            score_threshold=SEARCH_SCORE_THRESHOLD,
            query_filter=Filter(
                must=[FieldCondition(key="chunk_level", match=MatchAny(any=levels))]
            ),
        )
        points = res.points
    elif hasattr(client, "search"):
        res = client.search(
            collection_name=target_collection,
            query_vector=emb,
            limit=top_k,
            score_threshold=SEARCH_SCORE_THRESHOLD,
            query_filter=Filter(
                must=[FieldCondition(key="chunk_level", match=MatchAny(any=levels))]
            ),
        )
        points = res
    else:
        _path_add("bge_dense", 0, t0=_t_dense, stopped="no_api")
        _path_exit(_pc, _ptok, [])
        return []

    dense_hits = []
    for r in points:
        payload = r.payload or {}
        content = _payload_content(payload)
        if not _is_valid_content(content):
            continue
        dense_hits.append({
            "content": content,
            "score": round(r.score, 4) if hasattr(r, "score") and r.score else 0.0,
            "source": payload.get("document_id", ""),
            "id": r.id if hasattr(r, "id") else str(r.id),
            "chunk_id": payload.get("chunk_id"),
            "chunk_level": payload.get("chunk_level"),
            "title": payload.get("title", ""),
            "large_chunk_id": payload.get("large_chunk_id"),
            "section_type": payload.get("section_type", "text"),
            "image_file_id": payload.get("image_file_id"),
            "parent_chunk_id": payload.get("parent_chunk_id"),
            "parent_document_id": payload.get("parent_document_id"),
            "mini_chunk_index": payload.get("mini_chunk_index"),
            "blurb": payload.get("blurb", ""),
        })
    _path_add("bge_dense", dense_hits, t0=_t_dense,
              stopped="hit_enough" if dense_hits else "no_hit")

    # ── v3.7: 精度保护 — 查询含精确项(错误码)但 BGE 结果不含时, 合并 BM25 兜底 ──
    # 21 号 2E: 必须传 target_collection——本函数自己的 BM25（L583）已按集合走，
    # guard 若不传就会把默认主集合的命中混进指定集合的检索（实测跨集合污染）。
    if hybrid:
        pg_hits = _precision_guard_fallback(query, dense_hits, top_k,
                                            collection=target_collection)
        if pg_hits:
            seen_ids = {h.get("id") for h in dense_hits}
            for h in pg_hits:
                if h.get("id") not in seen_ids:
                    h["_guard"] = True  # 21 号 2F: 标记改独立字段，不再污染 source
                    dense_hits.insert(0, h)
                    seen_ids.add(h["id"])

    # ── BM25 全库搜索 + RRF 融合（不过滤 chunk_level）──
    if hybrid:
        try:
            from .bm25 import bm25_search, rrf_fusion
            _t_bm25 = time.perf_counter()
            _path_query()
            sparse_hits = bm25_search(query, top_k=top_k * 2, collection=target_collection)
            if sparse_hits:
                merged = rrf_fusion(dense_hits, sparse_hits, top_k=top_k)
                for h in merged:
                    h["rrf_score"] = h.get("rrf_score")  # rrf_fusion 已写入，保序透传
                _path_add("bm25_rrf", merged, t0=_t_bm25, stopped="hit_enough")
                _path_exit(_pc, _ptok, merged)
                return merged
            _path_add("bm25_rrf", 0, t0=_t_bm25, stopped="no_hit")
        except ImportError:
            _path_add("bm25_rrf", 0, stopped="no_bm25")
            logger.debug("BM25 模块未安装，跳过 RRF 融合")

    _out = dense_hits[:top_k]
    _path_exit(_pc, _ptok, _out)
    return _out


def _resolve_standard_batch(mini_hits: list[dict], client=None, collection: str = None) -> dict:
    """批量反查 standard 父块。

    输入: mini 命中列表
    输出: {(document_id, chunk_id): standard_payload}（payload 附 `_point_id`）

    21 号 2G：由「逐 parent 单点 scroll」（10 parent ≈ 370ms、40 parent ≈ 1.65s）
    改为**单次批量 scroll**（chunk_id MatchAny + 客户端 pair 过滤，10/40 parent 均
    44-87ms，等价性已实测）——这是 34 号「已知性能点」预留的优化方向，实测延迟
    已达其写明的重评条件。见 34 号 §已知性能点 与 21 号 §8.8。
    """
    from qdrant_client.http.models import Filter, FieldCondition

    _t0 = time.perf_counter()   # B1：standard_batch 段计时
    if client is None:
        client = _get_qdrant_client()
    if client is None:
        _path_add("standard_batch", 0, t0=_t0, stopped="no_client")
        return {}

    target_collection = collection or QDRANT_COLLECTION

    parent_keys = set()
    for h in mini_hits:
        pid = h.get("parent_chunk_id")
        pdid = h.get("parent_document_id")
        if pid is not None and pdid:
            parent_keys.add((pdid, pid))

    if not parent_keys:
        _path_add("standard_batch", 0, t0=_t0, stopped="no_parent")
        return {}

    # 单次批量 scroll（分页取全）：chunk_id MatchAny 覆盖全部候选父块，
    # chunk_id 可跨文档重复 → 取回后按 (document_id, chunk_id) pair 客户端过滤
    # v1.7: standard 层级匹配含 log_pattern_standard（日志模式库的 standard 块命名）
    from qdrant_client.http.models import MatchAny as _MatchAny
    standards = {}
    chunk_ids = [pid for _, pid in parent_keys]
    want = {(doc_id, chunk_id) for doc_id, chunk_id in parent_keys}
    offset = None
    _path_query()   # B1：一次批量 scroll = 一次检索请求
    from .bm25 import PATTERN_META_KEYS   # 唯一口径（勿再抄键清单）
    while True:
        pts, offset = client.scroll(
            collection_name=target_collection,
            limit=max(32, len(chunk_ids)),
            offset=offset,
            with_payload=[
                "content", "mini_chunk_texts", "mini_chunk_offsets",
                "mini_chunk_count", "chunk_id", "document_id",
                "title", "large_chunk_id", "section_type", "blurb",
            ] + list(PATTERN_META_KEYS),
            with_vectors=False,
            scroll_filter=Filter(must=[
                FieldCondition(key="chunk_level",
                               match=_MatchAny(any=["standard", "log_pattern_standard"])),
                FieldCondition(key="chunk_id",
                               match=_MatchAny(any=chunk_ids)),
            ]),
        )
        for p in pts:
            payload = p.payload or {}
            key = (payload.get("document_id"), payload.get("chunk_id"))
            if key not in want:
                continue  # 同 chunk_id 的其它文档块，不属于本批 parent
            if key in standards:
                continue
            # 21 号 2F：回填点 ID 作稳定去重键（(source, chunk_id) 会因标记覆写/字段缺失塌缩）
            payload["_point_id"] = str(p.id)
            standards[key] = payload
        if offset is None:
            break

    _path_add("standard_batch", standards, t0=_t0,
              stopped="hit_enough" if standards else "no_hit")
    return standards


def _make_hit_mini(mh: dict, sp: dict) -> dict:
    """从 mini hit 和 standard payload 组装 hit_mini 信息。"""
    mi = mh.get("mini_chunk_index", 0)
    offsets = sp.get("mini_chunk_offsets", []) or []
    texts = sp.get("mini_chunk_texts", []) or []
    return {
        "index": mi,
        "text": texts[mi] if isinstance(texts, list) and mi < len(texts) else "",
        "offset": offsets[mi] if isinstance(offsets, list) and mi < len(offsets) else None,
    }


def _search_mini_first(
    query: str,
    top_k: int,
    client=None,
    model=None,
    collection: str = None,
) -> list[dict]:
    """mini-first 策略：mini ANN → standard 回源 → 偏移标注 → fallback standard。"""
    # B1：mini_first 路由的**检索入口**（嵌套调用只登记、不重复发事件）
    _pc, _ptok = _path_enter()
    if client is None:
        client = _get_qdrant_client()
    if model is None:
        model = _get_embedding_model()

    if client is None or model is None:
        _path_exit(_pc, _ptok, [])
        return []

    # Phase 1: mini ANN（带 BM25 全库 RRF），取 top_k * 2
    _t_mini = time.perf_counter()
    all_hits = _search_chunk_level(
        query, top_k * MINI_FIRST_TOP_K_MULTIPLIER, ["mini"],
        client=client, model=model, hybrid=True, collection=collection,
    )

    # 分离 BGE 命中的 mini 与 BM25 带来的其他层结果
    mini_hits = [h for h in all_hits if h.get("chunk_level") == "mini"]
    other_hits = [h for h in all_hits if h.get("chunk_level") != "mini"]
    # B1：本段的「命中数」取 **mini 层命中**（驱动 Phase2 回源的那批），不是 all_hits 全量
    _path_add("mini_first", mini_hits, t0=_t_mini,
              stopped="hit_enough" if mini_hits else "no_hit")

    if not mini_hits:
        # Fallback: 直接搜 standard（hybrid=True 保留 BM25 补充）
        _fb = _search_chunk_level(
            query, top_k, ["standard"], client=client, model=model, hybrid=True,
            collection=collection,
        )
        _path_exit(_pc, _ptok, _fb)
        return _fb

    # Phase 2: 批量反查 standard
    standards = _resolve_standard_batch(mini_hits, client=client, collection=collection)

    # Phase 3: 组装 mini→standard 结果并去重
    # 21 号 2F：去重键改用点 ID（_key）——原 (source, chunk_id) 会因 source 被检索标记
    # 覆写成同值字符串、且 BM25 条目无 chunk_id 而塌缩成单个键，静默丢弃同类全部条目。
    result_map = {}
    for mh in mini_hits:
        key = (mh.get("parent_document_id"), mh.get("parent_chunk_id"))
        if key not in standards:
            continue
        sp = standards[key]
        rkey = sp.get("_point_id") or f"std::{key[0]}::{key[1]}"
        if rkey in result_map:
            result_map[rkey]["hit_mini"].append(_make_hit_mini(mh, sp))
            continue

        result_map[rkey] = {
            "content": sp.get("content", ""),
            "score": mh.get("score", 0),
            # 21 号 2F：携带父块排序键 = 命中它的 mini 的 rrf_score（原实现丢弃，
            # 导致全局排序没有跨尺度可用键）
            "rrf_score": mh.get("rrf_score"),
            "_key": rkey,
            "source": sp.get("document_id", ""),
            "title": sp.get("title", ""),
            "chunk_id": sp.get("chunk_id"),
            "chunk_level": sp.get("chunk_level", "standard"),
            "section_type": sp.get("section_type", "text"),
            "large_chunk_id": sp.get("large_chunk_id"),
            "blurb": sp.get("blurb", ""),
            "hit_mini": [_make_hit_mini(mh, sp)],
            "mini_chunk_count": sp.get("mini_chunk_count", 0),
            "retrieval_path": ["dense"] + (["bm25"] if mh.get("rrf_score") else []),
        }
        # 模式库 payload 字段透传（log_patterns_collection，v1.7）
        from .bm25 import PATTERN_META_KEYS
        for _f in PATTERN_META_KEYS:
            if sp.get(_f) is not None:
                result_map[rkey][_f] = sp[_f]

    # Phase 4: 合并 BM25 带来的其它层命中（仅搜 mini 可能遗漏的内容）
    # 21 号 2F：原实现直接放行 BM25 原始字典 → ① 与 Phase3 条目共用 (source, chunk_id)
    # 塌缩键而丢结果；② 交付的是 BM25 原始块（可能是 mini/image/large 原文），
    # 违背 mini_first「只交付父 standard 块」契约。现按真实 chunk_level 解析交付块。
    phase4 = _resolve_delivery_hits(other_hits, mini_hits, standards,
                                   client=client, collection=collection)
    for h in phase4:
        rkey = h.get("_key")
        if rkey and rkey not in result_map:
            result_map[rkey] = h

    # 21 号 2F：统一 RRF 量纲排序（原 sorted(key=score) 混三种量纲——RRF 独中无 score
    # 取 0 沉底、guard 条目 score 是 BM25 值（2~10）霸榜压过余弦 0.3）
    results = sorted(result_map.values(), key=_rank_key, reverse=True)

    # Phase 5: 数量不足时补充 standard
    if len(results) < top_k:
        existing_ids = {h.get("_key") for h in results}
        std_hits = _search_chunk_level(
            query, top_k - len(results), ["standard"],
            client=client, model=model, hybrid=True, collection=collection,
        )
        for h in std_hits:
            # 21 号 2F：与 result_map 同用点 ID 作去重键（原 (source, chunk_id) 会漏判重复）
            if _hit_key(h) not in existing_ids:
                results.append(h)

    _out = results[:top_k]
    _path_exit(_pc, _ptok, _out)
    return _out


def _hit_key(hit: dict) -> str:
    """检索命中的稳定标识：优先点 ID，回落 (source, chunk_id) 组合键。

    21 号 2F：原用 (source, chunk_id) 作去重键，而 `source` 会被检索标记覆写成
    同值字符串、BM25 命中又缺 chunk_id → 键塌缩成单个值，`if key not in result_map`
    只放行第一条，其余同类条目被静默丢弃（实测 -4073 查询 10 条只活 3 条）。
    """
    if hit.get("_key"):
        return hit["_key"]
    hid = hit.get("_point_id") or hit.get("id")
    if hid:
        return f"pt::{hid}"
    return f"sc::{hit.get('source')}::{hit.get('chunk_id')}"


def _rank_key(hit: dict) -> float:
    """全局排序键（21 号 2F：统一 RRF 量纲）。

    原实现 `sorted(key=x.get("score", 0))` 混了三种量纲，同时造成两种错位：
    RRF 独中项没有 `score` → 取 0 沉底（哪怕它全库唯一咬中该错误码）；
    precision guard 条目把 `score` 设成 BM25 原值（2~10）→ 霸榜压过余弦 0.3 的父块。
    RRF 分本身是排名倒数和（0~0.033），天然跨尺度，故优先用它；纯 dense 路径
    （hybrid=False）无 rrf_score 时回落 score。
    """
    rrf = hit.get("rrf_score")
    if rrf:
        return float(rrf)
    score = hit.get("score")
    return float(score) if score else 0.0


# BM25 独中项的交付块解析（21 号 2F）
# 与 mini_first 的「只交付父 standard 块」契约对齐：mini → 父块；其余层级取自身。
_DELIVERY_LAYERS = {"standard", "log_pattern_standard", "image", "large"}


def _resolve_delivery_hits(other_hits: list[dict], mini_hits: list[dict],
                           standards: dict, client=None,
                           collection: str = None) -> list[dict]:
    """把 Phase1 的非 mini 命中解析为「该交付的块」。

    - mini 层命中（BM25 咬中的 mini 块）→ 复用 Phase3 已解析的父块；未覆盖的
      合并 parent_keys **一次**反查（不额外增加 scroll 轮次）；
    - standard / log_pattern_standard / image / large → 取自身（已是交付层）；
    - 其它/未知层级 → 跳过（无法确定交付形态，宁缺勿错）。
    """
    delivery: list[dict] = []
    unresolved: list[dict] = []
    for oh in other_hits:
        lvl = oh.get("chunk_level")
        if lvl == "mini":
            unresolved.append(oh)
        elif lvl in _DELIVERY_LAYERS:
            delivery.append(_deliver_self(oh))
        # 未知层级不进交付（原实现直接放行原始字典，可能交付任意层级原文）

    if unresolved:
        extra_standards = dict(standards)
        unseen = [h for h in unresolved
                  if (h.get("parent_document_id"), h.get("parent_chunk_id")) not in extra_standards]
        if unseen:
            extra_standards.update(
                _resolve_standard_batch(unseen, client=client, collection=collection))
        for oh in unresolved:
            sp = extra_standards.get((oh.get("parent_document_id"), oh.get("parent_chunk_id")))
            if sp:
                delivery.append(_assemble_parent_hit(oh, sp))
            else:
                # 父块反查不到：降级交付自身，但显式标注（不静默丢）
                delivery.append(_deliver_self(oh, fallback_reason="parent_unresolved"))
    return delivery


def _deliver_self(hit: dict, fallback_reason: str = None) -> dict:
    """以自身作为交付块（standard/image/large 层，或父块不可解析时的降级）。"""
    out = dict(hit)
    out["_key"] = _hit_key(hit)
    path = ["bm25"] if hit.get("bm25_score") is not None else []
    if hit.get("rrf_score"):
        path = ["dense", "bm25"]
    if hit.get("_fallback_reason"):
        path.append("guard")
    if hit.get("_exact_match"):
        path.append("exact")
    _path_count_delivered("self")   # B1：`delivered.self`
    out["retrieval_path"] = path
    if fallback_reason:
        out["_fallback_reason_delivery"] = fallback_reason
    return out


def _assemble_parent_hit(mh: dict, sp: dict) -> dict:
    """BM25 咬中的 mini 块 → 组装父 standard 交付（与 Phase3 同构）。"""
    out = {
        "content": sp.get("content", ""),
        "score": mh.get("score"),
        "rrf_score": mh.get("rrf_score"),
        "bm25_score": mh.get("bm25_score"),
        "_key": sp.get("_point_id") or _hit_key(mh),
        "source": sp.get("document_id", ""),
        "title": sp.get("title", ""),
        "chunk_id": sp.get("chunk_id"),
        "chunk_level": sp.get("chunk_level", "standard"),
        "section_type": sp.get("section_type", "text"),
        "large_chunk_id": sp.get("large_chunk_id"),
        "blurb": sp.get("blurb", ""),
        "hit_mini": [_make_hit_mini(mh, sp)],
        "mini_chunk_count": sp.get("mini_chunk_count", 0),
        "retrieval_path": ["bm25", "mini->parent"],
    }
    from .bm25 import PATTERN_META_KEYS
    for _f in PATTERN_META_KEYS:
        if sp.get(_f) is not None:
            out[_f] = sp[_f]
    _path_count_delivered("parent")   # B1：`delivered.parent`
    return out


def _expand_parents(hits: list[dict], client=None, collection: str = None) -> list[dict]:
    """为标准块/mini 命中补充父大块的 title 信息（parent_expand 模式）。

    注意：当前仅返回 title，不返回 large content。doc_summary 预留为空字符串。
    """
    from qdrant_client.http.models import Filter, FieldCondition, MatchAny, MatchValue

    if client is None:
        client = _get_qdrant_client()
    if client is None:
        return hits

    lc_ids = {h.get("large_chunk_id") for h in hits if h.get("large_chunk_id") is not None}
    if not lc_ids:
        return hits

    parents = {}
    all_parents, _ = client.scroll(
        collection_name=collection or QDRANT_COLLECTION,
        limit=len(lc_ids) * PARENT_EXPAND_LIMIT_MULTIPLIER,
        with_payload=["title", "large_chunk_id"],  # 不取 content，先不返回 large content
        with_vectors=False,
        scroll_filter=Filter(must=[
            FieldCondition(key="chunk_level", match=MatchValue(value="large")),
            FieldCondition(key="large_chunk_id", match=MatchAny(any=list(lc_ids))),
        ]),
    )
    for p in all_parents:
        payload = p.payload or {}
        pid = payload.get("large_chunk_id")
        if pid and pid not in parents:
            parents[pid] = {
                "title": payload.get("title", ""),
            }

    for h in hits:
        lc_id = h.get("large_chunk_id")
        h["_parent"] = {
            "large_chunk_id": lc_id,
            "title": parents[lc_id]["title"] if lc_id in parents else "",
            "doc_summary": "",  # 当前全空，预留字段
        } if lc_id is not None else None

    return hits


# ── v3.4: BGE precision guard ──

_EXACT_TERM_PATTERNS = [
    # 负号 4 位数字 = 强错误码信号 (-4002, -4073)
    # 使用显式字符类 [0-9] 替代 \d, 兼容底层 re 分类异常的 Python 构建
    (r'(?<![0-9])-[0-9]{4}(?![0-9])', 'error_code'),
    # ORA 错误
    (r'(?<![a-zA-Z0-9_])ORA-[0-9]{5}(?![a-zA-Z0-9_])', 'ora_error'),
]


def _extract_exact_terms(query: str) -> list[str]:
    """从查询中提取精确匹配项: 错误码、ORA 错误等

    v3.4.1: 仅匹配负号 4 位数字 (-4002) 和 ORA-XXXXX。
    普通 4 位数字 (端口/年份/参数) 不触发, 避免噪声。"""
    # 84 号：由 code_rows 驱动（支持裸码/5 位/ORA|YAS 前缀 + 侧车校验 + 上下文放行）。
    from .code_rows import extract_code_mentions
    return [m["canonical"] for m in extract_code_mentions(query)]


def _any_hit_contains_term(hits: list[dict], terms: list[str]) -> bool:
    """检查任意一条 hit 的内容是否包含任一精确项"""
    if not terms:
        return True  # 无精确项, 视为通过
    for h in hits:
        content = h.get("content", "")
        for term in terms:
            variants = {term}
            if term.startswith("-") and term[1:].isdigit():
                variants.add(term[1:])
            for v in variants:
                # 边界感知：14017 / 40170 不得命中 4017
                if re.search(r"(?<![0-9A-Za-z_-])" + re.escape(v) + r"(?![0-9])",
                             content, re.IGNORECASE):
                    return True
    return False


def _search_content_exact(terms: list[str], top_k: int = 5,
                          collection: str = None) -> list[dict]:
    """内容级字符串匹配: 绕过 tokenizer 分词问题

    v3.5: 优先使用 BM25 exact-term 倒排索引, 避免全量 content_cache 扫描。
    对错误码尝试去横杠变体 (如 "-4002" → 也搜 "4002")。

    21 号 2E：`collection` 决定用哪个集合的索引（None = 主集合）——此前恒用主集合，
    导致指定集合的精确项检索打出别的集合的内容（实测见 21 号 §8.6）。
    """
    _t0 = time.perf_counter()   # B1：content_exact 段计时
    _path_query()
    from .bm25 import get_bm25_index
    idx = get_bm25_index(collection=collection)
    if not idx:
        _path_add("content_exact", 0, t0=_t0, stopped="no_index")
        return []
    content_cache = getattr(idx, "_content_cache", {})
    if not content_cache:
        _path_add("content_exact", 0, t0=_t0, stopped="no_cache")
        return []

    # 扩展变体: -4002 → 也搜 4002
    search_terms = list(terms)
    for t in terms:
        if t.startswith('-') and t[1:].isdigit():
            search_terms.append(t[1:])

    exact_index = getattr(idx, "_exact_index", None)
    candidate_ids = set()
    use_index = exact_index and any(t in exact_index for t in search_terms)
    if use_index:
        for t in search_terms:
            candidate_ids.update(exact_index.get(t, set()))
    else:
        # 索引不存在或查无术语时回退全量扫描
        candidate_ids = set(content_cache.keys())

    seen_content = set()
    matches = []
    meta_cache = getattr(idx, "_meta_cache", {})
    for doc_id in candidate_ids:
        content = content_cache.get(doc_id, "")
        if not content:
            continue
        matched = sum(1 for t in search_terms if t in content)
        if matched > 0:
            ckey = content[:200]
            if ckey in seen_content:
                continue
            seen_content.add(ckey)
            meta = dict(meta_cache.get(doc_id, {}))  # 21 号 2F: 元数据同源回传
            meta.update({
                "id": doc_id,
                "content": content,
                "bm25_score": float(matched),
                "source": meta.get("document_id", ""),
                "_exact_match": True,
            })
            matches.append(meta)
    matches.sort(key=lambda x: x["bm25_score"], reverse=True)
    _out = matches[:top_k]
    _path_add("content_exact", _out, t0=_t0,
              stopped="hit_enough" if _out else "no_hit")
    return _out


def _precision_guard_fallback(
    query: str,
    dense_hits: list[dict],
    top_k: int,
    exact_terms: list[str] = None,
    collection: str = None,
) -> list[dict] | None:
    """v3.7: 精度保护 — 当 BGE 结果不含精确项(错误码)时, content_exact + BM25 两路合并兜底。

    共享逻辑, 供 search_qdrant() 和 _search_chunk_level() 复用。
    返回 fallback hits 列表, 或 None (无需 guard / 未触发)。

    21 号 2E：`collection` 必须与调用方的 dense 检索同集合（None = 主集合）——
    exact 索引与 BM25 都要打同一集合，否则兜底结果会跨集合污染。"""
    _t0 = time.perf_counter()   # B1：precision_guard_fallback 段计时
    if not SEARCH_BM25_PRECISION_GUARD:
        _path_add("precision_guard_fallback", 0, t0=_t0, stopped="disabled")
        return None
    bge_failed = not dense_hits or all(
        h.get("score", 0) < SEARCH_BM25_FALLBACK_SCORE for h in dense_hits
    )
    if exact_terms is None:
        exact_terms = _extract_exact_terms(query)
    precision_fail = False
    if not bge_failed and dense_hits and exact_terms:
        if not _any_hit_contains_term(dense_hits, exact_terms):
            precision_fail = True
    if not (bge_failed or precision_fail):
        _path_add("precision_guard_fallback", 0, t0=_t0, stopped="not_triggered")
        return None
    try:
        from .bm25 import bm25_search
    except ImportError:
        _path_add("precision_guard_fallback", 0, t0=_t0, stopped="no_bm25")
        logger.debug("BM25 模块未安装，跳过 precision guard")
        return None
    _path_query()   # B1：guard 兜底发出的一次 BM25 检索
    if precision_fail and exact_terms:
        exact_hits = _search_content_exact(exact_terms, top_k=top_k, collection=collection)
        targeted = " ".join(exact_terms)
        bm25_hits = bm25_search(targeted, top_k=top_k, collection=collection)
        seen_ids = {h["id"] for h in exact_hits}
        fallback_hits = list(exact_hits)
        for h in bm25_hits:
            if h["id"] not in seen_ids:
                fallback_hits.append(h)
                seen_ids.add(h["id"])
        fallback_hits = fallback_hits[:top_k]
    else:
        fallback_hits = bm25_search(query, top_k=top_k, collection=collection)
    if not fallback_hits:
        _path_add("precision_guard_fallback", 0, t0=_t0, stopped="no_hit")
        return []
    # 21 号 2F：把 BM25 量纲的 score 折算成 RRF 量纲（1/(k+rank)，与 rrf_fusion 同公式）——
    # 原实现直接 h["score"] = bm25_score（2~10），在全局排序里霸榜压过余弦 0.3 的 dense 父块。
    for rank, h in enumerate(fallback_hits, start=1):
        h["score"] = round(h.get("bm25_score") or 0.0, 4)
        h["rrf_score"] = round(1.0 / (60 + rank), 4)
        if not _is_valid_content(h.get("content", "")):
            continue
        h["source"] = h.get("source") or ""  # 21 号 2F: source 已是 document_id，不再拼标记
        h["_fallback_reason"] = (
            "BGE precision fail" if precision_fail
            else "BGE returned 0 results" if not dense_hits
            else f"BGE all scores < {SEARCH_BM25_FALLBACK_SCORE}"
        )
    _out = [h for h in fallback_hits if h.get("_fallback_reason")]
    _path_add("precision_guard_fallback", _out, t0=_t0,
              stopped="hit_enough" if _out else "no_hit")
    return _out


def search_qdrant(query: str, top_k: int = None, hybrid: bool = True,
                  collection: str = None) -> list[dict]:
    """Qdrant 向量检索 (v2.1: query_points + 图片占位符过滤; v3.3: BGE miss→BM25 fallback; v3.4: BGE precision guard)

    优先使用 client.query_points() (兼容新旧版本 qdrant-client)。
    失败时 fallback 到 REST scroll + 模型本地编码过滤。
    v3.3: 当所有 dense hit score < SEARCH_BM25_FALLBACK_SCORE 时, 跳过 RRF 直接返回 BM25-only。
    v3.4: 当查询含精确项(-4002/ORA-00001)但 BGE 结果不含时, 触发 content_exact+BM25 两路合并。
    批 6-3（诊断方向层）：collection 参数——`store:` 检索源方向可指定集合（如
    store:log_patterns_collection），默认 None = 主集合（QDRANT_COLLECTION，向后兼容）。"""
    # B1：auto / parent_expand 路由的**检索入口**（一个决策点一条事件，出口统一发）
    _pc, _ptok = _path_enter()
    if top_k is None:
        top_k = SEARCH_TOP_K
    if collection is None:
        collection = QDRANT_COLLECTION

    client = _get_qdrant_client()
    model = _get_embedding_model()

    # ── 路径1: 有 client + 有 model → query_points 语义搜索 ──
    if client and model:
        try:
            _t_dense = time.perf_counter()
            _validate_qdrant_dimension(client, collection)
            emb = model.encode(query).tolist()
            # qdrant-client >=1.9: query_points; <1.9: search (可能不存在)
            _path_query()
            if hasattr(client, "query_points"):
                res = client.query_points(
                    collection_name=collection,
                    query=emb,
                    limit=top_k,
                    score_threshold=SEARCH_SCORE_THRESHOLD,
                )
                points = res.points
            elif hasattr(client, "search"):
                res = client.search(
                    collection_name=collection,
                    query_vector=emb,
                    limit=top_k,
                    score_threshold=SEARCH_SCORE_THRESHOLD,
                )
                points = res
            else:
                raise NotImplementedError("No query_points or search method")
            dense_hits = []
            for r in points:
                content = _payload_content(r.payload or {})
                if not _is_valid_content(content):
                    continue
                dense_hits.append({
                    "content": content,
                    "score": round(r.score, 4) if hasattr(r, "score") and r.score else 0.0,
                    "source": (r.payload or {}).get("document_id", ""),
                    "id": r.id if hasattr(r, "id") else str(r.id),
                    # 21 号 2F: dense 侧也带层级元数据（下游交付块解析/分类需要）
                    "chunk_level": (r.payload or {}).get("chunk_level"),
                    "chunk_id": (r.payload or {}).get("chunk_id"),
                    "title": (r.payload or {}).get("title", ""),
                })
            _path_add("bge_dense", dense_hits, t0=_t_dense,
                      stopped="hit_enough" if dense_hits else "no_hit")
            # ── v3.7: 精度保护 (复用 _precision_guard_fallback) ──
            # 21 号 2E: 传 collection，且空结果不得丢弃 dense（见下）
            if hybrid:
                pg_hits = _precision_guard_fallback(query, dense_hits, top_k,
                                                    collection=collection)
                # 真值判断：guard 在「精确项全局无匹配」时返回 []（L933），
                # `is not None` 会让该查询直接返回空、丢掉全部正确的 dense 命中（21 号 2E 修复；
                # _search_chunk_level 一直用的是真值判断，此处与之对齐）
                if pg_hits:
                    _path_exit(_pc, _ptok, pg_hits)
                    return pg_hits
            if hybrid and dense_hits:
                try:
                    from .bm25 import bm25_search, rrf_fusion
                    _t_bm25 = time.perf_counter()
                    _path_query()
                    sparse_hits = bm25_search(query, top_k=top_k * 2, collection=collection)
                    if sparse_hits:
                        merged = rrf_fusion(dense_hits, sparse_hits, top_k=top_k)
                        # 21 号 2F：检索标记不再拼进 source（source 保持纯 document_id），
                        # rrf_fusion 已写入 rrf_score 供下游排序
                        _path_add("bm25_rrf", merged, t0=_t_bm25, stopped="hit_enough")
                        _path_exit(_pc, _ptok, merged)
                        return merged
                    _path_add("bm25_rrf", 0, t0=_t_bm25, stopped="no_hit")
                except ImportError:
                    _path_add("bm25_rrf", 0, stopped="no_bm25")
                    logger.debug("BM25 模块未安装，跳过 RRF 融合")
            _path_exit(_pc, _ptok, dense_hits)
            return dense_hits
        except Exception as e:
            # 记录降级原因后继续走 REST scroll fallback, 不吞掉异常信息
            msg = str(e).lower()
            if "dimension" in msg:
                _record_init_warning(f"向量维度不匹配: {e}")
                _fall_stop = "error_dimension"
            elif "connection" in msg or "connect" in msg:
                _record_init_warning(f"Qdrant 连接失败: {e}")
                _fall_stop = "error_connection"
            else:
                _record_init_warning(f"Qdrant 查询失败: {e}")
                _fall_stop = "error_query"
            _path_add("bge_dense", 0, t0=_t_dense, stopped=_fall_stop)

    # ── 路径2: 无 client/model 或异常 → REST scroll + 模型过滤 ──
    _fb = _fallback_scroll_with_filter(query, top_k, model, collection=collection)
    _path_exit(_pc, _ptok, _fb)
    return _fb


def _fallback_scroll_with_filter(query: str, top_k: int, model=None,
                               collection: str = None) -> list[dict]:
    """REST scroll + 可选模型重排序 + 图片占位符过滤（批 6-3：collection 透传）"""
    _t0 = time.perf_counter()   # B1：fallback_scroll_with_filter 段计时
    results = _fallback_scroll_raw(top_k * 3, collection=collection)  # 多取些供过滤
    if not results:
        _path_add("fallback_scroll_with_filter", 0, t0=_t0, stopped="no_hit")
        return []

    # 如果模型可用，用余弦相似度重排序
    if model:
        try:
            import numpy as np
            q_emb = np.array(model.encode(query))
            for h in results:
                content = h.get("content", "")
                if content and len(content) >= 20:
                    c_emb = np.array(model.encode(content))
                    cos = np.dot(q_emb, c_emb) / (
                        np.linalg.norm(q_emb) * np.linalg.norm(c_emb) + 1e-8
                    )
                    h["score"] = round(float(cos), 4)
            results.sort(key=lambda x: x.get("score", 0), reverse=True)
        except Exception as e:
            for h in results:
                h["_fallback_reason"] = f"模型重排序失败, 返回未排序结果: {e}"

    _out = results[:top_k]
    _path_add("fallback_scroll_with_filter", _out, t0=_t0,
              stopped="hit_enough" if _out else "no_hit")
    return _out


def _fallback_scroll_raw(limit: int, collection: str = None) -> list[dict]:
    """REST API scroll + 内容质量过滤（批 6-3：collection 透传）"""
    if collection is None:
        collection = QDRANT_COLLECTION
    _t0 = time.perf_counter()   # B1：fallback_scroll_raw 段计时
    _stop = "no_hit"
    try:
        import requests
        _path_query()
        resp = requests.post(
            f"http://{QDRANT_HOST}:{QDRANT_PORT}/collections/{collection}/points/scroll",
            json={"limit": limit, "with_payload": True, "with_vector": False},
            timeout=QDRANT_TIMEOUT,
        )
        if resp.status_code == 200:
            points = resp.json().get("result", {}).get("points", [])
            hits = []
            for p in points:
                payload = p.get("payload", {})
                content = _payload_content(payload)
                if not _is_valid_content(content):
                    continue
                hits.append({
                    "content": content,
                    "score": 0.0,
                    "source": payload.get("document_id", payload.get("source", "")),
                    "id": p.get("id", ""),
                })
            _path_add("fallback_scroll_raw", hits, t0=_t0,
                      stopped="hit_enough" if hits else "no_hit")
            return hits
        else:
            _stop = "http_error"
            _record_init_warning(f"Qdrant REST scroll 返回 HTTP {resp.status_code}")
    except Exception as e:
        _stop = "error"
        _record_init_warning(f"Qdrant REST scroll 失败: {e}")
    _path_add("fallback_scroll_raw", 0, t0=_t0, stopped=_stop)
    return []


# ======================================================================
#  v2.0: 多维度查询分解 + 聚合
# ======================================================================

# ── 分维度查询模板: 每个 Tool 类型对应一组子查询生成规则 ──

_DECOMPOSE_TEMPLATES = {
    "design_solution": [
        ("字符集/类型映射", lambda s, t: f"{s}到{t} 字符集转换 数据类型映射 字段长度 注意事项"),
        ("全量同步参数",    lambda s, t: f"全量同步 大表拆分 导出线程 装载线程 表覆盖策略 单表拆分"),
        ("增量/日志解析",   lambda s, t: f"{s} 增量同步 日志解析 CDC 配置要求"),
        ("断点续传/容错",   lambda s, t: f"断点续传 checkpoint LSN 中断恢复 错误处理 冲突处理"),
        ("数据校验/对比",   lambda s, t: f"数据校验 整库对比 表对比 一致性检查 差异修复"),
        ("源端特定配置",    lambda s, t: f"{s} 数据库配置 编目 编码 环境要求 Demo Product部署"),
        ("目标端特定配置",  lambda s, t: f"{t} 同步 配置 字符集 用户授权 环境要求"),
        ("跨地域/网络优化", lambda s, t: f"跨地域 异地同步 网络优化 压缩 带宽 延迟 批量提交"),
        ("风险/异常处理",   lambda s, t: f"{s} {t} 同步 风险 异常 常见错误 故障排查"),
    ],
    "check_compatibility": [
        ("源端版本要求",    lambda s, t: f"{s} 版本要求 兼容性 Demo Product支持"),
        ("目标端配置要求",  lambda s, t: f"{t} 配置要求 兼容性 前置条件"),
        ("数据类型映射",    lambda s, t: f"{s}到{t} 数据类型 不兼容对象 限制"),
    ],
    "diagnose_error": [
        ("错误原因",        lambda ec, _: f"错误码{ec} 原因 异常 触发条件"),
        ("修复步骤",        lambda ec, _: f"错误码{ec} 修复 处理 解决方案"),
        ("操作约束",        lambda ec, _: f"错误码{ec} 操作约束 前置条件 注意事项"),
    ],
    "explain_architecture": [
        ("原理机制",        lambda topic, _: f"Demo Product {topic} 原理 机制 架构"),
        ("配置调优",        lambda topic, _: f"Demo Product {topic} 配置 调优 参数 性能"),
        ("异常场景",        lambda topic, _: f"Demo Product {topic} 异常 故障 排查"),
    ],
    "get_prerequisites": [
        ("环境要求",        lambda op, _: f"{op} 环境要求 前置条件"),
        ("权限配置",        lambda op, _: f"{op} 权限 授权 用户"),
        ("参数验证",        lambda op, _: f"{op} 配置 参数 验证"),
    ],
    "query_product": [
        ("产品定位",        lambda a, _: f"Demo Product 产品定位 核心能力 {a}"),
        ("行业覆盖",        lambda a, _: f"Demo Product 行业 场景 {a}"),
        ("信创适配",        lambda a, _: f"Demo Product 信创 国产化适配 {a}"),
    ],
    "list_scenarios": [
        ("迁移场景",        lambda kws, _: f"Demo Product 数据迁移 场景 {' '.join(kws)}"),
        ("容灾场景",        lambda kws, _: f"Demo Product 容灾 双活 高可用 {' '.join(kws)}"),
        ("大数据场景",      lambda kws, _: f"Demo Product 大数据 实时同步 流式 {' '.join(kws)}"),
    ],
    "resolve_relation": [
        ("实体关系",        lambda src, _: f"Demo Product {src} 关联 关系 配置"),
        ("关联约束",        lambda src, _: f"Demo Product {src} 约束 依赖 限制"),
    ],
}


def _decompose_queries(tool_name: str, args: dict, gaps: list[str] = None) -> list[tuple[str, str]]:
    """根据 Tool 类型将单一查询分解为多个精准子查询

    每类 Tool 有预设的维度模板, 每个维度生成独立的检索查询。
    查询会自动融合 args 参数和 gaps 建议的关键词。

    Returns:
        list[tuple[str, str]]: [(维度名, 查询文本), ...]
    """
    templates = _DECOMPOSE_TEMPLATES.get(tool_name)
    if not templates:
        return [("通用查询", _build_query(args, gaps))]

    queries = []
    # 提取常用参数
    source = args.get("source", "")
    target = args.get("target", "")
    error_code = args.get("error_code", "")
    topic = args.get("topic", args.get("aspect", ""))
    operation = args.get("operation", "")
    keywords = args.get("keywords", [])
    if isinstance(keywords, list):
        keywords_str = " ".join(keywords)
    else:
        keywords_str = str(keywords)

    gap_kws = _extract_gap_keywords(gaps) if gaps else []

    for dim_name, fn in templates:
        if tool_name == "diagnose_error":
            query = fn(error_code, "")
        elif tool_name == "explain_architecture":
            query = fn(topic, "")
        elif tool_name == "get_prerequisites":
            query = fn(operation, "")
        elif tool_name == "query_product":
            aspect = args.get("aspect", "overview")
            query = fn(aspect, "")
        elif tool_name == "list_scenarios":
            query = fn(keywords_str.split() if keywords_str else ["通用"], "")
        elif tool_name == "resolve_relation":
            source_entity = args.get("source_entity", "")
            query = fn(source_entity, "")
        else:
            query = fn(source, target)

        if gap_kws:
            query += " " + " ".join(gap_kws[:3])

        queries.append((dim_name, query))

    n = len(queries)
    if n > SEARCH_DECOMPOSE_MAX:
        queries = queries[:SEARCH_DECOMPOSE_MAX]
    elif n < SEARCH_DECOMPOSE_MIN:
        generic_query = _build_query(args, gaps)
        while len(queries) < SEARCH_DECOMPOSE_MIN:
            queries.append((f"补充维度{len(queries)}", generic_query + f" 补充维度{len(queries)}"))

    return queries


def _aggregate_results(all_hits_by_query: list[tuple[str, list[dict]]],
                       max_total: int = None) -> list[dict]:
    """聚合多路查询结果: 去重 + 重排序

    每条查询独立返回 top_k 条结果 (已通过 BM25+BGE+RRF 混合检索)。
    聚合逻辑:
      1. 按内容前 N 字符去重 (SEARCH_DECOMPOSE_DEDUP 控制阈值)
      2. 相同内容保留最高分
      3. 标记来源维度
      4. 按分数降序排列

    Args:
        all_hits_by_query: [(query_text, [hits]), ...]
        max_total: 最大返回条数

    Returns:
        list[dict]: 去重后的聚合结果
    """
    if max_total is None:
        max_total = SEARCH_DECOMPOSE_TOP_K * 2  # 聚合后适当扩大

    # 去重: 取内容前 N 字符的 hash 作为去重 key
    # SEARCH_DECOMPOSE_DEDUP 为小数 (0.85 = 85%), 直接乘 500 得字符数
    dedup_len = max(80, int(500 * SEARCH_DECOMPOSE_DEDUP))
    seen_hashes = {}
    unique_hits = []

    for query_text, hits in all_hits_by_query:
        for h in hits:
            content = h.get("content", "")
            # 用前 dedup_len 字符的 hash 去重
            content_key = hashlib.md5(
                content[:dedup_len].encode("utf-8", errors="replace")
            ).hexdigest()
            if content_key in seen_hashes:
                # 保留更高分
                if h.get("score", 0) > seen_hashes[content_key].get("score", 0):
                    seen_hashes[content_key] = dict(h)
                    seen_hashes[content_key]["_query"] = query_text[:50]
                continue
            h_copy = dict(h)
            h_copy["_query"] = query_text[:50]
            seen_hashes[content_key] = h_copy

    unique_hits = list(seen_hashes.values())

    # 按分数降序
    unique_hits.sort(key=lambda x: x.get("score", 0), reverse=True)

    # 截断
    return unique_hits[:max_total]


# ======================================================================
#  v3.6: 通用诊断知识消费优化（处理深度）
# ======================================================================

# 通用、与 DB/症状无关的 snippet 可操作性信号
_ACTIONABILITY_PATTERNS = [
    (re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*\.[a-zA-Z0-9_.]+[ \t\n\r\f\v]*[:=][ \t\n\r\f\v]*[^ \t\n\r\f\v,;]+"), 1.0),
    (re.compile(r"(?<![a-zA-Z0-9_])-[0-9]{3,}(?![a-zA-Z0-9_])"), 1.0),
    (re.compile(r"(?<![a-zA-Z0-9_])/([a-zA-Z0-9_.-]+(?:/[a-zA-Z0-9_.-]+)*)", re.IGNORECASE), 1.0),
    (re.compile(r"(?<![a-zA-Z0-9_])(?:SELECT|ALTER|CREATE|INSERT|UPDATE|DELETE)(?![a-zA-Z0-9_])", re.IGNORECASE), 0.8),
    (re.compile(r"(?:不支持|暂不支持|not supported|limited)", re.IGNORECASE), 0.8),
]

# 从 snippet 文本中提取顶层关键事实的通用模式（不做 DB/症状语义解释）
_MUST_KNOW_PATTERNS = {
    "critical_params": re.compile(
        r"(?:^|[ \t\n\r\f\v])"
        r"([a-zA-Z_][a-zA-Z0-9_]*\.[a-zA-Z0-9_.]+)"
        r"[ \t\n\r\f\v]*[:=][ \t\n\r\f\v]*"
        r"([^ \t\n\r\f\v,;]+)"
    ),
    "error_codes": re.compile(r"(?<![a-zA-Z0-9_])-?[0-9]{3,}(?![a-zA-Z0-9_])"),
    "paths": re.compile(r"(?<![a-zA-Z0-9_])/([a-zA-Z0-9_.-]+(?:/[a-zA-Z0-9_.-]+)*)", re.IGNORECASE),
    "flags": re.compile(r"(?<![a-zA-Z0-9_])(YES|NO|TRUE|FALSE|ON|OFF)(?![a-zA-Z0-9_])", re.IGNORECASE),
}

_MUST_KNOW_MAX_ITEMS = 8


def _actionability_score(text: str) -> float:
    """基于通用结构信号给 snippet 打分，越高表示越可能包含可直接操作的信息。"""
    if not text:
        return 0.0
    score = 0.0
    for pat, weight in _ACTIONABILITY_PATTERNS:
        if pat.search(text):
            score += weight
    return min(score, 3.0)


def _extract_must_know(dimensions: List[dict]) -> dict[str, list]:
    """从 dimension snippets 中通用提取关键事实。

    仅使用语法级模式：点分参数名、错误码、路径、开关值。
    不解释参数含义，不维护 DB/症状特定规则。
    """
    all_text = "\n".join(
        str(s.get("content", ""))
        for d in dimensions
        for s in d.get("snippets", [])
    )

    # 1. 点分参数名赋值
    params: list[dict] = []
    seen_params = set()
    for m in _MUST_KNOW_PATTERNS["critical_params"].finditer(all_text):
        name, value = m.group(1), m.group(2)
        if name in seen_params or len(name) <= 3:
            continue
        # 过滤掉明显不是配置项的内容（URL、时间戳、版本号）
        if value.startswith(("http", "https", "www")):
            continue
        if re.match(r"^[0-9]{1,2}\.[0-9]{1,2}\.[0-9]{1,2}$", value):
            continue
        seen_params.add(name)
        params.append({"name": name, "value": value})
        if len(params) >= _MUST_KNOW_MAX_ITEMS:
            break

    # 2. 错误码
    error_codes: list[str] = []
    seen_codes = set()
    for m in _MUST_KNOW_PATTERNS["error_codes"].finditer(all_text):
        code = m.group(0)
        if code not in seen_codes:
            seen_codes.add(code)
            error_codes.append(code)
        if len(error_codes) >= _MUST_KNOW_MAX_ITEMS:
            break

    # 3. 路径
    paths: list[str] = []
    seen_paths = set()
    for m in _MUST_KNOW_PATTERNS["paths"].finditer(all_text):
        path = "/" + m.group(1).strip(".,;:!?'")  # type: ignore[operator]
        if path not in seen_paths:
            seen_paths.add(path)
            paths.append(path)
        if len(paths) >= _MUST_KNOW_MAX_ITEMS:
            break

    # 4. 开关值
    flags: list[str] = []
    seen_flags = set()
    for m in _MUST_KNOW_PATTERNS["flags"].finditer(all_text):
        flag = m.group(1).upper()
        if flag not in seen_flags:
            seen_flags.add(flag)
            flags.append(flag)
        if len(flags) >= _MUST_KNOW_MAX_ITEMS:
            break

    return {
        "critical_params": params,
        "error_codes": error_codes,
        "paths": paths,
        "flags": flags,
    }


# ======================================================================
#  v3.5: 通用诊断知识合成（指针污染修复）
# ======================================================================

# 内置诊断知识源注册表：BKN 优先，Qdrant 补充
# 23 号方案：分析思路/能力概要不再来自 symptom-router（已下延），改由
# `get_symptom_skills` 从**本体派生**（进程链/日志自证性/检索源）与 **Skill manifest** 生成；
# 来源标签随内容动态标注（skill_map.analysis_source / capabilities_source）。
_DIAGNOSIS_REGISTRY = KnowledgeRegistry([
    BknSectionSource("分析思路", "analysis_framework", "skill_map", priority=1,
                     source_key="analysis_source"),
    BknSectionSource("Skill 能力概要", "skill_capabilities", "skill_map", priority=2,
                     source_key="capabilities_source"),
    BknRiskContextSource(priority=3),
    QdrantSearchSource(
        "常见原因",
        lambda ctx: f"{ctx['symptom']} {ctx['db_type']} 原因 触发条件 常见",
        priority=10,
    ),
    QdrantSearchSource(
        "排查步骤",
        lambda ctx: f"{ctx['symptom']} {ctx['db_type']} 排查 步骤 修复 解决方案",
        priority=11,
    ),
    QdrantSearchSource(
        "配置检查",
        lambda ctx: f"{ctx['db_type']} 配置 参数 检查 {ctx['symptom']}",
        priority=12,
    ),
    QdrantSearchSource(
        "日志与工具",
        lambda ctx: f"{ctx['db_type']} {ctx['symptom']} 日志 分析 dump 工具",
        priority=13,
    ),
    QdrantSearchSource(
        "操作约束",
        lambda ctx: (
            f"{ctx['error_code']} 操作约束 前置条件 注意事项".strip()
            if ctx.get("error_code") else ""
        ),
        priority=14,
    ),
])


def synthesize_diagnosis_knowledge(
    symptom: str,
    db_type: str,
    error_code: Optional[str] = None,
    bkn_context: Optional[dict] = None,
    skill_map: Optional[dict] = None,
    top_k: int = 3,
    sources: Optional[list] = None,
) -> dict:
    """为 diagnose_db_link 合成多维度排查知识。

    通过 KnowledgeRegistry 组合 BKN 结构化知识与 Qdrant 非结构化补充：
      - BKN Section Source：分析思路（本体派生：进程链/日志自证性/检索源）、Skill 能力概要（manifest）。
      - BKN Risk Context Source：从 risks/diagnostics 提取错误码风险上下文。
      - Qdrant Search Source：按维度搜索常见原因、排查步骤、配置检查、日志/工具、操作约束。
    返回按维度组织的 snippets，供模型直接阅读。
    """
    if not symptom:
        symptom = "unknown"
    # db_type 为空或 "unknown" 时不参与检索词（避免污染语义检索），摘要中省略
    if not db_type or db_type == "unknown":
        db_type = ""

    # 25 号接线：检索源 `store:` 引用 → 物理集合（BKN 指引「查哪」真实生效）
    collection = ""
    if sources:
        collection = _resolve_collection(sources[0])

    ctx = {
        "symptom": symptom,
        "db_type": db_type,
        "error_code": error_code,
        "skill_map": skill_map or {},
        "bkn_context": bkn_context,
        "search_fn": search_qdrant,
        "track_fn": _track_dimension,
        "top_k": top_k,
        "hybrid": SEARCH_HYBRID,
        "collection": collection or None,
    }

    dimensions = [r.to_dict() for r in _DIAGNOSIS_REGISTRY.synthesize(ctx)]

    # 收集 Qdrant 引用
    all_references = set()
    for dim in dimensions:
        for snippet in dim.get("snippets", []):
            src = snippet.get("source", "") or snippet.get("id", "")
            if src:
                all_references.add(src)

    # 信息仍不足时扩大检索
    # 21 号 2E：必须带 collection——此前绕过 ctx 直接调 search_qdrant，
    # registry 各源打对了集合（QdrantSearchSource.fetch 透传 ctx.collection），
    # 唯独这条补充检索回落到主集合，是 diagnose_db_link 33% 污染的来源。
    total_snippets = sum(len(d.get("snippets", [])) for d in dimensions)
    if total_snippets < 5:
        try:
            generic_query = f"{symptom} {db_type} Demo Product 故障排查"
            extra_hits = search_qdrant(generic_query, top_k=top_k + 2, hybrid=SEARCH_HYBRID,
                                       collection=collection or None)
            if extra_hits:
                for h in extra_hits:
                    all_references.add(h.get("source", "") or h.get("id", ""))
                dimensions.append({"name": "补充检索", "phase": "qdrant", "snippets": extra_hits})
        except Exception as e:
            logger.warning("补充检索失败: %s", e)

    # 按可操作性对每维度内部 snippet 排序（通用，不依赖 DB/症状）
    for dim in dimensions:
        snippets = dim.get("snippets", [])
        if snippets:
            snippets.sort(
                key=lambda s: (_actionability_score(s.get("content", "")), s.get("score", 0)),
                reverse=True,
            )

    # 从所有 snippets 中提取通用关键事实（不做语义解释）
    must_know = _extract_must_know(dimensions)

    # 生成一句话摘要
    parts = [f"{symptom}（{db_type}）" if db_type else symptom]
    if error_code and error_code != symptom:
        parts.append(f"错误码 {error_code}")
    parts.append("的排查知识")
    summary = "基于 BKN 分析思路、Skill 能力概要、风险上下文与 Qdrant 多维度检索，整理了 " + "".join(parts) + "，涵盖常见原因、排查步骤、配置检查与日志/工具参考。"

    return {
        "summary": summary,
        "must_know": must_know,
        "dimensions": dimensions,
        "top_references": sorted(r for r in all_references if r),
    }


# ======================================================================
#  v3.0: Hermes 原生分解 — 返回 gaps + 搜索提示
# ======================================================================

def _extract_skill_from_result(result: dict) -> str | None:
    """从 BKN 结果中提取 `负责 Skill` 或 Skill 引用"""
    # 批 5-7（22 号 5b-7 ①）：优先读 tools 注入的结构化字段（get_prerequisites 由
    # resolver 经 get_skills_for_action() 图查得到，非文本正则）；正则兜底保留为兼容层。
    structured = result.get("_structured_skills")
    if isinstance(structured, list) and structured:
        return structured[0]
    # 优先从 kv 字段精确匹配
    kv = result.get("kv", {})
    for key, val in kv.items():
        if "Skill" in key or "skill" in key.lower():
            m = re.search(r"`?([a-zA-Z0-9_-]+)`?", val)
            if m:
                return m.group(1)
    # 从 diagnosis/raw/prerequisites 文本提取
    # v3.10: raw 已从 diagnose_error / get_prerequisites 的输出里删除（与命名字段逐字节重复），
    # 所以兜底链要补上 prerequisites。**但必须逐项校验类型**：`prerequisites` 不是到处都为字符串——
    # design_solution 的 `prerequisites` 是一个 operation 列表，若直接取用会把 list 喂给 re.search
    # 并抛 TypeError（本改动第一版正是这么把 test_design_solution 三个用例打红的）。
    # 原实现 `result.get("raw","") or ...` 在 raw 为非空 list 时同样会崩，这里一并收紧。
    raw = ""
    for _candidate in ("raw", "diagnosis", "prerequisites"):
        _value = result.get(_candidate)
        if isinstance(_value, str) and _value:
            raw = _value
            break
    if raw:
        m = re.search(r"负责[ \t]*Skill[：:][ \t]*`?([a-zA-Z0-9_-]+)`?", raw)
        if m:
            return m.group(1)
    return None


# ── 维度提示词注册表（模块级，供 _build_search_instruction 和 diagnose_db_link 共用）──

def _build_dimension_hints(tool_name: str, args: dict) -> dict[str, str]:
    """根据 Tool 与 args 生成维度→提示词映射。

    各 Tool 有专属模板时用模板，否则回退到通用拼接。Agent 可自由改写。
    """
    source = (args.get("source") or args.get("db_type") or "").strip()
    target = (args.get("target") or "").strip()
    symptom = (args.get("symptom") or "").strip()

    # design_solution / diagnose_db_link 共用的维度提示词
    hints = {
        "字符集/类型映射": f"{source} 字符集转换 数据类型映射 字段长度 NLS_LANG 精度丢失",
        "全量同步参数": "全量同步 大表拆分 导出线程 装载线程 表覆盖策略 单表拆分 并发",
        "增量/日志解析": f"{source} 增量同步 日志解析 CDC redo log 归档 archive log supplemental 错误处理策略 插入冲突 更新未找到 装载错误",
        "断点续传/容错": "断点续传 checkpoint 中断恢复 错误处理 冲突处理 主键冲突 位点异常 dumpredo",
        "数据校验/对比": "数据校验 整库对比 表对比 一致性检查 差异修复 SCN sequence",
        "源端特定配置": f"{source} 数据库配置 权限 授权 环境要求 前置条件 supplemental log force logging 归档模式",
        "目标端特定配置": f"{target} 数据库配置 编目 编码 用户授权 表空间 环境要求",
        "跨地域/网络优化": "跨地域 异地同步 网络优化 LZ4 ZSTD 压缩 批量提交 带宽 延迟",
        "风险/异常处理": "同步 风险 异常 常见错误 故障排查 ORA- -4002 -4073 -4006",
        "规则配置/装载策略": "同步规则 错误处理策略 更新未找到记录 删除未找到记录 插入冲突 装载错误 过滤条件 维护模式 DDL过滤 字段映射 DML追踪 全量对象过滤",
    }

    # 诊断类 Tool 可附加症状关键词
    if symptom and tool_name in ("diagnose_db_link", "diagnose_error"):
        hints = {
            k: (f"{symptom} {v}" if symptom not in v else v)
            for k, v in hints.items()
        }

    return hints


def _build_search_instruction(tool_name: str, args: dict, gaps: list[str],
                               skill_name: str = None) -> str:
    """生成搜索提示：展示全部可用维度菜单，由 Agent 根据上下文自选。

    v3.6: 从「指令式」（推荐前 5 个维度请搜索）改为「菜单式」（列出所有维度
    及提示词，Agent 根据症状/DB 类型/对话上下文自主选择 3-5 个维度构造查询）。

    当 SEARCH_DEFER_TO_HERMES=true 时触发。
    """
    params_str = ", ".join(
        f"{k}={v}" for k, v in args.items() if v
    )

    dim_names = _get_known_dimensions(tool_name)
    query_hints = _build_dimension_hints(tool_name, args)

    # ── 全量菜单：不替 Agent 筛选，全部列出 ──
    dim_menu = "\n".join(
        f"  - {dim_name}\n    hint: {query_hints.get(dim_name, f'{dim_name} 相关配置参数和命令')}"
        for dim_name in dim_names
    )

    if skill_name:
        skill_line = (
            f"ACTION_REQUIRED: BKN is partial but has identified responsible Skill. "
            f"Execute BOTH in parallel: (1) skill_view(\"{skill_name}\") for diagnostic commands and repair steps, "
            f"AND (2) choose 3-5 relevant dimensions from the menu below and search_qdrant per dimension. "
            f"These are EQUAL priority actions — do both, not just one.\n"
        )
    else:
        skill_line = ""

    return (
        f"{skill_line}"
        f"BKN data is partial for {tool_name}({params_str}). "
        f"Gaps: {'; '.join(gaps[:4])}. "
        f"YOU (the Agent) choose which dimensions to search based on the context. "
        f"Pick 3-5 relevant dimensions, use the hints below as query starting points, "
        f"and call `search_qdrant` with PRECISE technical terms.\n"
        f"Available dimensions (you decide):\n{dim_menu}"
    )


# ======================================================================
#  fallback_to_qdrant (v2.0: 支持多维度分解)
# ======================================================================

def _resolve_collection(store_ref: str) -> str:
    """`store:xxx#维度` → 物理集合名（25 号接线：让 BKN「查哪」契约真实生效）。

    解析层 = `manifest.resolve_store_id`（原本零生产调用者）；未登记/无法解析返回 ""
    （调用方按 None 处理 → 默认主集合 QDRANT_COLLECTION，向后兼容）。
    """
    ref = (store_ref or "").strip()
    if not ref.startswith("store:"):
        return ""
    try:
        from .manifest import resolve_store_id
        item = resolve_store_id(ref)
    except Exception:
        return ""
    return (item or {}).get("collection", "")


def _evidence_collection(args: dict) -> str:
    """按 args 推导诊断检索源集合。

    32 号（码只作入口）：**错误码的检索源就是模式库**——`DIAG_RETRIEVAL_GUIDE`
    （`store:log_patterns_collection#错误码`）是常量规则，不再依赖"码 → 进程 → 证据源"这条边链
    （码已退出本体）。症状仍走原链（症状 → 嫌疑进程 → 证据源）。
    """
    try:
        from .resolver import BKNResolver
        from .config import BKN_ROOT
        from .constants import DIAG_RETRIEVAL_GUIDE
        if (args.get("error_code") or "").strip():
            col = _resolve_collection(str(DIAG_RETRIEVAL_GUIDE).split("#")[0])
            if col:
                return col
        r = BKNResolver(bkn_root=BKN_ROOT)
        key = (args.get("error_code") or args.get("symptom") or "").strip()
        if not key:
            return ""
        procs = r.get_processes_for_symptom(key)
        if not procs:
            return ""
        for src in r.get_evidence_sources(procs[0]):
            col = _resolve_collection(src)
            if col:
                return col
    except Exception:
        pass
    return ""


def fallback_to_qdrant(args: dict, result: dict, gaps: list[str] = None) -> dict:
    """BKN 数据不充分时回退 Qdrant 语义检索

    v3.0: SEARCH_DEFER_TO_HERMES=true → 返回 _search_deferred + _instruction
    v3.1: 质量评估已移除, 旧路径仅保留基本 enrichment
    """
    confidence = result.get("confidence", "full")

    # ── v3.0: Hermes 原生分解 — 返回 gaps + 搜索提示即 return, 不做内部 Qdrant ──
    if SEARCH_DEFER_TO_HERMES and confidence in ("none", "partial"):
        # 优先从 result 取 _tool_name，回退到推断
        tool_name = result.get("_tool_name", "")
        if not tool_name:
            if "source" in args and "target" in args:
                tool_name = "design_solution"
            elif "error_code" in args:
                tool_name = "diagnose_error"
            elif "operation" in args:
                tool_name = "get_prerequisites"
            elif "topic" in args:
                tool_name = "explain_architecture"
        # v3.5: 提取 BKN 中标记的 Skill，Skill 与 Qdrant 同级并列
        skill_name = _extract_skill_from_result(result)
        if skill_name:
            result["_skill_recommendation"] = {
                "skill": skill_name,
                "reason": "BKN 标记此对象由该 Skill 负责，含完整诊断命令、修复步骤和操作约束",
                "priority": "equal"  # Skill 与 Qdrant 同级，应同时执行
            }
        instruction = _build_search_instruction(tool_name, args, gaps or [], skill_name=skill_name)
        result["_instruction"] = instruction
        result["_search_deferred"] = True
        result["_coverage_pending"] = True
        return result

    # ↓ 以下仅 SEARCH_DEFER_TO_HERMES=false 时到达（v2.0 内部兜底）
    # 决定是否执行内部 Qdrant fallback：尊重 fallback 开关
    if confidence == "none" and not SEARCH_FALLBACK_NONE:
        return result
    if confidence == "partial" and not SEARCH_FALLBACK_PARTIAL:
        return result

    # 从 result 或 args 推断 tool_name
    tool_name = result.get("_tool_name", "")
    if not tool_name:
        if "source" in args and "target" in args and "scenario_hint" in args:
            tool_name = "design_solution"
        elif "error_code" in args:
            tool_name = "diagnose_error"

    # ── v2.0: 查询分解 ──
    queries = []
    if SEARCH_DECOMPOSE and tool_name and tool_name in _DECOMPOSE_TEMPLATES:
        queries = _decompose_queries(tool_name, args, gaps)
        top_k_per_query = SEARCH_DECOMPOSE_TOP_K

        collection = _evidence_collection(args) or None  # 25 号接线：兜底检索打对集合
        all_hits = []
        for dim_name, q in queries:
            q_hits = search_qdrant(q, top_k=top_k_per_query, hybrid=SEARCH_HYBRID,
                                   collection=collection)
            if q_hits:
                # 给每个 hit 打上维度标签并追踪覆盖度
                for h in q_hits:
                    h["_dim"] = dim_name
                _track_dimension(dim_name, len(q_hits))
                all_hits.append((dim_name, q_hits))

        hits = _aggregate_results(all_hits)
        hit_count = len(hits)
    else:
        query = _build_query(args, gaps=gaps)
        hits = search_qdrant(query, top_k=3, hybrid=SEARCH_HYBRID,
                             collection=_evidence_collection(args) or None)
        hit_count = len(hits)
        queries = [("通用查询", query)]

    # ── 无命中 ──
    if not hits:
        result["fallback_hint"] = "BKN 和 Qdrant 均无相关数据。可尝试检查源端文档或询问用户补充。"
        return result

    # 拼接命中片段
    snippets = []
    for h in hits:
        dim_tag = f" [{h.get('_dim', h.get('_query', ''))}]" if h.get('_dim') or h.get('_query') else ""
        score_str = (f" [相似度:{h.get('score', 0):.2f}{dim_tag}]"
                     if h.get('score', 0) > 0 else dim_tag)
        snippets.append(f"---{score_str}\n{h.get('content', '')}")
    content_block = "\n".join(snippets)

    # 简化返回 (v3.1: 无质量评估, 仅保留基本 enrichment; 仅 DEFER=false 路径执行)
    if SEARCH_PARTIAL_ENRICH and confidence == "partial":
        result["_bkn_skeleton"] = True
        result["enrichment"] = {
            "source": "qdrant",
            "hits": hit_count,
            "decomposed": SEARCH_DECOMPOSE and tool_name in _DECOMPOSE_TEMPLATES,
            "content": content_block,
        }
        result["confidence"] = "full"
        result["gaps"] = []
    else:
        result["fallback_hint"] = content_block
        if confidence == "none":
            result["confidence"] = "partial"

    return result
