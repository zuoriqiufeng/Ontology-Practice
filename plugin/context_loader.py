"""context_loader.py — Trim + Toon 上下文优化管道

在 Tool 返回结果写入 LLM 上下文前进行:
  Trim: 过滤评分/UUID/空值等低价值字段
  Toon: JSON → 紧凑优化格式 (Token-Optimized Notation)

压缩效果: Token -30~60%, 准确率 +14pp (基于 MSFAgentBench 基准)
"""

import json
import re
from collections import Counter
from typing import Any


def _json_len(obj):
    """json.dumps 后的字符长度（B2 埋点用，44 号 §3.3）。取不到返回 None → 调用方省略该字段。

    **只量不改**：不参与任何返回值的构造（44 号 §3.2 的硬约束）。
    """
    try:
        return len(json.dumps(obj, ensure_ascii=False))
    except Exception:
        return None


class TrimFilter:
    """字段级相关性裁剪器"""

    # 三类裁剪规则
    SCORING_PATTERNS = [
        r"_score$", r"match_score$", r"rerank_score$",
        r"intent_score$", r"similarity$",
    ]
    TECHNICAL_PATTERNS = [
        r".*_uuid$", r"md5$", r"document_id$", r"element_id$",
        r"state_time$", r"start_time$",
    ]
    REDUNDANT_FIELDS = [
        "display_name", "data_source", "module_type",
        "samples", "metadata",
    ]

    def __init__(self, keep_fields=None):
        self.keep = set(keep_fields or [])
        self._compiled_scoring = [re.compile(p, re.I) for p in self.SCORING_PATTERNS]
        self._compiled_tech = [re.compile(p, re.I) for p in self.TECHNICAL_PATTERNS]

    def _should_skip(self, key: str, value) -> bool:
        if key in self.keep:
            return False
        if value is None or value == "" or value == [] or value == {}:
            return True
        for p in self._compiled_scoring:
            if p.search(key):
                return True
        for p in self._compiled_tech:
            if p.search(key):
                return True
        if key in self.REDUNDANT_FIELDS:
            return True
        return False

    def trim(self, data):
        """递归裁剪"""
        if isinstance(data, dict):
            return {
                k: self.trim(v)
                for k, v in data.items()
                if not self._should_skip(k, v)
            }
        elif isinstance(data, list):
            return [self.trim(item) for item in data]
        return data


class ToonFormatter:
    """Token-Optimized Notation 格式化器"""

    INDENT = "  "

    def format(self, data, key="root", indent=0, ancestors=()) -> str:
        if isinstance(data, list):
            return self._fmt_array(data, key, indent, ancestors)
        elif isinstance(data, dict):
            return self._fmt_dict(data, key, indent, ancestors)
        return self._fmt_scalar(data, key, ancestors)

    def _fmt_array(self, arr, key, indent, ancestors=()) -> str:
        if not arr:
            return f"{' ' * indent}{key}[0]: "
        if all(isinstance(x, dict) for x in arr):
            return self._fmt_object_array(arr, key, indent)
        values = ", ".join(self._fmt_scalar(v, key, ancestors) for v in arr)
        return f"{' ' * indent}{key}[{len(arr)}]: {values}"

    def _fmt_object_array(self, arr, key, indent) -> str:
        fields = self._common_fields(arr)
        prefix = " " * indent
        lines = [f"{prefix}{key}[{len(arr)}]{{{','.join(fields)}}}:"]
        for item in arr:
            row = ",".join(str(item.get(f, "")) for f in fields)
            lines.append(f"{prefix}{self.INDENT}{row}")
        return "\n".join(lines)

    def _fmt_dict(self, obj, key, indent, ancestors=()) -> str:
        prefix = " " * indent
        # 本 dict 自身的 key 成为所有子字段的祖先，供 _is_protected 做路径判定
        child_ancestors = ancestors + (key,)
        n_scalars = sum(1 for v in obj.values() if not isinstance(v, (dict, list)))
        # 紧凑格式仅在「全部为标量」时启用；
        # 含 dict/list 值时若走紧凑分支会静默丢弃嵌套内容 (P0-3 修复)
        if n_scalars == len(obj) and 0 < len(obj) <= 5:
            pairs = [f"{k}:{self._fmt_scalar(v, k, child_ancestors)}" for k, v in obj.items()]
            if pairs:
                return f"{prefix}{key}: {{{', '.join(pairs)}}}"
        lines = [f"{prefix}{key}:"]
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                lines.append(self.format(v, k, indent + 1, child_ancestors))
            else:
                lines.append(f"{prefix}{self.INDENT}{k}: {self._fmt_scalar(v, k, child_ancestors)}")
        return "\n".join(lines)

    # 不截断的关键字段: Qdrant enrichment / BKN 诊断等内容容器
    _FULL_CONTENT_KEYS = {"content", "fallback_hint", "enrichment",
                          "_instruction", "quality", "raw", "diagnosis", "description",
                          "_fallback_reason", "_warning", "_model_hint",
                          # v3.5 指针污染修复新增知识字段
                          "knowledge", "prerequisite_knowledge", "dimensions", "snippets",
                          "summary", "top_references", "detail", "check_method",
                          "recommended_steps", "what_you_need", "constraints", "common_errors",
                          "related_skills", "knowledge_snippets", "missing_info", "must_know",
                          # v3.9: 补入同类指令型字段。这三处实测会被截到 80 字符，
                          # 而它们承载的是「让 Agent 做什么」，截断等于静默废掉指令。
                          "_divergence_prompt", "_skill_enforcement", "note", "gaps",
                          # v3.10: get_prerequisites 的正文载体。实测 schema enum 的 operation
                          # **全部**被截：正文 234~724 字符 → 截到 80，切在列表中间，每次丢 154~644 字符。
                          # 同时它与备份字段 raw 逐字节相同，而 raw 已在 tools.py 删除——
                          # 因此这个 key 从此是唯一一份全文，**白名单保护是必需的，不是可选的**。
                          # 另：_enforce_budget 第 2 轮会删非白名单顶层 key，加入后该路径也不再整键丢失。
                          # （批 2-1 起 enum 为 8 个、正文改由 constrained_by 边派生，长度前提不变。）
                                                    "prerequisites",
                          # 54 号（裁 2＝C）：机制归因出口的承载字段——候选与判据命中原文；
                          # 不保护会被截到 80 字符（v3.10 经验 #3 的同类坑）。
                          "entry", "candidates",
                          # C-20261010-01（2026-10-10）：以下 4 个 key 实测存在 >80 字符的值，
                          # 而 _fmt_scalar 按 key 名匹配保护 → 它们此前会被静默截到 80。
                          # 证据：plugin/scripts/field_length_probe.py（13 条未受保护中这 4 个 key 占 12 条）。
                          # 注意副作用（plugin/CLAUDE.md v3.10 经验 #3）：受保护内容最后才动，
                          # 加入后 _enforce_budget 第 2 轮的淘汰顺序会变（被删的会换成别的 key）。
                          "delegated_to",   # check_compatibility：130 字符 qdrant_hint（含 collection 名）
                          "qdrant_hint",    # 同上，叶子级；加它可覆盖不在 delegated_to 下的同类
                          "risks",          # design_solution：100 字符，截断点正切在 Skill 指针中间
                          "processes"}      # explain_architecture：7 条 94~145 字符的进程说明

    @staticmethod
    def _is_protected(key, ancestors=()) -> bool:
        """该字段是否受内容保护（不截断）。

        父字段命中白名单时，其所有子字段一并受保护——避免嵌套在内容容器
        里的字段被无声截断（如 `_skill_enforcement.reason` 实测被截到 80 字符，
        而它承载的是「禁止在 required skill 未加载前输出方案」这条指令）。
        """
        if key in ToonFormatter._FULL_CONTENT_KEYS:
            return True
        return any(a in ToonFormatter._FULL_CONTENT_KEYS for a in ancestors)

    def _fmt_scalar(self, value, key="", ancestors=()) -> str:
        if isinstance(value, bool):
            return "✓" if value else "✗"
        if isinstance(value, str) and len(value) > 80:
            if self._is_protected(key, ancestors):
                return value  # 关键内容字段不截断，完整保留
            return value[:80] + "..."
        return str(value)

    @staticmethod
    def _common_fields(arr, threshold=0.5):
        all_fields = []
        for item in arr:
            all_fields.extend(item.keys())
        counts = Counter(all_fields)
        total = len(arr)
        return [f for f, c in counts.most_common() if c >= total * threshold]


class ContextLoader:
    """Trim + Toon 管道"""

    # 各 Tool 的优化策略
    STRATEGIES = {
        "design_solution":    "trim_only",
        "check_compatibility": "full",
        "query_product":      "toon_only",
        "list_scenarios":     "full",
        "get_prerequisites":  "full",
        "explain_architecture":"toon_only",
        "diagnose_error":     "raw",
        "resolve_relation":   "full",
        "diagnose_mechanism": "full",   # 54 号：五段契约不得被截断
        "resolve_operation":  "full",
    }

    def __init__(self, trim_filter=None):
        self.trim_filter = trim_filter or TrimFilter()
        self.toon = ToonFormatter()

    # ---------- v1.5: 输出总量预算（默认关闭，output_max_chars=0） ----------

    def _enforce_budget(self, data, budget: int):
        """按优先级把 data 截断到 budget 字符内。

        优先级: _FULL_CONTENT_KEYS 内容字段最后被动；非白名单长字符串先截断，
        再删非白名单顶层 key，最后才截白名单内容字段。
        返回 (data, truncated: bool)。
        """
        full_keys = ToonFormatter._FULL_CONTENT_KEYS

        def _size(d):
            return len(json.dumps(d, ensure_ascii=False))

        if _size(data) <= budget:
            return data, False

        import copy
        data = copy.deepcopy(data)

        # 第 1 轮: 非白名单长字符串字段截断到 200 字符（递归）
        # 路径感知：父字段受保护时子字段一并放行，与 _fmt_scalar 同一判定
        def _clip_long_strings(obj, ancestors=()):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if (isinstance(v, str) and len(v) > 200
                            and not ToonFormatter._is_protected(k, ancestors)):
                        obj[k] = v[:200] + "..."
                    elif isinstance(v, (dict, list)):
                        _clip_long_strings(v, ancestors + (k,))
            elif isinstance(obj, list):
                for item in obj:
                    _clip_long_strings(item, ancestors)
        _clip_long_strings(data)
        if _size(data) <= budget:
            return data, True

        # 第 2 轮: 删除非白名单顶层 key（按 key 排序逐个删）
        if isinstance(data, dict):
            for k in sorted(list(data.keys())):
                if k in full_keys or k.startswith("_"):
                    continue
                del data[k]
                if _size(data) <= budget:
                    return data, True

        # 第 3 轮: 白名单长字符串保留头部截断
        if isinstance(data, dict):
            for k in sorted(data.keys()):
                v = data.get(k)
                if isinstance(v, str) and len(v) > 500:
                    keep = max(500, budget // max(len(data), 1))
                    data[k] = v[:keep] + f"\n...[截断，原文 {len(v)} 字符]"
                    if _size(data) <= budget:
                        return data, True

        return data, True

    def process(self, data, tool_name=None, mode="full") -> str:
        """处理查询结果, 返回优化后的字符串"""
        if tool_name and tool_name in self.STRATEGIES:
            mode = self.STRATEGIES[tool_name]
        if mode == "raw":
            return json.dumps(data, ensure_ascii=False, indent=2)
        # v1.5: 输出总量预算（默认 0 = 无限制；raw 模式已在上方直接返回）
        from .config import SEARCH_OUTPUT_MAX_CHARS
        if SEARCH_OUTPUT_MAX_CHARS > 0:
            # B2（44 号 §3.3 `budget_trim`）：本管道是 `_wrap` 类 Tool 的裁剪点，
            # 事件与 tools._apply_output_budget 同形（tool 传 "context_loader"）。
            before_chars = _json_len(data)
            data, truncated = self._enforce_budget(data, SEARCH_OUTPUT_MAX_CHARS)
            if truncated and isinstance(data, dict):
                after_chars = _json_len(data)  # 紧跟裁剪后量取（此时尚未加 `_budget_note`）
                data["_budget_note"] = (
                    f"输出超预算 {SEARCH_OUTPUT_MAX_CHARS} 字符，已按优先级截断"
                )
                from .observability import track
                _fields = {"tool": "context_loader", "max_chars": SEARCH_OUTPUT_MAX_CHARS}
                if before_chars is not None:
                    _fields["before_chars"] = before_chars
                if after_chars is not None:
                    _fields["after_chars"] = after_chars
                track("budget_trim", **_fields)
        trimmed = data
        if mode in ("full", "trim_only"):
            trimmed = self.trim_filter.trim(data)
        if mode in ("full", "toon_only"):
            return self.toon.format(trimmed)
        return json.dumps(trimmed, ensure_ascii=False, indent=2)
