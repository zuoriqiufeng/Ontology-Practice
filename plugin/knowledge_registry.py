"""knowledge_registry.py — 可组合知识源注册机制

把 BKN 文本、风险上下文、Qdrant 检索等知识获取方式抽象为独立的
KnowledgeSource，通过 KnowledgeRegistry 按优先级组合。

设计约束：
- 本模块为纯抽象层，不在模块加载时依赖 supplement.py / resolver.py，
  避免循环导入。
- Qdrant 搜索与维度追踪函数通过 ctx 注入，保持 source 可测试、可复用。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Optional


def _obs_track(event: str, **fields) -> None:
    """知识源编排的旁路埋点（P2）：无作用域/开关关闭/异常 → 静默丢弃，绝不影响主流程。"""
    try:
        from .observability import track
        track(event, **fields)
    except Exception:
        pass


@dataclass
class DimensionResult:
    """单个知识维度的检索结果。"""

    name: str
    phase: str
    snippets: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "phase": self.phase,
            "snippets": self.snippets,
        }


class KnowledgeSource(ABC):
    """知识源抽象基类。"""

    @property
    @abstractmethod
    def name(self) -> str:
        """知识源名称（对应返回的 dimension 名称）。"""

    @property
    @abstractmethod
    def priority(self) -> int:
        """优先级，数字越小越先执行。"""

    @property
    @abstractmethod
    def source_type(self) -> str:
        """来源类型：'bkn' / 'qdrant' / 其他。"""

    @abstractmethod
    def fetch(self, ctx: dict) -> Optional[DimensionResult]:
        """根据上下文获取知识维度。

        Args:
            ctx: 本次合成的上下文，可包含 symptom、db_type、error_code、
                 skill_map、bkn_context、search_fn、track_fn、top_k 等。

        Returns:
            DimensionResult 或 None（表示无有效内容）。
        """


class BknSectionSource(KnowledgeSource):
    """从 BKN 预提取文本生成知识维度。

    例如从 ctx["skill_map"]["analysis_framework"] 读取「分析思路」。
    """

    def __init__(
        self,
        name: str,
        ctx_key: str,
        ctx_parent: Optional[str] = None,
        source_label: str = "bkn:本体派生",
        priority: int = 1,
        source_key: Optional[str] = None,
    ):
        self._name = name
        self._ctx_key = ctx_key
        self._ctx_parent = ctx_parent
        self._source_label = source_label
        self._priority = priority
        # 动态来源标签：parent dict 中该键的取值（23 号方案：本体派生/ Skill manifest 来源）
        self._source_key = source_key

    @property
    def name(self) -> str:
        return self._name

    @property
    def priority(self) -> int:
        return self._priority

    @property
    def source_type(self) -> str:
        return "bkn"

    def fetch(self, ctx: dict) -> Optional[DimensionResult]:
        parent = ctx.get(self._ctx_parent, {}) if self._ctx_parent else ctx
        if not isinstance(parent, dict):
            return None
        text = parent.get(self._ctx_key, "")
        if not text or not str(text).strip():
            return None
        label = self._source_label
        if self._source_key:
            label = str(parent.get(self._source_key, "") or label)
        return DimensionResult(
            name=self._name,
            phase="bkn",
            snippets=[{
                "content": str(text).strip(),
                "score": 1.0,
                "source": label,
            }],
        )


class BknRiskContextSource(KnowledgeSource):
    """错误码诊断指引维度（25 号：字段随锚点表删除而更新）。

    背景：21 号起 `tools._extract_bkn_context` 输出的是「指引」字段
    （retrieval_guide / suspected_process / dimensions / aliases / unknown_rule），
    本类此前仍读 `risk_level/trigger/handling/prohibitions` 旧字段 → 恒返回 None（死维度）。
    """

    _KEY_LABELS = {
        "retrieval_guide": "完整定义检索源",
        "suspected_process": "嫌疑进程（suspected_in 边）",
        "dimensions": "跨切面维度（has_class 边）",
        "aliases": "别名（归一用）",
        "unknown_rule": "未登记码处理",
    }

    def __init__(self, priority: int = 2):
        self._priority = priority

    @property
    def name(self) -> str:
        return "错误码诊断指引"

    @property
    def priority(self) -> int:
        return self._priority

    @property
    def source_type(self) -> str:
        return "bkn"

    def fetch(self, ctx: dict) -> Optional[DimensionResult]:
        bkn_context = ctx.get("bkn_context")
        if not bkn_context or not isinstance(bkn_context, dict):
            return None
        parts = []
        for key, label in self._KEY_LABELS.items():
            val = bkn_context.get(key)
            if val:
                parts.append(f"{label}: {val if isinstance(val, str) else '、'.join(map(str, val))}")
        if not parts:
            return None
        return DimensionResult(
            name=self.name,
            phase="bkn",
            snippets=[{
                "content": "\n".join(parts),
                "score": 1.0,
                "source": "bkn:risk_context（关系边 + 常量组装）",
            }],
        )


class QdrantSearchSource(KnowledgeSource):
    """通过 Qdrant 搜索生成知识维度。"""

    def __init__(
        self,
        name: str,
        query_template: Callable[[dict], str],
        priority: int = 10,
    ):
        self._name = name
        self._query_template = query_template
        self._priority = priority

    @property
    def name(self) -> str:
        return self._name

    @property
    def priority(self) -> int:
        return self._priority

    @property
    def source_type(self) -> str:
        return "qdrant"

    def fetch(self, ctx: dict) -> Optional[DimensionResult]:
        query = self._query_template(ctx)
        if not query or not str(query).strip():
            return None

        search_fn = ctx.get("search_fn")
        if not search_fn:
            return None

        top_k = ctx.get("top_k", 3)
        hybrid = ctx.get("hybrid", True)
        collection = ctx.get("collection")  # 25 号接线：检索源 store: 解析后的物理集合
        try:
            hits = search_fn(query, top_k=top_k, hybrid=hybrid, collection=collection)
        except Exception:
            return None

        if not hits:
            return None

        track_fn = ctx.get("track_fn")
        if track_fn:
            try:
                track_fn(self._name, len(hits))
            except Exception:
                pass

        return DimensionResult(
            name=self._name,
            phase="qdrant",
            snippets=list(hits),
        )


class KnowledgeRegistry:
    """知识源注册表：按优先级组合多个 KnowledgeSource。"""

    def __init__(self, sources: Optional[list[KnowledgeSource]] = None):
        self._sources: list[KnowledgeSource] = list(sources) if sources else []

    def register(self, source: KnowledgeSource) -> "KnowledgeRegistry":
        """注册新的知识源，支持链式调用。"""
        self._sources.append(source)
        return self

    @property
    def sources(self) -> list[KnowledgeSource]:
        """返回当前注册的所有知识源（按优先级升序排列）。"""
        return sorted(self._sources, key=lambda s: s.priority)

    def synthesize(self, ctx: dict) -> list[DimensionResult]:
        """按优先级执行所有 source，收集非空结果。

        P2 可观测（2026-10-14）：此前 `except: continue` 与「真的没内容」在日志里**完全
        同形**——「本体知识源挂了」不可判别。现在两者各发一条过程事件（`source_error` /
        `source_miss`），`continue` 的容错语义**逐字不变**（异常仍不阻断其他 source）。
        """
        results: list[DimensionResult] = []
        for source in self.sources:
            try:
                result = source.fetch(ctx)
                if result and result.snippets:
                    results.append(result)
                else:
                    _obs_track("source_miss", source=source.name,
                               phase=getattr(source, "source_type", ""))
            except Exception as exc:
                # Source 内部异常不应阻断其他 source 执行
                _obs_track("source_error", source=source.name,
                           phase=getattr(source, "source_type", ""),
                           error=type(exc).__name__)
                continue
        return results

    def to_dicts(self, ctx: dict) -> list[dict]:
        """便捷方法：直接返回维度字典列表。"""
        return [r.to_dict() for r in self.synthesize(ctx)]
