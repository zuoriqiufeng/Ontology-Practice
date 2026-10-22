"""bm25.py — BM25 稀疏检索 + RRF 融合

结合 BGE dense 向量搜索和 BM25 关键词搜索, 通过 RRF 融合提高召回精度。
BM25 对错误码、数据库名等精确关键词匹配有优势,
BGE 对自然语言描述有优势, 两者互补。

参考: Qdrant Hybrid Search + RRF (Reciprocal Rank Fusion)
"""
from __future__ import annotations


import math
import re
from collections import defaultdict
from typing import Any

# 模块级 tokenizer 警告, jieba 缺失时设置
_tokenizer_warning: str | None = None


def get_bm25_warnings() -> list[str]:
    """返回 BM25 分词器相关警告"""
    return [_tokenizer_warning] if _tokenizer_warning else []


class BM25Scorer:
    """BM25 评分器 (Okapi BM25)

    简化实现, 支持中文分词 (基于 jieba 或 字符级 n-gram)
    """

    def __init__(self, k1=1.5, b=0.75):
        self.k1 = k1
        self.b = b
        self.doc_count = 0
        self.avg_doc_len = 0
        self.doc_lengths: list[int] = []
        self.doc_ids: list[str] = []
        self.inverted_index: dict[str, dict[int, int]] = defaultdict(dict)  # term → {doc_idx: freq}
        self.doc_term_freq: list[dict[str, int]] = []  # per-doc term frequencies

    # ----- tokenization -----

    @staticmethod
    def tokenize(text: str) -> list[str]:
        """中文/英文混合分词

        优先 jieba, 不可用时用字符级 bigram + 英文 word
        """
        try:
            import jieba
            return list(jieba.cut(text))
        except ImportError:
            global _tokenizer_warning
            _tokenizer_warning = "jieba 未安装, BM25 分词质量下降"
        # Fallback: character bigrams for Chinese + word split for English
        tokens = []
        # Split Chinese characters into bigrams
        chinese_chars = re.findall(r'[\u4e00-\u9fff]+', text)
        for chunk in chinese_chars:
            for i in range(len(chunk)):
                tokens.append(chunk[i])
                if i + 1 < len(chunk):
                    tokens.append(chunk[i:i+2])
        # English words (lowercase, remove punctuation)
        # 使用显式字符类 [a-zA-Z0-9_ \t\n\r\f\v] 替代 \w\s, 兼容底层 re 分类异常的 Python 构建
        english = re.sub(r'[^a-zA-Z0-9_ \t\n\r\f\v]', ' ', text)
        tokens.extend(w.lower() for w in english.split() if len(w) > 1)
        return tokens

    # ----- indexing -----

    def index_documents(self, documents: list[dict]):
        """构建 BM25 索引

        Args:
            documents: [{"id": str, "content": str}, ...]
        """
        self.doc_count = len(documents)
        total_len = 0
        for idx, doc in enumerate(documents):
            doc_id = doc.get("id", str(idx))
            content = doc.get("content", "")
            self.doc_ids.append(doc_id)
            tokens = self.tokenize(content)
            self.doc_lengths.append(len(tokens))
            total_len += len(tokens)
            tf = defaultdict(int)
            for t in tokens:
                tf[t] += 1
            self.doc_term_freq.append(dict(tf))
            for term, freq in tf.items():
                self.inverted_index[term][idx] = freq
        self.avg_doc_len = total_len / max(self.doc_count, 1)

    # ----- scoring -----

    def score(self, query: str) -> list[tuple[str, float]]:
        """对查询评分, 返回 [(doc_id, score), ...] 按分数降序"""
        query_terms = self.tokenize(query)
        if not query_terms:
            return []
        scores: dict[int, float] = defaultdict(float)
        for term in set(query_terms):
            postings = self.inverted_index.get(term, {})
            if not postings:
                continue
            idf = math.log((self.doc_count - len(postings) + 0.5) / (len(postings) + 0.5) + 1)
            for doc_idx, tf in postings.items():
                doc_len = self.doc_lengths[doc_idx]
                numerator = tf * (self.k1 + 1)
                denominator = tf + self.k1 * (1 - self.b + self.b * doc_len / self.avg_doc_len)
                scores[doc_idx] += idf * numerator / denominator
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [(self.doc_ids[idx], score) for idx, score in ranked]


# ========== RRF 融合 ==========

def rrf_fusion(dense_results: list[dict], sparse_results: list[dict],
               k: int = 60, top_k: int = 5) -> list[dict]:
    """Reciprocal Rank Fusion

    融合 dense (BGE) 和 sparse (BM25) 两路搜索结果

    Args:
        dense_results: [{"id": str, "score": float, "content": str}, ...]
        sparse_results: [{"id": str, "score": float, "content": str}, ...]
        k: RRF 平滑参数 (默认 60)
        top_k: 返回条数

    Returns:
        rrf_score = 1/(k + rank_dense) + 1/(k + rank_sparse)
    """
    rrf_scores: dict[str, float] = defaultdict(float)
    doc_map: dict[str, dict] = {}

    # Dense ranking
    for rank, item in enumerate(dense_results, start=1):
        doc_id = item.get("id", "")
        rrf_scores[doc_id] += 1.0 / (k + rank)
        doc_map[doc_id] = item

    # Sparse ranking
    for rank, item in enumerate(sparse_results, start=1):
        doc_id = item.get("id", "")
        rrf_scores[doc_id] += 1.0 / (k + rank)
        if doc_id not in doc_map:
            doc_map[doc_id] = item

    # Sort by RRF score
    merged = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
    result = []
    for doc_id, rrf_score in merged:
        item = dict(doc_map[doc_id])
        item["rrf_score"] = round(rrf_score, 4)
        result.append(item)
    return result


# ========== 全局 BM25 索引 (懒加载, v1.7 按 collection 实例化) ==========

_bm25_indexes: dict[str, "BM25Scorer | None"] = {}  # {collection: index}
_bm25_ready: set[str] = set()                        # 已尝试构建的集合
_bm25_locks: dict[str, Any] = {}                     # 每集合一把构建锁（批量模式防并发重复 scroll）


def _get_lock(collection: str):
    import threading
    if collection not in _bm25_locks:
        _bm25_locks[collection] = threading.Lock()
    return _bm25_locks[collection]


def _build_index(client, collection: str) -> "BM25Scorer | None":
    """从指定 collection scroll 全量文档构建 BM25 索引 + content_cache + exact_index + meta_cache

    21 号 2G 量纲拆分：**索引文本（分词）截断 1000**（构建耗时取舍，已知限制），
    **content_cache / exact_index 用全量 content**（修复尾部错误码精确匹配盲区：
    实测 42 个文档的错误码只出现在 1000 字符之后）。
    """
    docs = []
    content_cache = {}
    meta_cache = {}
    offset = None
    while True:
        try:
            points, offset = client.scroll(
                collection_name=collection,
                limit=200,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
        except (TypeError, ValueError):
            # qdrant-client < 1.7 兼容: scroll 返回单值或不同格式
            result = client.scroll(
                collection_name=collection,
                limit=200,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            if isinstance(result, tuple):
                points, offset = result
            else:
                points, offset = result, None

        for p in points:
            doc_id = str(p.id)
            payload = p.payload or {}
            full_content = payload.get("content", "")
            # 21 号 2G：送 tokenize 的索引文本仍截断 1000（构建耗时保持 ~2.5s 量级，
            # 全量 tokenize 会 2.54→3.54s，+1s 冷启动未获批，登记为已知取舍）；
            # 但 content_cache / exact_index 改用**全量** content——截断曾导致
            # 42 个文档的尾部错误码对精确匹配完全不可见（audit 2026-07-03 登记的 Low 项）
            docs.append({"id": doc_id, "content": full_content[:1000]})
            content_cache[doc_id] = full_content
            # 21 号 2F：载荷元数据随命中回传，供下游分类/去重/交付块解析
            meta_cache[doc_id] = _extract_doc_meta(payload)

        if offset is None:
            break

    if not docs:
        return None  # 空集合/未向量化：不建索引

    index = BM25Scorer()
    index.index_documents(docs)
    # 挂载 content_cache（全量）供 bm25_search 交付与 _search_content_exact 匹配
    index._content_cache = content_cache
    index._meta_cache = meta_cache
    # 构建 exact-term 倒排索引, 用于错误码等精确项快速定位
    # 21 号 2G：基于**全量** content 构建——尾部错误码（>1000 字符区间）此前完全不可见
    exact_index: dict[str, set[str]] = defaultdict(set)
    error_code_pat = re.compile(r'(?<![0-9])-[0-9]{4}(?![0-9])')
    ora_pat = re.compile(r'(?<![a-zA-Z0-9_])ORA-[0-9]{5}(?![a-zA-Z0-9_])')
    token_pat = re.compile(r'[a-zA-Z0-9_\-]+')
    for doc_id, content in content_cache.items():
        if not content:
            continue
        terms: set[str] = set()
        terms.update(error_code_pat.findall(content))
        terms.update(ora_pat.findall(content))
        for token in token_pat.findall(content):
            if len(token) >= 4 and any(c.isdigit() for c in token):
                terms.add(token)
        for term in terms:
            exact_index[term].add(doc_id)
            if term.startswith('-') and term[1:].isdigit():
                exact_index[term[1:]].add(doc_id)
    index._exact_index = dict(exact_index)
    # 84 号：码行倒排（同一批 content_cache，零 embedding；构建失败不影响检索）
    try:
        from .code_rows import CodeRowIndex
        index._code_index = CodeRowIndex.build(content_cache)
    except Exception:  # noqa: BLE001
        index._code_index = None
    return index


def get_code_index(collection: str = None):
    """→ 码行索引（与 BM25 索引同生命周期）；索引不可用返回 None。"""
    idx = get_bm25_index(collection)
    return getattr(idx, "_code_index", None) if idx else None


def get_bm25_index(collection: str = None) -> "BM25Scorer | None":
    """获取指定 collection 的 BM25 索引（懒加载）。

    collection=None 时用默认主集合 QDRANT_COLLECTION（现有调用点零改动）。
    """
    from .config import QDRANT_COLLECTION
    name = collection or QDRANT_COLLECTION
    if name in _bm25_ready:
        return _bm25_indexes.get(name)
    lock = _get_lock(name)
    with lock:
        # double-check（并发时另一线程可能已构建）
        if name in _bm25_ready:
            return _bm25_indexes.get(name)
        _bm25_ready.add(name)
        try:
            from .supplement import _get_qdrant_client
            client = _get_qdrant_client()
            if not client:
                _bm25_indexes[name] = None
                return None
            _bm25_indexes[name] = _build_index(client, name)
            return _bm25_indexes[name]
        except Exception:
            _bm25_indexes[name] = None
            return None


def reset_bm25(collection: str = None) -> list[str]:
    """重置 BM25 索引。collection=None 时重置注册表中的全部集合。

    返回被重置的集合名列表。索引下次使用时自动重建（懒加载）。
    """
    from .config import QDRANT_COLLECTIONS
    if collection:
        targets = [collection]
    else:
        targets = list(QDRANT_COLLECTIONS.keys())
    reset = []
    for name in targets:
        _bm25_indexes.pop(name, None)
        _bm25_ready.discard(name)
        reset.append(name)
    return reset


# ========== 载荷元数据（21 号 2F：随命中回传，供下游分类/去重/交付块解析） ==========

# 与 mini_first 交付块解析、模式库 payload 透传共用的字段集
# 日志模式库（log_patterns_collection）专用字段 —— **唯一口径**。
# **插件内不得再抄一份**：2026-10-13 前该清单有 5 处硬编码副本，`dimension` 只加进本表而漏了副本
# ⇒ 即使 payload 里有 dimension，检索侧也传不回（已修）。
# 与 skill/demo_product-log-pattern-modeler/SKILL.md 的「运行时透传字段」段同源；新增字段须两处同改。
PATTERN_META_KEYS = (
    "pattern_id", "log_fingerprint", "component", "severity",
    "error_codes", "db_types", "target_types", "source_note",
    "dimension",
)
_DOC_META_KEYS = (
    "document_id", "chunk_id", "chunk_level", "title", "large_chunk_id",
    "section_type", "blurb", "parent_chunk_id", "parent_document_id",
    "mini_chunk_index", "image_file_id",
) + PATTERN_META_KEYS


def _extract_doc_meta(payload: dict) -> dict:
    """从 payload 抽取 BM25 命中需要回传的元数据（缺字段不写入，保持 dict 紧凑）。"""
    return {k: payload[k] for k in _DOC_META_KEYS if payload.get(k) is not None}


def bm25_search(query: str, top_k: int = 5, collection: str = None) -> list[dict]:
    """BM25 关键词搜索。collection=None 时用默认主集合。

    21 号 2F：返回 `{**meta, id, bm25_score, content, source}`——此前只回传
    `{id, bm25_score, content}`，导致下游 mini_first 无法按 chunk_level 分类
    （全被判成 other_hits）、去重键 (source, chunk_id) 塌缩、且只能交付 BM25 原始块。
    `source` 取元数据的 document_id（不再是空串，避免下游用标记覆写成同值字符串）。
    """
    index = get_bm25_index(collection)
    if not index:
        return []
    results = index.score(query)[:top_k]
    content_cache = getattr(index, "_content_cache", {})
    meta_cache = getattr(index, "_meta_cache", {})
    out = []
    for doc_id, score in results:
        meta = dict(meta_cache.get(doc_id, {}))
        meta.update({
            "id": doc_id,
            "bm25_score": score,
            "content": content_cache.get(doc_id, ""),
            "source": meta.get("document_id", ""),
        })
        out.append(meta)
    return out
