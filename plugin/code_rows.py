"""码行索引：把「错误码 → 所在行」做成确定性通道。

背景（84 号设计）：
- 向量/BM25 是**块级相关性**，对「同一张表里只差一位数字的相邻行」没有区分度；
- 查询侧提取此前只认 -NNNN / ORA-NNNNN，裸码导致精确通道整个静默。

本模块只做三件事，不依赖 embedding：
1. extract_code_mentions()：把查询里的码归一为规范 ID（裸码须过侧车校验）；
2. CodeRowIndex：从 Qdrant 全文（bm25 的 content_cache）建「码 → 行位置」倒排；
3. code_rows_for_query()：查询 → 命中行（含表头），供检索入口短路返回。
"""

from __future__ import annotations

import re

from .config import CODE_ROWS_MAX, CODE_ROW_MAX_CHARS, EXACT_CODE_LOOKUP

#: 数字码：允许带负号；4-5 位（-4217 / 4217 / 10928）
CODE_RE = re.compile(r"(?<![0-9A-Za-z-])-?[0-9]{4,5}(?![0-9])")
#: 带前缀码：ORA-01555 / ORA01555 / YAS-02276
PREFIX_CODE_RE = re.compile(r"(?<![A-Za-z0-9])(?:ORA|YAS)-?[0-9]{4,5}(?![0-9])", re.IGNORECASE)
#: 裸码的上下文词：仅用于「侧车缺表但用户明确在问码」时放行
_CONTEXT_RE = re.compile(
    r"(错误码|错误代码|异常码|报错|错误|err(?:or)?[ \t\n\r\f\v]*code|code|码)", re.IGNORECASE
)

_MAX_ROW_TEXT = max(80, int(CODE_ROW_MAX_CHARS))


def normalize_code(raw: str) -> str:
    """码的机械归一：4217 -> -4217；ORA1555/ora-1555 -> ORA-01555；其它原样。"""
    s = (raw or "").strip()
    if re.fullmatch(r"[0-9]{4}", s):
        return "-" + s
    m = re.fullmatch(r"(ORA|YAS)-?([0-9]{4,5})", s, re.IGNORECASE)
    if m:
        return "%s-%s" % (m.group(1).upper(), m.group(2).zfill(5))
    return s
_MAX_TOTAL_REFS = 200_000


def _line_span(content: str, pos: int) -> tuple[int, int]:
    """返回 pos 所在行的 [start, end)（不含换行符）。"""
    start = content.rfind("\n", 0, pos) + 1
    end = content.find("\n", pos)
    if end < 0:
        end = len(content)
    return start, end


def _table_header(content: str, line_start: int) -> str:
    """若该行是 Markdown 表行，返回所属表头（表头 + 分隔行，<=200 字）。"""
    line_end = content.find("\n", line_start)
    if line_end < 0:
        line_end = len(content)
    if not content[line_start:line_end].lstrip().startswith("|"):
        return ""
    top = line_start
    while top > 0:
        prev_end = top - 1
        prev_start = content.rfind("\n", 0, prev_end) + 1
        if not content[prev_start:prev_end].strip().startswith("|"):
            break
        top = prev_start
    lines, pos = [], top
    for _ in range(2):
        end = content.find("\n", pos)
        if end < 0:
            end = len(content)
        text = content[pos:end].strip()
        if text:
            lines.append(text)
        pos = end + 1
        if pos >= len(content):
            break
    return " / ".join(lines)[:200]


def _segment_around(content: str, ls: int, le: int, start: int, end: int) -> tuple[int, str]:
    """取「码」附近的自然段，返回 (段起点, 段文本)。

    - 表行：整行；
    - 长段：以「错误码」为分段标记（文档常把上百个码写在同一行）；
    - 分段失败：退回整行。
    """
    line = content[ls:le]
    if line.lstrip().startswith("|"):
        return ls, line.strip()
    seg_start = content.rfind("错误码", ls, start + 1)
    if seg_start < 0:
        seg_start = ls
    seg_end = le
    nxt = content.find("错误码", end)
    if 0 <= nxt < le:
        seg_end = nxt
    seg = content[seg_start:seg_end].strip().strip(",，;；")
    if len(seg) < 8:
        return ls, line.strip()
    return seg_start, seg


def _row_text(content: str, start: int, end: int) -> tuple[str, str]:
    """返回 (表头, 行/段文本)。长段以命中位置为中心切窗，保证命中项在窗内。"""
    ls, le = _line_span(content, start)
    seg_start, line = _segment_around(content, ls, le, start, end)
    if len(line) > _MAX_ROW_TEXT:
        rel = max(0, start - seg_start)
        left = max(0, rel - _MAX_ROW_TEXT // 6)
        line = line[left:left + _MAX_ROW_TEXT]
    return _table_header(content, ls), line


_SIDECAR: dict | None = None


def _sidecar_meaning(canonical: str) -> str:
    """侧车（error_codes.yaml）里的中文释义；缺表/缺键返回空串。"""
    global _SIDECAR
    if _SIDECAR is None:
        try:
            from .resolver import _load_error_codes
            _SIDECAR = _load_error_codes() or {}
        except Exception:  # noqa: BLE001
            _SIDECAR = {}
    entry = (_SIDECAR.get(canonical) or _SIDECAR.get(canonical.lstrip("-"))
             or _SIDECAR.get(canonical.replace("-", "")) or {})
    for key in ("zh", "meaning", "en"):
        value = str(entry.get(key) or "").strip()
        if value:
            return value
    return ""


def _keys(canonical: str, raw: str) -> set[str]:
    """码的所有可检索键（带横杠/不带横杠两种形态）。"""
    keys = {canonical, canonical.replace("-", "")}
    if raw and raw != canonical:
        keys.add(raw)
        keys.add(raw.replace("-", ""))
    return {k for k in keys if k}


def extract_code_mentions(query: str) -> list[dict]:
    """查询 → 规范码列表 [{canonical, raw, verified}]。

    规则：
    - 带负号 / 带 ORA|YAS 前缀：强信号，侧车缺表也采纳（verified=False）；
    - 裸数字：必须在 error_codes.yaml 里（verified=True），或紧邻「错误码/报错/code」等上下文词；
    - 端口、年份、版本号等普通数字不触发。
    """
    text = (query or "").strip()
    if not text:
        return []
    try:
        from .resolver import _load_error_codes
    except Exception:  # noqa: BLE001 —— 侧车不可用时不阻断检索
        return []

    table = _load_error_codes() or {}
    out: dict[str, dict] = {}

    def _add(raw: str, canonical: str, verified: bool) -> None:
        cur = out.get(canonical)
        if cur is None or (verified and not cur["verified"]):
            out[canonical] = {"canonical": canonical, "raw": raw, "verified": verified}

    for m in PREFIX_CODE_RE.finditer(text):
        raw = m.group(0)
        canonical = normalize_code(raw)
        _add(raw, canonical, canonical in table)

    for m in CODE_RE.finditer(text):
        raw = m.group(0)
        canonical = normalize_code(raw)
        verified = canonical in table or raw in table
        if not raw.startswith("-"):
            near = text[max(0, m.start() - 12):m.end() + 12]
            if not verified and not _CONTEXT_RE.search(near):
                continue
        _add(raw, canonical, verified)

    return list(out.values())


class CodeRowIndex:
    """「码 → 行」倒排。构建自 bm25 的 content_cache（Qdrant 全文），零 embedding。"""

    def __init__(self, posting: dict[str, list[tuple]], cache: dict[str, str],
                 complete: bool = True):
        self.posting = posting
        self.cache = cache
        self.complete = complete

    @classmethod
    def build(cls, content_cache: dict[str, str], max_per_code: int | None = None,
              max_total: int = _MAX_TOTAL_REFS) -> "CodeRowIndex":
        limit = int(max_per_code or CODE_ROWS_MAX)
        posting: dict[str, list[tuple]] = {}
        seen: set[tuple] = set()
        total = 0
        complete = True
        for doc_id, content in (content_cache or {}).items():
            if not content:
                continue
            spans = [(m.start(), m.end(), m.group(0)) for m in CODE_RE.finditer(content)]
            spans += [(m.start(), m.end(), m.group(0)) for m in PREFIX_CODE_RE.finditer(content)]
            for start, end, raw in spans:
                total += 1
                if total > max_total:
                    complete = False
                    break
                key = (doc_id, start)
                if key in seen:
                    continue
                seen.add(key)
                try:
                    from .resolver import normalize_error_code
                    canonical = normalize_code(raw)
                except Exception:  # noqa: BLE001
                    canonical = raw
                ref = (doc_id, start, end)
                for k in _keys(canonical, raw):
                    bucket = posting.setdefault(k, [])
                    if len(bucket) < limit:
                        bucket.append(ref)
            if not complete:
                break
        return cls(posting, content_cache or {}, complete)

    def lookup(self, mentions: list[dict], top_k: int = 5) -> list[dict]:
        """码 → 行。同一码的带/不带负号两个键合并，富文本优先，同文去重。"""
        hits: list[dict] = []
        seen: set[tuple] = set()
        for ment in mentions:
            canonical = ment["canonical"]
            keys = [canonical]
            bare = canonical.replace("-", "")
            if bare != canonical:
                keys.append(bare)
            rendered: list[dict] = []
            for key in keys:
                for ref in self.posting.get(key, []):
                    ref_key = (ref[0], ref[1])
                    if ref_key in seen:
                        continue
                    seen.add(ref_key)
                    hit = self._render(ref, ment)
                    if hit:
                        rendered.append(hit)
            # 语料里同一码可能有「映射枚举行」和「表格式说明行」，先按信息量排
            rendered.sort(key=lambda h: -len(h["content"]))
            seen_text: set[str] = set()
            for hit in rendered:
                if hit["content"] in seen_text:
                    continue
                seen_text.add(hit["content"])
                hits.append(hit)
                if len(hits) >= top_k:
                    return hits
        return hits

    def _render(self, ref: tuple, ment: dict) -> dict | None:
        doc_id, start, end = ref
        content = self.cache.get(doc_id) or ""
        if not content:
            return None
        header, line = _row_text(content, start, end)
        if not line:
            return None
        text = (header + "\n" + line) if header else line
        meaning = _sidecar_meaning(ment["canonical"])
        if meaning and meaning not in text:
            text = text + " — " + meaning
        return {
            "id": f"{doc_id}:{start}",
            "content": text[:600],
            "score": 1.0,
            "source": doc_id,
            "chunk_level": "code_row",
            "exact_code": ment["canonical"],
            "exact_raw": ment.get("raw", ""),
            "exact_verified": bool(ment.get("verified")),
            "exact_meaning": meaning,
            "table_header": header,
            "offset": start,
            "_exact_match": True,
            "retrieval_path": ["code_row"],
        }


def blend_code_rows(code_hits: list[dict], base_hits: list[dict], top_k: int) -> list[dict]:
    """码行 + 语义块混合交付：码行在前，按 (来源, 内容前 80 字) 去重，总量 ≤ top_k。"""
    out: list[dict] = []
    seen: set[tuple] = set()
    for hit in list(code_hits) + list(base_hits):
        key = (str(hit.get("source") or ""), (hit.get("content") or "")[:80])
        if key in seen:
            continue
        seen.add(key)
        out.append(hit)
        if len(out) >= top_k:
            break
    return out


def code_rows_for_query(query: str, top_k: int = 5,
                        collection: str | None = None) -> tuple[list[dict], list[dict]]:
    """查询 → (码行命中, 提及列表)。开关关闭或无码时返回 ([], [])。"""
    if not EXACT_CODE_LOOKUP:
        return [], []
    mentions = extract_code_mentions(query)
    if not mentions:
        return [], []
    try:
        from .bm25 import get_code_index
        index = get_code_index(collection)
    except Exception:  # noqa: BLE001 —— 索引不可用时安静退回旧路径
        return [], mentions
    if index is None:
        return [], mentions
    return index.lookup(mentions, top_k=top_k), mentions

