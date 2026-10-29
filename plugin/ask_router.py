# -*- coding: utf-8 -*-
"""ask_router — 开放入口：信号抽取框架（设计：open-entry-ontology-routing-design.md，P1）。

范围（P1）：注册制信号抽取器 + 复用既有逻辑（code_origin / SYMPTOM_ALIASES / 进程·维度·场景
提及 / lookup_operation / 库型词），产出 list[Signal]，供 P2 intent_routes + _route_v2 接 ask()；
P1 阶段不接入 ask()（config.ask_router.enabled=false，仅框架/直测）。

裁定约束（见设计文档 §12）：
- Q1（主导错误码）= 方案 A：regex 命中原生判定；本框架不引入词频驱动（log_pattern 停用，P4 且仅候选）。
- Q3 = 延 P4：alarm_simple 仅兜「告警文本/JSON 已含错误码」（复用 error_code 抽取）。
- 单类抽取失败静默跳过，不放大（错误不拉垮整体入口）。

纪律：P-008 边界匹配、P-009 禁正则简写（显式字符类）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SIGNAL_YAML = _HERE / "entry_signal.yaml"
_SCHEMA_EXPECTED = 1

# 复用 ask.py 的码外形（含 DB 原生码 alpha 前缀）；P-008 边界匹配、P-009 不用 \d/\s
_CODE = re.compile(r"(?<![A-Za-z0-9])((?:[A-Za-z]{1,8}[-_]?)?[0-9]{3,5})(?![0-9])")
# 产品码 vendor 哨兵：用非产品名常量而非产品名，保证去产品化改写（.py→demo_product / .yaml→demo_product）
# 不会把两个文件的同一常量撕裂成不同形态。OSS 同步后，.py 与 intent_routes.yaml 仍同为 "product"。
_PRODUCT_VENDOR = "product"


@dataclass
class Signal:
    kind: str = ""          # error_code / symptom / entity / operation / db_type / alarm
    raw: str = ""
    canonical: str = ""     # 本体入口或规范 id（可为空）
    vendor: str = ""
    confidence: str = "low"      # high / medium / low
    trust: str = "unknown"       # canonical / alias / pattern / unknown
    source_rule: str = ""
    extra: dict = field(default_factory=dict)


def _load_signal_registry():
    try:
        import yaml
        data = yaml.safe_load(_SIGNAL_YAML.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return data


def registry() -> list:
    """启用的注册条目，按 priority 升序。"""
    data = _load_signal_registry()
    rows = data.get("signal_extractors") or []
    rows = [r for r in rows if r.get("enabled")]
    rows.sort(key=lambda r: int(r.get("priority") or 100))
    return rows


def _config() -> dict:
    """读取 plugin/config.yaml 的 ask_router 段（懒加载；异常回退空）。"""
    try:
        import yaml
        cfg = yaml.safe_load((_HERE / "config.yaml").read_text(encoding="utf-8")) or {}
        return cfg.get("ask_router") or {}
    except Exception:
        return {}


def router_enabled() -> bool:
    """P2 起 ask() 据此决定是否前置 _route_v2；P1 默认关，仅框架/直测。"""
    return bool(_config().get("enabled"))


def validate_registry() -> list:
    """注册表 schema 校验，返回问题清单（空=通过）；供测试/门禁使用。"""
    problems = []
    data = _load_signal_registry()
    if data.get("schema") != _SCHEMA_EXPECTED:
        problems.append("schema != %d" % _SCHEMA_EXPECTED)
    rows = data.get("signal_extractors") or []
    ids = [r.get("id") for r in rows]
    if len(ids) != len(set(ids)):
        problems.append("signal id 重复")
    for i, r in enumerate(rows):
        for f in ("id", "kind", "enabled", "priority", "confidence", "fetch"):
            if f not in r:
                problems.append("row[%d] 缺字段 %s" % (i, f))
        if r.get("fetch") not in _FETCHERS:
            problems.append("row[%d] fetch 无实现: %s" % (i, r.get("fetch")))
        if r.get("confidence") not in ("high", "medium", "low"):
            problems.append("row[%d] confidence 非法: %s" % (i, r.get("confidence")))
    return problems


# ---------------- 内置抽取器（注册表只声明开关/优先级/基准置信） ----------------

def _resolver():
    """共享 BKNResolver（懒初始化，避免导入开销/副作用）。"""
    import plugin.tools as m
    if getattr(m, "_resolver", None) is None:
        m._init()
    return m._resolver


def _boundary_hit(name, text):
    """"拉丁词/码标志边界匹配（P-008：不做子串）。"""
    if not name:
        return False
    return re.search(r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])", text, re.I) is not None


def _fetch_error_code(text, *, message="", db_hint="", log_source=""):
    from .code_origin import classify
    hits, seen = [], set()
    for m in _CODE.finditer(text):
        raw = m.group(1)
        info = classify(raw, message=message or text, db_hint=db_hint)
        origin = info.get("origin")
        if origin in ("unknown", "ambiguous"):
            continue
        if origin == "product":
            canonical = "-" + raw.lstrip("-")
            conf = "high"
        else:
            canonical = raw
            conf = "medium"
        key = (origin, canonical)
        if key in seen:
            continue
        seen.add(key)
        hits.append(Signal(kind="error_code", raw=raw, canonical=canonical,
                           vendor=_PRODUCT_VENDOR if origin == "product" else info.get("vendor", ""),
                           confidence=conf, trust="pattern",
                           source_rule=info.get("rule") or "code_origin"))
    return hits


def _fetch_symptom(text, *, message="", db_hint="", log_source=""):
    from .constants import SYMPTOM_ALIASES
    hits, seen = [], set()
    for alias in sorted(SYMPTOM_ALIASES, key=len, reverse=True):
        if alias and alias in text:
            canon = SYMPTOM_ALIASES[alias]
            if canon in seen:
                continue
            seen.add(canon)
            hits.append(Signal(kind="symptom", raw=alias, canonical=canon, trust="alias",
                               confidence="medium", source_rule="symptom_alias"))
    return hits


def _fetch_entity(text, *, message="", db_hint="", log_source=""):
    from .constants import DIMENSION_ALIASES
    R = _resolver()
    hits, seen = [], set()
    try:
        for pid in R._iter_process_ids():
            short = str(pid).rsplit(":", 1)[-1]
            if _boundary_hit(short, text) and pid not in seen:
                seen.add(pid)
                hits.append(Signal(kind="entity", raw=short, canonical=pid, trust="canonical",
                                   confidence="medium", source_rule="process_mention"))
    except Exception:
        pass
    for alias, short in DIMENSION_ALIASES.items():
        if not alias or alias not in text:
            continue
        canon = "dimension:" + short
        if canon not in seen:
            seen.add(canon)
            hits.append(Signal(kind="entity", raw=alias, canonical=canon, trust="alias",
                               confidence="medium", source_rule="dimension_alias"))
    try:
        for sc in R.list_scenarios():
            matches = [k for k in (sc.get("name"), sc.get("id")) if k and k in text]
            matches += [k for k in (sc.get("keywords") or []) if k and k in text]
            if matches:
                canon = "scenario:" + str(sc.get("id") or "")
                if canon not in seen:
                    seen.add(canon)
                    hits.append(Signal(kind="entity", raw=matches[0], canonical=canon, trust="alias",
                                       confidence="medium", source_rule="scenario_keyword"))
    except Exception:
        pass
    return hits


def _fetch_operation(text, *, message="", db_hint="", log_source=""):
    R = _resolver()
    hits, seen = [], set()
    for cap, info in (R._operations or {}).items():
        needles = [cap, info.get("name", "")]
        needles += [a for a in (info.get("aliases") or []) if a]
        for n in needles:
            if n and n in text:
                if cap not in seen:
                    seen.add(cap)
                    hits.append(Signal(kind="operation", raw=n, canonical=cap, trust="alias",
                                       confidence="medium", source_rule="operation_mention"))
                break
    return hits


def _fetch_db_type(text, *, message="", db_hint="", log_source=""):
    from .code_origin import _vendor_hint
    v = _vendor_hint(text or message or db_hint)
    if not v:
        return []
    return [Signal(kind="db_type", raw=v, canonical=v, vendor=v, trust="alias",
                   confidence="medium", source_rule="vendor_hint")]


def _fetch_alarm_simple(text, *, message="", db_hint="", log_source=""):
    """Q3 裁定 P1 兜底：告警文本/JSON 已含错误码才触发（复用 error_code 抽取）；完整字段延 P4。"""
    low = (text or "").lower()
    if not any(k in low for k in ("告警", "alarm")):
        return []
    out = _fetch_error_code(text, message=message, db_hint=db_hint, log_source=log_source)
    for s in out:
        s.kind = "alarm"
    return out


_LOG_LIKE_LEVEL = ("error", "warn", "fatal", "debug", "trace", "exception", "traceback")
_LOG_LIKE_CN = ("告警", "报错", "堆栈", "无法连接", "连接超时", "超时", "拒绝")
_FREQ_STOP = {"error", "errors", "failed", "the", "and", "for", "null", "server",
              "client", "java", "exception", "message", "caused", "info", "warn",
              "debug", "trace", "this", "from", "with", "that", "have", "was",
              "were", "when", "where", "which", "cannot"}


def _is_log_like(text):
    """"是否疑似日志片段（级别词 / 时间戳 / 日志惯用中文词）。"""
    low = text.lower()
    if any(k in low for k in _LOG_LIKE_LEVEL):
        return True
    if re.search(r"[0-9]{4}[-/][0-9]{1,2}[-/][0-9]{1,2}[ T][0-9]{1,2}:[0-9]{1,2}", text):
        return True
    if any(k in low for k in _LOG_LIKE_CN):
        return True
    return False


def _freq_candidates(text, n=3):
    """"无码日志的高频词候选。仅供提示，绝不驱动路由（Q1）。"""
    import collections
    words = [w.lower() for w in re.findall(r"[A-Za-z][A-Za-z0-9_]{1,}", text)]
    words = [w for w in words if len(w) >= 3 and w not in _FREQ_STOP]
    cnt = collections.Counter(words)
    return [w for w, _ in cnt.most_common(n)]


def _fetch_log_pattern(text, *, message="", db_hint="", log_source=""):
    """"Q1：日志片段——只认 regex 身份/码；频次仅候选提示（extra），绝不驱动路由。"""
    if not _is_log_like(text):
        return []
    codes = _fetch_error_code(text, message=message, db_hint=db_hint, log_source=log_source)
    dominant = codes[0].canonical if codes else ""
    return [Signal(kind="log_pattern", raw="", canonical="log_text", confidence="medium",
                   trust="pattern", source_rule="log_snippet",
                   extra={"dominant_code": dominant, "freq_candidates": _freq_candidates(text)})]


_INTENT_KEYWORDS = [
    ("diagnosis", ("报错", "排查", "怎么回事", "原因", "失败", "错误", "问题")),
    ("compat", ("兼容", "迁移", "升级", "支持", "版本", "平台", "jdk", "中间件")),
    ("deploy", ("安装", "部署", "初始化", "搭建", "agent", "注册")),
    ("operation", ("怎么", "如何", "执行", "操作", "步骤", "启动", "停止", "切换")),
    ("risk", ("风险", "影响", "回滚", "后果", "数据丢失", "损坏")),
    ("solution", ("方案", "设计", "规划", "容量", "如何搭建")),
    ("inspection", ("巡检", "检查项", "健康", "定期")),
]


def _fetch_freetext(text, *, message="", db_hint="", log_source=""):
    """"P4：疑问/描述句类分类（诊断/兼容/部署/操作/风险/方案/巡检），仅作文类提示，不参与路由。"""
    low = text.lower()
    best, best_hits = None, 0
    for cls, kws in _INTENT_KEYWORDS:
        hits = sum(1 for k in kws if k in low)
        if hits > best_hits:
            best, best_hits = cls, hits
    if not best:
        return []
    return [Signal(kind="freetext", raw="", canonical=best, confidence="low", trust="alias",
                   source_rule="freetext_intent",
                   extra={"hint": "文类(回答风格参考)；不参与路由"})]


_FETCHERS = {
    "error_code": _fetch_error_code,
    "symptom": _fetch_symptom,
    "entity": _fetch_entity,
    "operation": _fetch_operation,
    "db_type": _fetch_db_type,
    "alarm_simple": _fetch_alarm_simple,
    "log_pattern": _fetch_log_pattern,
    "freetext": _fetch_freetext,
}


def extract_all(text, *, message="", db_hint="", log_source=""):
    """对一段现场输入抽全部信号（注册表逐类；单类失败跳过，不放大）。"""
    text = (text or "").strip()
    if not text:
        return []
    signals = []
    for cfg in registry():
        fetcher = _FETCHERS.get(cfg.get("fetch"))
        if fetcher is None:
            continue
        try:
            for s in (fetcher(text, message=message, db_hint=db_hint, log_source=log_source) or []):
                signals.append(s)
        except Exception:
            continue
    out, seen = [], set()
    for s in signals:
        key = (s.kind, s.canonical or s.raw, s.vendor)
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


# ---------------- 意图解析（P2：intent_routes.yaml 驱动；P3 补聚合/诚实） ----------------

def _load_intent_routes():
    """读取 plugin/intent_routes.yaml 的 routes，按 priority 升序。"""
    try:
        import yaml
        data = yaml.safe_load((_HERE / "intent_routes.yaml").read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    routes = data.get("routes") or []
    routes.sort(key=lambda r: int(r.get("priority") or 100))
    return routes


def _sig_matches(sig, match: dict) -> bool:
    if not match:
        return True
    if match.get("kind") and sig.kind != match.get("kind"):
        return False
    if match.get("vendor") and sig.vendor != match.get("vendor"):
        return False
    if match.get("vendor_not") and (not sig.vendor or sig.vendor == match.get("vendor_not")):
        return False
    if match.get("trust") and sig.trust != match.get("trust"):
        return False
    if match.get("canonical") and sig.canonical != match.get("canonical"):
        return False
    return True


def _build_args(spec: dict, sig, text: str) -> dict:
    out = {}
    for k, v in (spec.get("args") or {}).items():
        if v == "canonical":
            out[k] = sig.canonical
        elif v == "vendor":
            out[k] = sig.vendor
        elif v == "raw":
            out[k] = sig.raw
        elif v == "text500":
            out[k] = (text or "")[:500]
        else:
            out[k] = v
    return out


def _meta(tool: str, sig, code: str) -> dict:
    base = {"ambiguous": False, "rule": "ask_router"}
    if tool == "diagnose_error":
        return dict(base, origin="product", vendor=_PRODUCT_VENDOR, confidence="high",
                    code=code, code_detected=True)
    if tool == "diagnose_db_link":
        if sig.kind == "error_code":
            return dict(base, origin=sig.vendor or "unknown", vendor=sig.vendor,
                        confidence="medium", code=code, code_detected=True)
        return dict(base, origin="symptom", vendor="", confidence="medium", code_detected=False)
    if tool == "resolve_operation":
        return dict(base, origin="operation", vendor="", confidence="medium", code_detected=False)
    return dict(base, origin="unknown", code_detected=False)


def resolve_intent(text, *, db_hint="", log_source="", signals=None):
    """""现场输入 → (tool, args, meta) 或 None。取 dominant：某路由恰命中 1 个候选才采纳；
    无候选/多候选歧义 → None（交 ask() 旧 _route，不猜）。"""
    text = (text or "").strip()
    if not text:
        return None
    if signals is None:
        signals = extract_all(text, db_hint=db_hint, log_source=log_source)
    if not signals:
        return None
    for route in _load_intent_routes():
        m = route.get("match") or {}
        cands = [s for s in signals if _sig_matches(s, m)]
        if not cands:
            continue
        if len(cands) > 1:
            continue  # 同路由多候选 → 歧义，不猜，回退
        sig = cands[0]
        tool = route.get("tool")
        if not tool or tool == "null":
            continue
        args = _build_args(route, sig, text)
        code = sig.canonical if sig.kind == "error_code" else ""
        meta = _meta(tool, sig, code)
        meta["route"] = route.get("id")
        return (tool, args, meta)
    return None


def _route_v2(q, *, db_hint="", log_source=""):
    """""P2：_route_v2。返回 (tool, args, meta) 或 None（回退 ask() 旧 _route）。"""
    return resolve_intent(q, db_hint=db_hint, log_source=log_source)


# ---------------- P3 聚合/答案层：所有已识别意图必须在回答里体现（Q2 裁定） ----------------

_DIRECTION = {
    "error_code": "错误码诊断（含义 / 维度 / 推荐 Skill）",
    "symptom": "该症状维度的排查方向（嫌疑进程 / 检查点 / Skill）",
    "entity": "实体在拓扑 / 进程链 / 文档中的定位与分析",
    "operation": "运维操作的步骤 / 前置条件 / 风险",
    "db_type": "按库型定位诊断落点（DB 原生码）",
    "alarm": "告警对应错误码的诊断方向",
}


def _tool_for_signal(sig) -> str:
    """某信号会落到哪个工具（读 intent_routes 路由表，数据驱动）。"""
    for r in _load_intent_routes():
        if _sig_matches(sig, r.get("match") or {}):
            return r.get("tool") or "—"
    return "—"


def _is_primary(s, primary) -> bool:
    """该信号是否为正在执行的主意图。"""
    args = (primary or (None, {}, None))[1]
    if s.kind == "error_code":
        return s.canonical == args.get("error_code")
    if s.kind == "symptom":
        return s.canonical == args.get("symptom")
    if s.kind == "operation":
        return s.canonical == args.get("operation")
    return False


def attach_intents(payload: dict, sigs: list, primary) -> None:
    """把全部已识别意图写进 payload（Q2：dominant-first，其余备选方向必现）。

    仅产出结构化字段（intents / alt_intents），来源全部确定（信号抽取 + 路由表），
    不引入 Qdrant / 词频等非确定内容 → 守 54 号 C（启用前输出不变，启用后新增字段仍可复现）。
    """
    try:
        sigs = sigs or []
        if not sigs:
            return
        items = []
        for s in sigs:
            item = {"kind": s.kind, "entry": s.canonical or s.raw,
                    "tool": _tool_for_signal(s), "confidence": s.confidence,
                    "source": s.source_rule}
            if s.kind == "log_pattern" and s.extra.get("freq_candidates"):
                item["freq_candidates"] = s.extra["freq_candidates"]
            items.append(item)
        payload["intents"] = items
        if any(s.kind == "log_pattern" for s in sigs):
            payload["log_tip"] = "输入像日志片段：可交给 skill:demo_product-log-analyzer 的 funnel.py 取数/聚类（仅提示，不跨层调用）"
        alt = []
        for s in sigs:
            if primary is not None and _is_primary(s, primary):
                continue
            alt.append({"kind": s.kind, "entry": s.canonical or s.raw,
                        "tool": _tool_for_signal(s),
                        "direction": _DIRECTION.get(s.kind, "备选分析方向")})
        if alt:
            payload["alt_intents"] = alt
    except Exception:
        return


def log_route_trace(question, sigs, primary) -> None:
    """落一条路由决策 trace（确定性、纯增量，不影响主输出，守 54 号 C）。

    仅在 ask_router 启用时调用；记录：抽取到的信号快照 + 命中主意图(route_id/tool/origin)。
    写入 logs/route_trace_log.jsonl（daily + 大小双维轮转，与 usage/gap 一致）。
    任何异常静默——trace 不得影响主流程。
    """
    try:
        import json
        import time
        from .config import (LOG_ROTATE_BACKUPS, LOG_ROTATE_ROUTE_TRACE_MAX_BYTES, resolve_log_path)
        from .log_rotate import rotate_day_file
        path = rotate_day_file(
            resolve_log_path("route_trace_log.jsonl"),
            LOG_ROTATE_ROUTE_TRACE_MAX_BYTES, LOG_ROTATE_BACKUPS,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": int(time.time()),
            "question": (question or "")[:120],
            "n_signals": len(sigs or []),
            "intents": [
                {"kind": s.kind, "entry": s.canonical or s.raw, "vendor": s.vendor,
                 "confidence": s.confidence, "source": s.source_rule}
                for s in (sigs or [])
            ],
            "primary": None,
        }
        if primary is not None:
            entry["primary"] = {
                "tool": primary[0], "args": primary[1],
                "route": (primary[2] or {}).get("route"),
                "origin": (primary[2] or {}).get("origin"),
                "confidence": (primary[2] or {}).get("confidence"),
            }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        return
