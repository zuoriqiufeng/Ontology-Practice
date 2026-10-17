"""resolver.py — BKN 文件加载与解析引擎

遍历 bkn/ 目录加载所有 .bkn 文件, 提供结构化查询。
支持: Markdown 表格解析 / Section 拆分 / 键值对提取
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .constants import (
    KNOWN_DBS, DB_ALIASES, PROCESS_IDS, is_db_match,
    ERROR_ALIASES, SYMPTOM_ALIASES, DIMENSION_ALIASES, DIAG_RETRIEVAL_GUIDE,
    EVIDENCE_SOURCES, EVIDENCE_SOURCES_DEFAULT,
)
from .relations import RelationTraverser
from .supplement import search_qdrant, _track_dimension

# ── 错误消息语义规则（32 号：码只作入口，含义进推理链）────────────────────
# 规则表在 `plugin/error_semantics.yaml`（**有界：≈8 个语义类别，不随码数增长**；不是码表）。
# 惰性加载并缓存；解析失败时返回空表（此时分类落到 fallback → dimension:unknown，绝不猜）。
_ERROR_SEMANTICS: dict | None = None


def _load_error_semantics() -> dict:
    global _ERROR_SEMANTICS
    if _ERROR_SEMANTICS is None:
        path = Path(__file__).resolve().parent / "error_semantics.yaml"
        try:
            import yaml  # 局部导入：本模块历史上不依赖 yaml（frontmatter 逐行解析），避免加载期强耦合
            _ERROR_SEMANTICS = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001 —— 缺库/缺文件/坏 YAML 都退化为"无规则"（安全侧）
            _ERROR_SEMANTICS = {}
    return _ERROR_SEMANTICS


def classify_error_message(message: str) -> dict:
    """按**消息文本**命中语义规则（顺序即优先级，首位命中即返回）。

    返回 `{rule, dimension, guide, skill, evidence}`；全不命中 → 行的 fallback（未归类 + 检索指引）。
    **依据可溯**：`evidence` 写明命中了哪些关键词（三段式输出契约的第①条要求）。
    """
    data = _load_error_semantics()
    text = str(message or "")
    low = text.lower()
    for rule in data.get("rules") or []:
        hits = [k for k in (rule.get("match") or []) if k and str(k).lower() in low]
        if hits:
            return {
                "rule": str(rule.get("id", "")),
                "dimension": str(rule.get("dimension", "")),
                "guide": str(rule.get("guide", "")),
                "skill": str(rule.get("skill", "")),
                "evidence": "命中关键词 " + "、".join(f"『{h}』" for h in hits[:3]),
            }
    fb = data.get("fallback") or {}
    return {
        "rule": "", "dimension": str(fb.get("dimension", "dimension:unknown")),
        "guide": str(fb.get("guide", "")), "skill": "",
        "evidence": "未命中任何语义类别（需要消息文本或走检索）",
    }

def classify_official_meaning(text: str) -> dict:
    """按**官方含义**命中语义规则（63 号 §3.2；与 classify_error_message 同规则、不同词表）。

    唯一区别：优先用规则的 `match_official` 词表（为**规范措辞**调的），
    现场日志文本仍走 `match`。某条规则没有 `match_official` 时**回退**到 `match`，
    保证既有规则行为不变。返回形状与 classify_error_message 完全一致。
    """
    data = _load_error_semantics()
    low = str(text or "").lower()
    rules = data.get("rules") or []
    # **两遍**：① 官方含义专用词表（措辞更精确，优先）② 回退到现场词表（不漏掉既有覆盖）。
    # 只做一遍会让"有 match_official 的规则"丢掉 match 的覆盖（实测 state_machine 会掉一条）。
    for scope in ("match_official", "match"):
        for rule in rules:
            # 官方路径专属 deny 表（64 号 §4.2）：过泛词（停滞/重启/超时）在**官方措辞**上会误判，
            # 但在**现场日志**上往往是有效信号 ⇒ 只对官方路径生效，match 一个字不动。
            deny = rule.get("match_official_deny") or []
            if any(d and str(d).lower() in low for d in deny):
                continue
            kws = rule.get(scope) or []
            hits = [k for k in kws if k and str(k).lower() in low]
            if hits:
                tag = "官方含义关键词" if scope == "match_official" else "关键词"
                return {
                    "rule": str(rule.get("id", "")),
                    "dimension": str(rule.get("dimension", "")),
                    "guide": str(rule.get("guide", "")),
                    "skill": str(rule.get("skill", "")),
                    "evidence": "命中" + tag + " " + "、".join(f"『{h}』" for h in hits[:3]),
                }
    fb = data.get("fallback") or {}
    return {
        "rule": "", "dimension": str(fb.get("dimension", "dimension:unknown")),
        "guide": str(fb.get("guide", "")), "skill": "",
        "evidence": "官方含义未命中任何语义类别",
    }


# ── 官方码表侧车（62／63 号：码 → 官方含义 → 维度）────────────────────────
# Q27：码**不进本体**。本侧车只在 Tool 层做「码 → 官方含义 → 语义类别」的**入口解析**，
# 出口仍是 dimension:*。**只有 status=统一 的码可信**——官方含义与仓内说法确为同一件事时，
# 据表给维度**不是猜**；区分 / 待现场复核 的码如实落 unknown 并把冲突写出来（不选边）。
_ERROR_CODES: dict | None = None


def _load_error_codes() -> dict:
    """→ {码或 define: 条目}；缺文件 / 坏 YAML / 缺 yaml 库 → 空表（安全侧，落 unknown）。"""
    global _ERROR_CODES
    if _ERROR_CODES is None:
        _ERROR_CODES = {}
        path = Path(__file__).resolve().parent / "error_codes.yaml"
        try:
            import yaml  # 局部导入：与 _load_error_semantics 同理由（不引入加载期强耦合）
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            for e in data.get("dimension_map") or []:
                # 官方表存**数字**（4002），仓内用**负号形态**（-4002）——两种都登记，
                # 与 resolver._error_code_variants 的机械变体口径一致（否则查不到，静默落 unknown）。
                code = str(e.get("code") or "").strip()
                if code:
                    _ERROR_CODES[code] = e
                    _ERROR_CODES.setdefault("-" + code.lstrip("-"), e)
                dfn = str(e.get("define") or "").strip()
                if dfn:
                    _ERROR_CODES.setdefault(dfn, e)
        except Exception:  # noqa: BLE001 —— 缺库/缺文件/坏 YAML 都退化为"无表"（安全侧）
            _ERROR_CODES = {}
    return _ERROR_CODES


_ALIAS_TABLE = None


def _load_alias_table() -> dict:
    """→ {alias(小写): (canonical, scope)}；缺文件 / 坏 YAML → 空表（安全侧）。

    别名机制 v2（43 号 §7 D11）：新增别名只落数据文件 `plugin/aliases.yaml`（带 provenance），
    代码里不再新增别名；码的机械变体由 `Resolver._pattern_code()` 生成，**禁止入表**。
    """
    global _ALIAS_TABLE
    if _ALIAS_TABLE is None:
        _ALIAS_TABLE = {}
        path = Path(__file__).resolve().parent / "aliases.yaml"
        try:
            import yaml  # 局部导入：与 _load_error_codes 同理由（不引入加载期强耦合）
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            for e in data.get("entries") or []:
                alias = str((e or {}).get("alias") or "").strip().lower()
                canonical = str((e or {}).get("canonical") or "").strip()
                if alias and canonical:
                    _ALIAS_TABLE[alias] = (canonical, str((e or {}).get("scope") or "").strip())
        except Exception:
            _ALIAS_TABLE = {}
    return _ALIAS_TABLE


def _official_meaning_for(code: str, conflicts: list) -> dict:
    """裸码 → 官方含义 → 维度（63 号 §3.1 的 status 闸门）。"""
    fb = {"rule": "", "dimension": "dimension:unknown", "guide": "", "skill": "",
          "evidence": "未命中任何语义类别（需要消息文本或走检索）"}
    if not code:
        return fb
    tbl = _load_error_codes()
    ent = (tbl.get(code) or tbl.get(code.lstrip("-"))
           or tbl.get("-" + code.lstrip("-")))
    if not ent:
        return fb
    status = str(ent.get("status") or "")
    dm = str(ent.get("dimension") or "dimension:unknown")
    if status in ("统一", "单源") and dm != "dimension:unknown":
        got = classify_official_meaning(str(ent.get("meaning") or ""))
        if got.get("dimension") == "dimension:unknown":
            got["dimension"] = dm
        if status == "单源":
            got["evidence"] = "单源（厂商文档，未经现场验证）｜" + got.get("evidence", "")
        got["evidence"] = "官方含义『%s』（%s）｜%s" % (
            ent.get("meaning"), ent.get("define"), got.get("evidence"))
        return got
    if status in ("区分", "待现场复核"):
        conflicts.append("%s（%s）：官方含义『%s』与仓内证据不一致——%s" % (
            ent.get("define"), code, ent.get("meaning"), ent.get("note")))
    return fb


# 场景路由规则（Tool 层数据，23 号方案：路由表属延展层，不入 BKN 本体）
# 原 bkn/scenarios/scenario-rules.bkn（已删）迁移至此；修改后 reload 生效。
_SCENARIO_ROUTING_RULES: list[dict] = [
    {"priority": 1, "source_pattern": "same", "target_pattern": "same",
     "file": "objects/scenario-dual-active.bkn", "scenario": "数据库双活", "sub_scenario": "同构同步",
     "description": "同构数据库双活同步", "relation_key": "数据库双活"},
    {"priority": 2, "source_pattern": "*", "target_pattern": "kafka,hive,doris,starrocks",
     "file": "objects/scenario-bigdata-pipeline.bkn", "scenario": "大数据采集分析", "sub_scenario": "大数据入仓",
     "description": "多元异构数据摄取到大数据平台", "relation_key": "大数据采集"},
    {"priority": 3, "source_pattern": "*", "target_pattern": "*",
     "file": "objects/scenario-dual-active.bkn", "scenario": "跨平台迁移", "sub_scenario": "异构迁移",
     "description": "异构数据库在线数据迁移", "relation_key": "跨平台迁移"},
    {"priority": 4, "source_pattern": "*", "target_pattern": "*",
     "file": "objects/scenario-dual-active.bkn", "scenario": "两地三中心", "sub_scenario": "异地容灾",
     "description": "两地三中心灾备同步", "relation_key": "两地三中心"},
]

# 值委托指针表（Tool 层常量，23 号方案）：本体层不持有会随实例/客户/版本增长的值数据，
# 数据下延到 Skill references，本体（Tool）只返回结构化指针，由 Agent 按需加载。
DELEGATIONS: dict[str, dict] = {
    "compatibility": {
        "id": "skill:demo_product-migration-designer",
        "path": "references/compatibility.md",
        "covers": "源端/目标端版本表、数据库对象兼容性、按库特殊约束、SQL Server 三种模式、OS/硬件要求",
    },
    "charset": {
        "id": "skill:demo_product-db-manager",
        "path": "references/charset.md",
        "covers": "字符集规则与各库确认项、脏数据处理",
    },
    "architecture": {
        "id": "skill:demo_product-product-knowledge",
        "path": "references/architecture.md",
        "covers": "三层控制/核心流水线/全量增量原理/Oracle 抽取/事务一致性/比对修复（完整架构正文）",
    },
    "product": {
        "id": "skill:demo_product-product-knowledge",
        "path": "references/product.md",
        "covers": "竞品对比/行业覆盖/信创适配/性能指标/数据源全景",
    },
    "db_checkpoints": {
        "id": "skill:demo_product-db-diagnostics",
        "path": "references/db-checkpoints.md",
        "covers": "进程/维度 × 各库检查点速查",
    },
    "scenario_details": {
        "id": "skill:demo_product-migration-designer",
        "path": "references/scenario-details.md",
        "covers": "场景方案优势对照、需求 → 拓扑选择指南",
    },
    "compare_mechanism": {
        "id": "skill:demo_product-diff-op",
        "path": "references/compare-mechanism.md",
        "covers": "比对机制（快照/排序递归/轨迹库）与修复方式明细",
    },
    "cross_process_logs": {
        "id": "skill:demo_product-log-analyzer",
        "path": "references/cross-process-correlation.md",
        "covers": "跨进程日志关联速查（可能根因 → 需对照日志）",
    },
}

# 值委托类返回值统一的 Qdrant 兜底提示（检索通道，无需归一化）
DELEGATION_QDRANT_HINT = (
    "search_qdrant(query='<问题关键词>', collection='demo_product_collection')；"
    "日志特征类问题可加 collection='log_patterns_collection' + dimension='日志模式'"
)


#: 节名前缀 → 本体使用阶段（P2）。只做**前缀归类**，不改任何取值语义；
#: 未列出的节归 "section_read"（原始事实，不猜）。
_SECTION_STAGES = (
    ("Action:", "action"),
    ("Scenario:", "scenario"),
    ("Dimension:", "dimension"),
    ("Object:", "object"),
    ("Relation:", "relation"),
    ("Risk:", "risk"),
)


def _note_file(rel: str, stage: str, section: str = "") -> None:
    """记一次**文件级**「本次查询按住了这个 .bkn」（P2）。

    与 `_SectionDict._ensure`（节级读点）的分工：部分服务方法直接取整个 section dict
    （不再逐节访问，如 query_product 拿到 data 后只做 in 判定），节级读点抓不到，
    故在「按文件承重」的那一步补一条文件级条目。stage 写成 `load:<服务名>` 以区别节级读取。
    只读、只累积；无作用域/异常一律静默——不改任何返回值。
    """
    try:
        from .observability import ontology_read
        ontology_read(rel, stage="load:%s" % stage, section=section)
    except Exception:
        pass


def _stage_for_section(key: str) -> str:
    """由节的键名推阶段（如 kv/tables 这类惰性解析子键归原阶段）。失败返回 "section_read"。"""
    try:
        for prefix, stage in _SECTION_STAGES:
            if key.startswith(prefix):
                return stage
    except Exception:
        pass
    return "section_read"


class _SectionDict(dict):
    """Section 数据容器：raw 立即存储，tables/kv 首次访问时懒提取 (P2-6)。

    继承 dict，访问接口与旧实现（{"raw","tables","kv"} 完整 dict）完全兼容：
    `sec["tables"]`、`sec.get("kv")`、`"tables" in sec` 等均正常。
    """

    def __init__(self, raw: str, source: str = ""):
        super().__init__({"raw": raw})
        self._raw = raw
        #: 所属 .bkn（仓库相对路径）；_parse 构造时传入。只供本体台账读侧溯源，
        #: 不参与任何取值语义（字典本身仍是懒解析的 kv/tables）。
        self._source = source

    def _ensure(self, key: str):
        # P2 本体台账：直方括号取值与 .get()/.items() 都经过这里，故读点收在这一处
        # （避免同一节被记两次）。只读、只累积；无来源/无作用域时是 no-op。
        if self._source:
            try:
                from .observability import ontology_read
                ontology_read(self._source, stage=_stage_for_section(key), section=key)
            except Exception:
                pass
        if key == "tables" and not dict.__contains__(self, "tables"):
            self["tables"] = BKNResolver._extract_tables(self._raw)
        elif key == "kv" and not dict.__contains__(self, "kv"):
            self["kv"] = BKNResolver._extract_key_values(self._raw)

    def __getitem__(self, key):
        self._ensure(key)
        return super().__getitem__(key)

    def get(self, key, default=None):
        self._ensure(key)
        return super().get(key, default)

    def __contains__(self, key):
        self._ensure(key)
        return super().__contains__(key)

    def items(self):
        self._ensure("tables")
        self._ensure("kv")
        return super().items()


class BKNResolver:
    """BKN 文件加载引擎"""

    def __init__(self, bkn_root: str = None):
        if bkn_root is None:
            bkn_root = str(Path(__file__).resolve().parent.parent / "bkn")
        self.root = Path(bkn_root).expanduser().resolve()
        self.cache: dict[str, dict] = {}
        self._index: dict[str, str] = {}    # section_name → file_path
        self._operations: dict[str, dict] = {}  # capability → action info
        self._scenario_rules: list[dict] = []   # 场景匹配规则缓存
        self._traverser: RelationTraverser | None = None  # O-域图（惰性，批 1-2）
        self._load_all()
        self._load_scenario_rules()

    def _get_traverser(self) -> RelationTraverser:
        """惰性构建关系图遍历器（错误码 → 诊断类 → Skill 路由用）。"""
        if self._traverser is None:
            self._traverser = RelationTraverser(str(self.root))
        return self._traverser

    # ========== 加载 ==========

    def _load_all(self):
        """遍历 bkn/ 加载所有 .bkn 文件（templates/ 目录除外——模板含占位符，非正式内容）"""
        # P2：一次性预热标记——首次 Tool 调用会在此读全量 .bkn，读计数由调用出口聚合成
        # **一条** bkn_load（否则同一次调用的 reads 会被 46 件灌满，反而看不见真实使用）。
        try:
            from .observability import note_cold_load
            note_cold_load(root=Path(self.root).name)
        except Exception:
            pass
        files = sorted(self.root.rglob("*.bkn"))
        for path in files:
            rel = str(path.relative_to(self.root))
            if rel.startswith("templates/"):
                continue
            try:
                from .observability import ontology_read
                ontology_read(rel, stage="cold_load")   # 预热期 → 进 _WARM
            except Exception:
                pass
            self.cache[rel] = self._parse(path)
        self._build_index()

    def _parse(self, path: Path) -> dict:
        """解析 .bkn 文件 → sections dict + raw_lines

        v1.5 (P2-6): tables/kv 懒解析——section 创建时只存 raw，
        首次访问 tables/kv 时才提取（SectionDict 包装，访问接口不变）。
        例外: Action 段的 kv 在 _register_actions 注册时即被消费，会自然触发懒提取。
        """
        text = path.read_text(encoding="utf-8", errors="ignore")
        sections = {}
        current_section = "_head"
        current_lines = []
        for line in text.split("\n"):
            if line.startswith("## ") and not line.startswith("### "):
                sections[current_section] = "\n".join(current_lines)
                current_section = line[3:].strip()
                current_lines = []
            else:
                current_lines.append(line)
        sections[current_section] = "\n".join(current_lines)
        try:
            _rel = str(path.relative_to(self.root))
        except Exception:
            _rel = path.name
        return {name: _SectionDict(content, source=_rel) for name, content in sections.items()}

    # ========== 索引 ==========

    def _build_index(self):
        """构建 section→file 索引 + 操作注册表"""
        for rel, data in self.cache.items():
            for section_name in data:
                self._index[section_name] = rel
            # 注册 Action → capability 映射
            self._register_actions(rel, data)

    def _register_actions(self, rel: str, data: dict):
        """从 actions/*.bkn 提取 capability 信息"""
        for section_name, section_data in data.items():
            if not section_name.startswith("Action:"):
                continue
            kv = section_data.get("kv", {})
            capability = kv.get("capability", "")
            if not capability:
                continue
            aliases_raw = kv.get("aliases", "")
            aliases = [a.strip() for a in re.split(r"[，,]", aliases_raw) if a.strip()]
            info = {"name": section_name.replace("Action: ", ""), "file": rel, **kv}
            info["aliases"] = aliases
            self._operations[capability] = info

    # ========== Object frontmatter (v1.5, P0-6) ==========

    def get_object_meta(self, rel_path: str) -> dict:
        """从 objects/*.bkn 的 _head section 解析 YAML frontmatter 元数据。

        返回 {"name":..., "id":..., "description":..., "aliases":[...], "source_doc":[...]}，
        无 frontmatter 时返回 {}。容错解析：不依赖 yaml 库，逐行处理。
        """
        data = self.cache.get(rel_path)
        if not data:
            return {}
        head = data.get("_head", {}).get("raw", "")
        if not head.startswith("---"):
            return {}
        meta: dict = {}
        current_list_key = None
        in_fm = False
        for line in head.split("\n"):
            stripped = line.strip()
            if stripped == "---":
                if in_fm:
                    break  # frontmatter 结束
                in_fm = True
                continue
            if not in_fm:
                continue
            m = re.match(r"^([a-zA-Z0-9_]+):[ \t]*(.*)$", stripped)
            if m and not stripped.startswith("- "):
                key, val = m.group(1), m.group(2).strip()
                if val:
                    meta[key] = val
                    current_list_key = None
                else:
                    meta[key] = []
                    current_list_key = key
            elif stripped.startswith("- ") and current_list_key:
                item = stripped[2:].strip()
                if item and isinstance(meta.get(current_list_key), list):
                    meta[current_list_key].append(item)
        return meta if meta else {}

    # （21 号 2D）list_object_aliases 已删：生产与测试零消费者（26 号 uses_tool 同款判据）；
    # 别名的规范消费路径是 resolve_synonym + 同址 aliases 字段。

    # ========== 块类型标注 (v1.5, P1-4) ==========

    @staticmethod
    def _parse_section_type(content_before: str, title: str) -> str:
        """解析 section 类型。

        优先取 `## ` 标题前一行的 `<!-- type: xxx -->` 注释；
        无注释时按标题关键词推断，兜底 entity。
        """
        m = re.search(r"<!--[ \t]*type:[ \t]*([a-zA-Z0-9_]+)[ \t]*-->[ \t]*$", content_before)
        if m:
            return m.group(1)
        if title.startswith("Action:"):
            return "action"
        if title.startswith("Relation:"):
            return "relation"
        if title.startswith(("Risk:", "Error:")):
            return "risk"
        if title.startswith("Symptom:"):
            return "symptom"
        return "entity"

    def get_sections_by_type(self, section_type: str) -> list:
        """按类型获取所有文件的 section → [{file, title, type}, ...]"""
        results = []
        for rel in self.cache:
            path = self.root / rel
            if not path.exists():
                continue
            lines = path.read_text(encoding="utf-8", errors="ignore").split("\n")
            for i, line in enumerate(lines):
                if line.startswith("## ") and not line.startswith("### "):
                    title = line[3:].strip()
                    before = lines[i - 1] if i > 0 else ""
                    t = self._parse_section_type(before, title)
                    if t == section_type:
                        results.append({"file": rel, "title": title, "type": t})
        return results

    def get_section_type(self, rel_path: str, section_name: str) -> str:
        """获取指定文件中某 section 的类型（读取源文件精确定位注释）"""
        path = self.root / rel_path
        if not path.exists():
            return "entity"
        lines = path.read_text(encoding="utf-8", errors="ignore").split("\n")
        for i, line in enumerate(lines):
            if line.strip() == f"## {section_name}":
                before = lines[i - 1] if i > 0 else ""
                return self._parse_section_type(before, section_name)
        return "entity"

    # ========== 同义词索引 (v1.5, P1-5) ==========

    def _build_synonym_index(self) -> dict:
        """构建同义词索引 → {同义词(小写): 规范ID/规范名}（批 3-1：同址化）。

        数据源改为**同址字段**（别名与它映射的基点同文件/同段，保证同 chunk 被一起
        召回，见 bkn/SYNONYMS.md 与 16 号方案批 3-1）：

        - 对象：`objects/*.bkn` frontmatter `aliases:`（基点 = frontmatter `id`）
        - 动作：`actions/*.bkn` 段内 `- aliases:`（基点 = `capability`）
        - 症状/维度/错误码：`plugin/constants.py` 值数据常量（25 号自 BKN 锚点表下沉）
        - 组件：`objects/worknode.bkn` 进程矩阵「别名」列（基点 = 进程名首 token）
        - 数据库：`plugin/constants.py::DB_ALIASES`（基点 = 规范库名）

        **运维类（Skill 名）不进索引**：其宿主是各 Skill 的 frontmatter `triggers:`，
        由 Agent 侧的 Skill 选择机制消费，不是 BKN 的规范 ID 空间——原中央表把
        「数据不一致」等业务词覆盖成 skill 名正是这样造成的（test_symptom_synonyms）。
        **错误码规范 ID 空间由边承载**（`suspected_in`）；别名在 `constants.ERROR_ALIASES`，机械变体由代码派生，口语别名走
        `normalize_error_code()` + `_extract_exact_terms()` 的精确命中通道。
        """
        index: dict[str, str] = {}

        def _put(key: str, canonical: str) -> None:
            key = (key or "").strip().lower()
            if key and canonical:
                index.setdefault(key, canonical)

        # ── 对象：frontmatter aliases + name（同址，基点 = id）
        # 24 号：业务对象与进程对象同在 objects/（原 processes/ 已并入；进程识别见 PROCESS_IDS），
        # 别名一律同址于 frontmatter `aliases:`（原 worknode.bkn 进程矩阵「别名」列已删）
        for rel in self.cache:
            if "objects/" not in rel:
                continue
            meta = self.get_object_meta(rel)
            canonical = meta.get("id", "")
            if not canonical:
                continue
            for alias in meta.get("aliases", []) or []:
                _put(alias, canonical)
            _put(meta.get("name", ""), canonical)

        # ── 动作：段内 aliases（同址，基点 = capability）
        for cap, info in self._operations.items():
            for alias in info.get("aliases", []) or []:
                _put(alias, cap)
            _put(info.get("name", ""), cap)

        # ── 症状 / 维度 / 错误码别名（25 号：自 BKN 下沉到 plugin/constants.py 值数据层）
        # 顺序有意为之：症状 → 维度 → 错误码，setdefault 保证「数据差异」这类冲突键归症状。
        for alias, sid in SYMPTOM_ALIASES.items():
            _put(alias, sid)
        for alias, dim in DIMENSION_ALIASES.items():
            _put(alias, dim)
        for alias, code in ERROR_ALIASES.items():
            _put(alias, code)
        # 机械变体（不必写进任何表）：去横杠 / 补横杠 / 去前导零 / ORA 变体 + 4 位数字补负号
        for code in sorted(set(ERROR_ALIASES.values())):
            for variant in self._error_code_variants(code):
                _put(variant, code)

        # ── 场景：objects/scenario-*.bkn「关键词」行（同址，基点 = 场景 ID；24 号加前缀归入 objects/）
        for rel, sec_data in self.cache.items():
            if "objects/" not in rel or "scenario-" not in rel:
                continue
            for sec in sec_data.values():
                kv = sec.get("kv", {})
                sid = (kv.get("场景 ID") or "").strip()
                if not sid:
                    continue
                for alias in re.split(r"[、,，]", kv.get("关键词", "") or ""):
                    _put(alias, sid)

        # ── 数据库：DB_ALIASES + 规范名自映射（已在生产链路，normalize_db 消费）
        for alias, canonical in DB_ALIASES.items():
            _put(alias, canonical)
        for db in KNOWN_DBS:
            _put(db, db)
        for canonical in DB_ALIASES.values():
            _put(canonical, canonical)

        # ── aliases.yaml（别名机制 v2：工具级/口语类别名；数据文件、**yaml 胜出**）
        for alias, (canonical, _scope) in (_load_alias_table() or {}).items():
            if alias and canonical:
                index[alias] = canonical

        return index

    @staticmethod
    def _error_code_variants(code: str) -> list[str]:
        """错误码的机械变体（口语/不规范写法），由规范码派生而非在 BKN 里写死。

        例: `-4073` → `4073` / `错误4073` / `error 4073`；`YAS-02276` → `YAS02276` /
        `YAS-2276` / `2276`；`ORA-01555` → `ORA01555` / `ORA-1555` / `01555`。
        """
        variants: list[str] = []
        code = code.strip()
        if not code:
            return variants
        if code.startswith("-"):
            digits = code[1:]
            variants += [digits, f"错误{digits}", f"error {digits}", f"error{digits}"]
        m = re.match(r"^([A-Za-z]+)-([0-9]+)$", code)
        if m:
            prefix, digits = m.group(1), m.group(2)
            stripped = digits.lstrip("0") or digits
            variants += [f"{prefix}{digits}", f"{prefix}{stripped}", f"{prefix}-{stripped}",
                         stripped, digits, f"错误{digits}", f"错误{stripped}", f"{prefix} {digits}"]
        return variants

    # ---------- mention 解析管线（别名机制 v2；43 号 §7 D11） ----------
    #: L1 形态：像错误码的输入（码的机械变体由模式生成，不写表）
    _CODE_FORMS = (
        re.compile(r"^-?[0-9]{3,6}$"),
        re.compile(r"^错误[ ]*-?[0-9]{3,6}$"),
        re.compile(r"^(?:error|err)[ ]*-?[0-9]{3,6}$", re.IGNORECASE),
        re.compile(r"^[A-Za-z]{2,6}-?[0-9]{2,6}$"),
    )

    def _canonical_ids(self) -> set[str]:
        """L0：已是规范 ID 的集合（症状 / 维度 / 进程 / 错误码 / 对象）。惰性构建一次。"""
        cached = getattr(self, "_canonical_cache", None)
        if cached is not None:
            return cached
        ids: set[str] = set()
        try:
            ids.update(str(v) for v in SYMPTOM_ALIASES.values() if v)
            ids.update(str(v) for v in DIMENSION_ALIASES.values() if v)
            ids.update(str(v) for v in PROCESS_IDS if v)
        except Exception:
            pass
        try:
            ids.update(str(k) for k in (_load_error_codes() or {}).keys())
        except Exception:
            pass
        try:
            for rel in self.cache:
                if "objects/" not in rel:
                    continue
                oid = (self.get_object_meta(rel) or {}).get("id")
                if oid:
                    ids.add(str(oid))
        except Exception:
            pass
        cached = {x.strip().lower() for x in ids if x and x.strip()}
        self._canonical_cache = cached
        return cached

    def _pattern_code(self, text: str) -> str | None:
        """L1：把「像码」的输入按形态归一到规范形态，并用生成侧车 `error_codes.yaml` 校验存在性。

        码空间是**可生成**的（官方表由 Excel 生成）⇒ 一条 per-code 别名都不该写。
        """
        s = (text or "").strip()
        if not s or not any(p.match(s) for p in self._CODE_FORMS):
            return None
        cands: list[str] = []
        norm = self.normalize_error_code(s)
        if norm != s:
            cands.append(norm)
        m = re.match(r"^错误[ ]*-?([0-9]{3,6})$", s)
        if m:
            cands.append("-" + m.group(1))
        m = re.match(r"^(?:error|err)[ ]*-?([0-9]{3,6})$", s, re.IGNORECASE)
        if m:
            cands.append("-" + m.group(1))
        m = re.match(r"^([A-Za-z]{2,6})-?([0-9]{2,6})$", s)
        if m:
            prefix, digits = m.group(1).upper(), m.group(2)
            cands += [f"{prefix}-{digits}", f"{prefix}{digits}"]
        try:
            table = _load_error_codes() or {}
        except Exception:
            table = {}
        for c in cands:
            if c in table or c.lstrip("-") in table or ("-" + c.lstrip("-")) in table:
                return c
        if norm.startswith("ORA-"):  # ORA 家族：沿用 normalize_error_code 的历史口径
            return norm
        return None

    def resolve_mention(self, text: str, *, kind: str = "") -> tuple[str, str]:
        """把一次「提到的东西」解析成 (canonical, path)。

        path ∈ canonical（已是规范 ID）/ pattern（码的机械形态，侧车已校验）/ alias（同址别名或
        aliases.yaml）/ unknown（无匹配，原样返回）。**不改变** `resolve_synonym()` 的返回值语义。
        """
        raw = (text or "").strip()
        if not raw:
            return text, "unknown"
        low = raw.lower()
        # L2 先查：同址别名 / aliases.yaml 的既有返回值语义原样保留（4073 → -4073 这类）
        if not hasattr(self, "_synonym_index"):
            self._synonym_index = self._build_synonym_index()
        hit = self._synonym_index.get(low)
        if hit is not None:
            return hit, "alias"
        # L0 幂等：已是规范 ID（症状/维度/进程/错误码/对象）→ 原样返回，不再误记缺口
        if low in self._canonical_ids():
            return raw, "canonical"
        # L1 形态：码的机械变体（由侧车校验，不写表）
        code = self._pattern_code(raw)
        if code:
            return code, "pattern"
        return raw, "unknown"

    def _note_mention(self, mention: str, path: str, canonical: str = "") -> None:
        """记一条 mention 解析事件（`mention_resolve`）；无调用作用域/超上限时静默。"""
        try:
            from .observability import track_mention
            track_mention(mention, path, canonical)
        except Exception:
            pass

    def resolve_synonym(self, text: str) -> str:
        """解析同义词 → 规范 ID/名；无匹配原样返回（薄壳：内部走 `resolve_mention`）。"""
        if not text:
            return text
        canonical, path = self.resolve_mention(text)
        self._note_mention(text.strip(), path, canonical)
        if path == "unknown":
            # P2：只有**真正未命中**的「像标识」输入才记缺口（已规范 ID / 码形态不再误报）。
            try:
                from .observability import _is_ident, ontology_drop
                if _is_ident(text.strip()):
                    ontology_drop(text.strip(), "synonym_miss")
            except Exception:
                pass
            return text
        return canonical if path == "alias" else text

    @staticmethod
    def normalize_error_code(code: str) -> str:
        """规范化错误码格式: 4073 → -4073; ORA01555/ora-1555 → ORA-01555"""
        code = (code or "").strip()
        if re.match(r"^[0-9]{4}$", code):
            return f"-{code}"
        m = re.match(r"^ORA-?([0-9]{4,5})$", code, re.IGNORECASE)
        if m:
            return f"ORA-{m.group(1).zfill(5)}"
        return code

    # ========== 解析工具 ==========

    @staticmethod
    def _extract_tables(text: str) -> list[dict]:
        """提取 Markdown 表格 → list[dict]"""
        tables = []
        lines = text.split("\n")
        i = 0
        while i < len(lines):
            if "|" in lines[i] and "---" in (lines[i + 1] if i + 1 < len(lines) else ""):
                header = [h.strip() for h in lines[i].split("|") if h.strip()]
                i += 2
                rows = []
                while i < len(lines) and "|" in lines[i]:
                    cells = [c.strip() for c in lines[i].split("|") if c.strip()]
                    if len(cells) == len(header):
                        rows.append(dict(zip(header, cells)))
                    i += 1
                tables.append({"header": header, "rows": rows})
            else:
                i += 1
        return tables

    @staticmethod
    def _extract_key_values(text: str) -> dict[str, str]:
        """提取 key: value 和 - key: value 行 (支持中文 key)"""
        kv = {}
        for line in text.split("\n"):
            line = line.strip()
            # key 排除 markdown 特殊符号, 支持中英文、数字、下划线
            m = re.match(r"^-?[ \t]*([^:\n>|# \t\n\r\f\v][^:\n]*?)[ \t]*:[ \t]*(.+)", line)
            if m:
                kv[m.group(1).strip()] = m.group(2).strip()
        return kv

    # ========== 查询接口 ==========

    def load(self, file_name: str) -> dict:
        """加载指定文件的全部 sections"""
        return self.cache.get(file_name, {})

    def get_section(self, section_name: str) -> dict | None:
        """按 section 名查找（跨文件索引）"""
        file_name = self._index.get(section_name)
        if file_name:
            return self.cache[file_name].get(section_name)
        return None

    @staticmethod
    def _delegation(key: str, **extra) -> dict:
        """值委托指针（23 号方案）：{id, path, covers, qdrant_hint} + 附加说明。"""
        ptr = {**DELEGATIONS[key], "qdrant_hint": DELEGATION_QDRANT_HINT}
        ptr.update(extra)
        return ptr

    def query_product(self, aspect: str = "overview") -> dict:
        """查询 objects/product.bkn（本体层：定位 / 核心能力 / 适用场景）。

        23 号方案：竞品对比/行业覆盖/信创适配/性能指标/数据源全景**已下延** Skill
        references（值数据会随客户/竞品/版本增长），本体侧返回结构化指针。
        """
        _note_file("objects/product.bkn", "product", "产品定位/核心能力/适用场景")
        data = self.load("objects/product.bkn")
        section_map = {
            "overview": "产品定位",
            "positioning": "产品定位",
            "advantages": "核心能力",
            "core_capabilities": "核心能力",
            "scenarios": "适用场景",
        }
        # 已下延 aspect → 指针（不再返回空段）
        _delegated = {
            "competitors": ("product", "竞品对比"),
            "industries": ("product", "行业覆盖"),
            "xinchuang": ("product", "信创适配"),
            "performance": ("product", "性能指标"),
            "sources": ("product", "数据源全景"),
            "etl_compare": ("product", "与传统 ETL 对比"),
        }
        if aspect == "all":
            sections = {k: v for k, v in data.items() if k != "_head"}
            pointer_line = (
                "> 23 号方案：竞品对比/行业覆盖/信创适配/性能指标/数据源全景已下延 "
                "`skill:demo_product-product-knowledge/references/product.md`（值委托）。"
            )
            combined_raw = "\n\n".join(
                sec.get("raw", "") for sec in sections.values() if isinstance(sec, dict)
            ) + "\n\n" + pointer_line
            sections["raw"] = combined_raw
            sections["delegated_to"] = [self._delegation("product")]
            return sections
        if aspect in _delegated:
            key, cn = _delegated[aspect]
            # 先试本体是否仍有该段（兼容期），无则返回指针
            for sec_name, sec_data in data.items():
                if cn in sec_name:
                    return sec_data
            return {
                "aspect": aspect,
                "delegated_to": [self._delegation(key, reason=f"「{cn}」不在本体层（23 号：值数据下延）")],
                "note": f"本体层只保留产品定义（定位/核心能力/适用场景）；「{cn}」见上述 Skill 引用，"
                        "或按 qdrant_hint 检索兜底。",
            }
        target = section_map.get(aspect, "产品定位")
        for sec_name, sec_data in data.items():
            if target in sec_name:
                return sec_data
        return {}

    def _iter_process_ids(self) -> list[str]:
        """本体层进程注册集（24 号：以 `constants.PROCESS_IDS` 为准，文件在 `objects/<id>.bkn`）。

        目录不再是语义信号——原 `processes/` 已并入 `objects/`，进程识别靠注册集常量；
        只返回实际存在对应对象文件的进程（缺失即视为未登记）。
        """
        ids = []
        for pid in PROCESS_IDS:
            if self.load(f"objects/{pid}.bkn"):
                ids.append(f"process:{pid}")
        return sorted(ids)

    def _derive_data_flow(self) -> tuple[list[str], list[str], list[str]]:
        """从 relations/process_topology.bkn 派生数据流/生命周期/控制面边（本体派生，投影为文本边）。"""
        t = self._get_traverser()
        data_flow, lifecycle, control = [], [], []
        for pid in self._iter_process_ids():
            for tgt in t.get_targets(pid, "feeds"):
                data_flow.append(f"{pid} --feeds--> {tgt}")
            for tgt in t.get_targets(pid, "supervises"):
                lifecycle.append(f"{pid} --supervises--> {tgt}")
            for tgt in t.get_targets(pid, "monitors"):
                control.append(f"{pid} --monitors--> {tgt}")
        return data_flow, lifecycle, control

    def query_architecture(self, topic: str) -> dict:
        """查询架构主题（23 号方案：本体派生 + 值委托指针）。

        `architecture.bkn` 已删除——可抽象的部分**抽象上升**为进程对象的属性与 topology 边
        （由 `objects/*.bkn` 进程对象 + `relations/process_topology.bkn` 边派生）；完整原理正文（叙述类）**下延**
        `skill:demo_product-product-knowledge/references/architecture.md`。
        """
        data_flow, lifecycle, control = self._derive_data_flow()
        proc_lines = []
        for pid in self._iter_process_ids():
            attrs = self.get_process_attrs(pid)
            proc_lines.append(
                f"- {pid}（{attrs.get('角色', '')} / {attrs.get('语言', '')} / "
                f"频度 {attrs.get('排查频度', '')}）: 日志 {attrs.get('日志标识', '')}"
            )
        if topic == "all":
            raw = "\n".join([
                "## 进程对象与拓扑（本体派生）",
                *proc_lines,
                "",
                "## 数据流边（feeds）",
                *[f"- {e}" for e in data_flow],
                "",
                "## 生命周期边（supervises）",
                *[f"- {e}" for e in lifecycle],
                "",
                f"> 完整架构正文（三层控制/核心流水线/初始化全同步/实时增量/Oracle 抽取/事务一致性/"
                f"比对修复）见 {DELEGATIONS['architecture']['id']} 的 "
                f"`{DELEGATIONS['architecture']['path']}`（值委托，23 号方案）。",
            ])
            return {
                "topic": "all",
                "raw": raw,
                "processes": proc_lines,
                "data_flow": data_flow,
                "lifecycle": lifecycle,
                "delegated_to": [self._delegation("architecture")],
                "note": "本体层给进程骨架与拓扑边；原理叙述与逐库实现要点按 delegated_to 加载。",
            }
        # 主题 → 本体可派生部分（feeds 链）/ 值委托章节
        entry_map = {"full_sync": "process:iadumper", "incremental_sync": "process:iatrack"}
        if topic in entry_map:
            chain = self.get_process_chain(entry_map[topic])
            raw = "\n".join([
                f"## {topic} 链路（本体派生：feeds 边）",
                *[f"- {c['process']}（{c['role']}）: {c['log']}；自证性={c['self_sufficient']}"
                  for c in chain],
                f"> 机制细节（抽取/解析/装载各阶段原理）见 "
                f"{DELEGATIONS['architecture']['path']}（值委托）。",
            ])
            return {
                "topic": topic,
                "raw": raw,
                "entry": entry_map[topic],
                "chain": chain,
                "data_flow": [e for e in data_flow if entry_map[topic] in e],
                "delegated_to": [
                    self._delegation(
                        "architecture",
                        reason=f"{topic} 的机制叙述不在本体层",
                        sections=("初始化全同步原理" if topic == "full_sync" else "实时增量同步原理"),
                    )
                ],
                "note": "链路结构由进程对象与 feeds 边派生（本体层）；阶段机制见 delegated_to。",
            }
        if topic == "topology":
            raw = "\n".join([
                "## 部署与进程拓扑（本体派生）",
                *[f"- {e}" for e in lifecycle + control],
                f"> 部署架构（控制机/工作节点/端口）见 {DELEGATIONS['architecture']['path']}（值委托）。",
            ])
            return {
                "topic": topic,
                "raw": raw,
                "lifecycle": lifecycle,
                "control": control,
                "delegated_to": [self._delegation("architecture", reason="端口/部署点位明细")],
            }
        # 其余主题：直接给指针（章节名映射到 Skill 引用内的标题）
        section_map = {
            "transaction": "事务一致性保障",
            "validation": "数据比对和修复机制",
            "performance": None,
            "oracle_log": "Oracle 抽取与日志配置",
            "mssql_mode": "SQL Server 三种模式对比",
            "matrix": "原理矩阵：15 种数据库",
        }
        if topic in section_map:
            section = section_map[topic]
            if topic == "mssql_mode":
                # SQL Server 三种模式：本体层保留「随库差异」指针级事实 + Skill 对照表
                return {
                    "topic": topic,
                    "raw": "> SQL Server 三种部署模式（开 CDC / 开发布订阅 / 全都不开）约束对照已下延 "
                           "`skill:demo_product-migration-designer/references/compatibility.md`（值委托）；"
                           "本体侧仅登记「三种模式」这一事实（`bkn/objects/database.bkn` MSSQLSource 段）。",
                    "delegated_to": [self._delegation("compatibility", reason="SQL Server 三种模式约束表")],
                }
            return {
                "topic": topic,
                "raw": f"> 「{section}」不在本体层（叙述类，23 号方案下延）——见 "
                       f"{DELEGATIONS['architecture']['path']}。",
                "delegated_to": [self._delegation("architecture", sections=section)],
            }
        return {}

    def match_scenario(self, source: str, target: str) -> dict:
        """基于 BKN 规则匹配 L3 场景"""
        default = {
            "scenario": "跨平台迁移",
            "sub_scenario": "异构迁移",
            "file": "objects/scenario-dual-active.bkn",
            "description": "异构数据库在线数据迁移",
            "relation_key": "跨平台迁移",
        }
        if not self._scenario_rules:
            return default

        for rule in self._scenario_rules:
            src_pat = rule["source_pattern"]
            tgt_pat = rule["target_pattern"]
            matched = False
            if src_pat == "same" and tgt_pat == "same":
                matched = is_db_match(source, target) and is_db_match(target, source)
            elif src_pat == "same":
                matched = is_db_match(source, target) and self._match_scenario_pattern(target, tgt_pat)
            elif tgt_pat == "same":
                matched = self._match_scenario_pattern(source, src_pat) and is_db_match(target, source)
            else:
                matched = (
                    self._match_scenario_pattern(source, src_pat)
                    and self._match_scenario_pattern(target, tgt_pat)
                )
            if matched:
                return {
                    "scenario": rule["scenario"],
                    "sub_scenario": rule["sub_scenario"],
                    "file": rule["file"],
                    "description": rule["description"],
                    "relation_key": rule["relation_key"],
                }
        return default

    def match_scenario_by_name(self, scenario_name: str, source: str, target: str) -> dict:
        """按场景名匹配规则；未命中时返回默认跨平台迁移。"""
        default = self.match_scenario(source, target)
        if not self._scenario_rules:
            return default
        for rule in self._scenario_rules:
            if rule.get("scenario") == scenario_name:
                src_pat = rule["source_pattern"]
                tgt_pat = rule["target_pattern"]
                matched = False
                if src_pat == "same" and tgt_pat == "same":
                    matched = is_db_match(source, target) and is_db_match(target, source)
                elif src_pat == "same":
                    matched = is_db_match(source, target) and self._match_scenario_pattern(target, tgt_pat)
                elif tgt_pat == "same":
                    matched = self._match_scenario_pattern(source, src_pat) and is_db_match(target, source)
                else:
                    matched = (
                        self._match_scenario_pattern(source, src_pat)
                        and self._match_scenario_pattern(target, tgt_pat)
                    )
                if matched:
                    return {
                        "scenario": rule["scenario"],
                        "sub_scenario": rule["sub_scenario"],
                        "file": rule["file"],
                        "description": rule["description"],
                        "relation_key": rule["relation_key"],
                    }
        return default

    @staticmethod
    def _find_table_in_section(data: dict, section_name: str, table_index: int = 0) -> dict | None:
        """从 BKN 解析结果中提取指定 section 的第 N 个表格"""
        section = data.get(section_name, {})
        tables = section.get("tables", [])
        if 0 <= table_index < len(tables):
            return tables[table_index]
        return None

    @staticmethod
    def _match_db_row(rows: list[dict], col_name: str, candidate: str) -> dict | None:
        """在表格行中按数据库名匹配候选值"""
        for row in rows:
            db = row.get(col_name, "")
            if is_db_match(candidate, db):
                return row
        return None

    def _build_db_constraints(self, source: str, target: str) -> list[str]:
        """按库特殊约束 → 值委托指针（23 号方案）。

        原 `compatibility.bkn`「按库特殊约束」表随值数据下延
        `skill:demo_product-migration-designer/references/compatibility.md`；此处只给指针行。
        """
        hits = [db for db in (source, target) if db and any(is_db_match(db, k) for k in KNOWN_DBS)]
        if not hits:
            return []
        return [f"{'、'.join(hits)} 按库特殊约束: 见 {DELEGATIONS['compatibility']['id']} 的 "
                f"{DELEGATIONS['compatibility']['path']}（值委托，23 号方案）"]

    def _build_charset_notes(self, source: str, target: str) -> dict:
        """字符集说明 → 值委托指针（23 号方案）。

        原 `objects/env_matrix.bkn`「字符集速查」随值数据下延
        `skill:demo_product-db-manager/references/charset.md`。
        """
        return {
            "delegated_to": self._delegation(
                "charset",
                reason=f"字符集规则与 {source or '源端'}/{target or '目标端'} 确认项不在本体层",
            ),
        }

    def _bkn_db_facts(self, db: str) -> dict:
        """本体侧 DB 对象事实（objects/database.bkn 的 `Object: <DB>Source` 段）。

        只取定义性 KV（标识/数据库类型/全量方式/增量方式/部署模式要点），
        逐库版本下限/对象兼容/DDL 对照等值数据不在本体层。
        """
        if not db:
            return {}
        data = self.load("objects/database.bkn")
        keep = ("标识", "数据库类型", "全量方式", "增量方式", "三种部署模式", "特殊", "原理")
        for sec_name, sec_data in data.items():
            if not sec_name.startswith("Object:"):
                continue
            obj_db = sec_name.removeprefix("Object:").removesuffix("Source").strip()
            if not (is_db_match(db, obj_db) or is_db_match(obj_db, db)):
                continue
            kv = sec_data.get("kv", {}) if isinstance(sec_data, dict) else {}
            facts: dict = {}
            for k, v in kv.items():
                key = k.strip().strip("*").strip()
                if key in keep:
                    facts[key] = v.strip().strip("`").strip()
            facts["_source"] = "bkn:objects/database.bkn#" + sec_name
            return facts
        return {}

    def check_compatibility(self, source: str, target: str,
                            source_version: str = None, target_version: str = None) -> dict:
        """兼容性查询（23 号方案：本体派生注册集判定 + 值委托指针）。

        保留（本体可判）：`supported`（KNOWN_DBS 注册集）+ 本体侧 DB 对象事实（`bkn_db_facts`）。
        下延（值数据）：源端/目标端版本下限、数据库对象兼容性、按库特殊约束、字符集规则
        → `delegated_to` 指针 + Qdrant 兜底提示。
        """
        s_match = any(is_db_match(source, db) for db in KNOWN_DBS)
        t_match = any(is_db_match(target, db) for db in KNOWN_DBS)

        delegated = [
            self._delegation(
                "compatibility",
                reason="版本表/对象兼容性/按库约束/SQL Server 三种模式不在本体层（值数据）",
            ),
            self._delegation(
                "charset",
                reason="字符集规则与各库确认项不在本体层（值数据）",
            ),
        ]
        risks = self._build_db_constraints(source, target)

        return {
            "supported": s_match and t_match,
            "source": source,
            "target": target,
            "source_version": source_version,
            "target_version": target_version,
            "bkn_db_facts": {
                "source": self._bkn_db_facts(source),
                "target": self._bkn_db_facts(target),
            },
            "version_notes": {
                "delegated": True,
                "reason": "源端/目标端支持版本与验证版本为值数据（随版本发布增长），23 号下延",
            },
            "object_compat": [],
            "charset_notes": self._build_charset_notes(source, target),
            "delegated_to": delegated,
            "qdrant_hint": DELEGATION_QDRANT_HINT,
            "risks": risks,
            "note": "本体层只能判定「是否受支持」（注册集）与 DB 对象定义事实；"
                    "版本/对象兼容/字符集明细按 delegated_to 加载 Skill 引用，或按 qdrant_hint 检索兜底。",
        }

    @staticmethod
    def _code_boundary_match(code: str, text: str) -> bool:
        """边界感知的错误码匹配: 前后不能是字母/数字/_/-, 避免 -407 命中 -4073"""
        if not code or not code.strip():
            return False
        # 使用显式字符类 [a-zA-Z0-9_] 替代 word-character 简写, 兼容底层 re 分类异常的 Python 构建
        boundary = r"[a-zA-Z0-9_-]"
        pattern = re.compile(rf"(?<!{boundary}){re.escape(code)}(?!{boundary})")
        return bool(pattern.search(text))

    def get_risk(self, error_code: str, message: str = "", log_source: str = "") -> dict:
        """错误码诊断指引（32 号：**码只作入口，含义进推理链**）。

        链路：码(+消息文本) → 语义类别（`error_semantics.yaml` 的**有界规则**，按文本命中、可溯依据）
             → 本体推理：`dimension --diagnosed_by--> skill`、`dimension --observed_in--> log`
             → 嫌疑进程：**只在给出 `log_source` 时**直接取它（哪个进程的日志出现该码）；
               未给出则**不猜**（空列表 + 在 `needs` 里明说要什么）。

        返回键与 21/25 号对齐（旧消费者无需改）：`error_code` / `retrieval_guide` /
        `suspected_process` / `dimensions` / `aliases` / `unknown_rule`；
        新增 `meaning`（命中了哪条规则、依据）/ `diagnosed_skills` / `observed_logs` / `needs`。

        为什么不再"按码查表"：错误码空间无上界（用户裁定 Q27）——码只作入口，不在任何一层穷举；
        见 `doc/build/demo_product-bkn/02-bkn_design_philosophy.md` §0 与 32 号。
        """
        clean_code = (error_code or "").strip().removeprefix("error:").strip()
        if not clean_code and not message:
            return {}
        aliases = [a for a, c in ERROR_ALIASES.items() if c == clean_code] if clean_code else []
        traverser = self._get_traverser()
        conflicts: list = []
        if message:
            meaning = classify_error_message(message)
            meaning_source = "message"
        else:
            # 【63 号】裸码走官方含义（仅 status=统一 的码可信；其余落 unknown ＋ 冲突说明）
            meaning = _official_meaning_for(clean_code, conflicts)
            meaning_source = "code"
        dim = meaning["dimension"]
        # P3：diagnose_error（真实流量第一热点）的**诊断轴**——拿到的维度是真实语义类别
        # 还是兜底的 dimension:unknown，是「本体到底接上没有」最直接的一条证据；
        # 紧邻它的 diagnosed_by / observed_in 两条边则给出「接上后走到了哪些 Skill/日志」。
        try:
            from .observability import ontology_graph_branch
            ontology_graph_branch("dim_known"
                                  if dim and dim != "dimension:unknown" else "dim_unknown")
        except Exception:
            pass
        skills = traverser.get_targets(dim, "diagnosed_by") if dim else []
        logs = traverser.get_targets(dim, "observed_in") if dim else []
        processes: list[str] = []
        if log_source:
            processes = [log_source if log_source.startswith("process:") else f"process:{log_source}"]
        needs = []
        if not message:
            if meaning_source == "code" and dim != "dimension:unknown":
                needs.append("已据官方含义给出类别；补该码的**日志消息文本**可进一步确认现场语义")
            else:
                needs.append("该码所在的**日志消息文本**（语义规则按文本命中；只给码且无可信官方含义时定不了含义）")
        if not processes:
            needs.append("**日志来源**（该码出现在哪个进程的日志——给出即可确定嫌疑进程）")
        return {
            "error_code": clean_code,
            "meaning": meaning,
            "meaning_source": meaning_source,
            "conflicts": conflicts,
            "dimensions": [dim] if dim else [],
            "diagnosed_skills": skills,
            "observed_logs": logs,
            "suspected_process": processes,
            "retrieval_guide": DIAG_RETRIEVAL_GUIDE,
            "aliases": aliases,
            "unknown_rule": ("含义未识别或未给消息文本 → ①带消息文本重问 ②search_qdrant 检索模式库"
                             "（store:log_patterns_collection）③记 gap_log 走缺口闭环"),
            "needs": needs,
        }

    @staticmethod
    def _manifest_skill_capabilities(names: list[str]) -> str:
        """关联 Skill 的能力概要（Skill 层 manifest，值委托；23 号方案）。"""
        from .manifest import resolve_skill_id
        lines = []
        for n in names:
            item = resolve_skill_id(f"skill:{n}") or {}
            cap = item.get("capability", "")
            if cap:
                lines.append(f"- {n}: {cap}")
        return "\n".join(lines)

    def _analysis_framework_for(self, processes: list[str]) -> str:
        """本体派生的排查框架（23 号方案，替代原 symptom-router「分析思路」段）。

        组成：嫌疑进程链（feeds）× 各进程「日志自证性」× 检索源顺序（get_evidence_sources）。
        """
        if not processes:
            return ""
        chain = self.get_process_chain(processes[0])
        parts = ["对象轴排查框架（本体派生）："]
        for c in chain:
            pid = c["process"]
            suffix = " → 需与链上其他进程对照时间线" if "需关联" in c.get("self_sufficient", "") else ""
            parts.append(f"{pid}（{c.get('role', '')}，日志 {c.get('log', '')}）{suffix}")
        sources = self.get_evidence_sources(processes[0])
        if sources:
            parts.append("检索源顺序: " + " → ".join(sources))
        return "\n".join(parts)

    def get_symptom_skills(self, key: str) -> dict[str, Any]:
        """根据症状或错误码提取 required/optional Skill 列表、分析思路（21/23 号方案对象轴）。

        症状/错误码 → suspected_in → 进程关联 Skill（objects/*.bkn 各进程对象「关联」段的 skill 引用，
        由 relations/process_topology.bkn 的 suspected_in 边承载）；跨切面回退 has_class → dimension
        diagnosed_by。分析思路/能力概要均为本体与 manifest 派生（23 号：原 symptom-router 段已下延）。

        返回结构:
            {
                "required": [{"name": "...", "reason": "..."}, ...],
                "optional": [{"name": "...", "reason": "..."}, ...],
                "analysis_framework": "...",
                "skill_capabilities": "...",
            }
        未命中时 fallback 到默认 diagnostic skill。
        """
        key = (key or "").strip()
        if not key:
            return self._fallback_symptom_skills()

        # 21 号方案：症状/错误码统一走 suspected_in → 进程 Skill（入口文件锚点仅做归一，
        # 不再维护逐症状 Skill 块——Skill 由进程对象「关联」段承载）
        # 裸名判定：数字/`-` 开头 → 错误码；否则 → 症状（现场说法 → 锚点归一）
        if ":" in key:
            node = key
        elif key[0].isdigit() or key.startswith("-"):
            node = f"error:{key}"
        else:
            node = f"symptom:{key}"
        processes = self._get_traverser().get_targets(node, "suspected_in")
        if processes:
            required = []
            seen: set[str] = set()
            for pid in processes:
                for name in self.get_process_skills(pid):
                    if name not in seen:
                        seen.add(name)
                        required.append({"name": name, "reason": f"进程 {pid} 关联（objects/*.bkn 进程对象）"})
            if required:
                names = [s["name"] for s in required]
                return {
                    "required": required,
                    "optional": [],
                    "analysis_framework": self._analysis_framework_for(processes),
                    "skill_capabilities": self._manifest_skill_capabilities(names),
                    "analysis_source": "bkn:objects/*.bkn（进程对象派生：进程链/日志自证性/检索源）",
                    "capabilities_source": "manifest:plugin/skill_manifest.yaml（Skill 层能力概要）",
                }
        # 错误码入参（带 error: 前缀）走对象轴 Skill（suspected_in → 进程）
        if node.startswith("error:"):
            graph_result = self._skills_for_error_code(node.removeprefix("error:"))
            if graph_result is not None:
                return graph_result
        return self._fallback_symptom_skills()

    def _skills_for_error_code(self, code: str) -> "dict[str, Any] | None":
        """错误码 → 嫌疑进程（suspected_in 边）→ 进程 Skill（20 号方案对象轴）。

        对象轴优先：错误码 → suspected_in → process:* → 进程对象「关联」段的 skill 引用。
        过渡期回退：suspected_in 未命中时走 has_class → diagnosed_by（保留一个版本周期，
        见 20 号方案 §4.2）。分析思路/能力概要为本体与 manifest 派生（23 号）。
        码未登记返回 None，由调用方走 fallback。
        """
        traverser = self._get_traverser()
        # 对象轴：suspected_in 边（全量覆盖 15 错误码）
        processes = traverser.get_targets(f"error:{code}", "suspected_in")
        if processes:
            # P3：diagnose_error 的诊断轴（真实流量第一热点）——走的是**对象轴**而非兜底类轴
            try:
                from .observability import ontology_graph_branch
                ontology_graph_branch("object_axis")
            except Exception:
                pass
            required = []
            seen: set[str] = set()
            for pid in processes:
                for name in self.get_process_skills(pid):
                    if name not in seen:
                        seen.add(name)
                        required.append({"name": name, "reason": f"进程 {pid} 关联（objects/*.bkn 进程对象）"})
            if required:
                names = [s["name"] for s in required]
                return {
                    "required": required,
                    "optional": [
                        BKNResolver._manifest_skill("skill:bkn-plugin", "补查错误码上下文（diagnose_error）")
                    ],
                    "analysis_framework": self._analysis_framework_for(processes),
                    "skill_capabilities": self._manifest_skill_capabilities(names),
                    "analysis_source": "bkn:objects/*.bkn（进程对象派生：进程链/日志自证性/检索源）",
                    "capabilities_source": "manifest:plugin/skill_manifest.yaml（Skill 层能力概要）",
                    "diag_class": processes[0],
                }
        # 过渡期回退：has_class → diagnosed_by（20 号方案 §4.2，保留一个版本周期）
        # P3：本条标记 = 本体**没能走对象轴**，退到跨切面类轴（「本体没接上」的直接证据）
        try:
            from .observability import ontology_graph_branch
            ontology_graph_branch("class_fallback")
        except Exception:
            pass
        classes = traverser.get_classes_for_symptom(f"error:{code}")
        if not classes:
            return None
        class_id = classes[0]  # has_class 为 N:1
        required = [
            {"name": name, "reason": f"诊断类 {class_id} 路由（diagnosed_by 边）"}
            for name in traverser.get_skills_for_class(class_id)
        ]
        # 分析思路：25 号起为「检索指引常量 + 维度边」（原锚点表已删）
        dims = traverser.get_targets(f"error:{code}", "has_class")
        analysis = f"诊断指引：完整定义查 {DIAG_RETRIEVAL_GUIDE}"
        if dims:
            analysis += f"；跨切面维度 {'、'.join(dims)}"
        names = [s["name"] for s in required]
        return {
            "required": required,
            "optional": [
                BKNResolver._manifest_skill("skill:bkn-plugin", "补查错误码上下文（diagnose_error）")
            ],
            "analysis_framework": analysis,
            "skill_capabilities": self._manifest_skill_capabilities(names),
            "analysis_source": f"bkn:relations/process_topology.bkn#suspected_in + constants.DIAG_RETRIEVAL_GUIDE（{DIAG_RETRIEVAL_GUIDE}）",
            "capabilities_source": "manifest:plugin/skill_manifest.yaml（Skill 层能力概要）",
            "diag_class": class_id,
        }

    def get_evidence_sources(self, class_id: str) -> list[str]:
        """读取诊断目标的「检索源」有序列表（批 6-2 字段，18 号方向三元组的「查哪」）。

        返回 store:xxx 有序列表（先查哪个集合/维度、后查哪个）；无字段返回 []。
        与 observed_in 边（日志查看顺序）统一为「证据源顺序」口径。
        21 号方案：入参为 `process:*`（对象轴）或 `dimension:*`（跨切面维度）。

        38 号批 1（37 号 §3-C1）：分支表**收拢到 `constants.EVIDENCE_SOURCES` 单点**——
        本方法退化为纯查表（返回值与收敛前逐字一致，5 个调用点行为不变）；
        `class:` 等其它前缀显式返回 []（原实现即落入末行 `return []` 的死分支，现写明）。
        """
        if not class_id:
            return []
        hit = EVIDENCE_SOURCES.get(class_id)
        if hit:
            return list(hit)
        if class_id.startswith("process:") or class_id.startswith("dimension:"):
            return list(EVIDENCE_SOURCES_DEFAULT)
        return []

    def get_log_map(self, symptom: str = "") -> dict:
        """症状 → 日志导航（23 号方案：**本体派生**，不再解析导航表）。

        派生链：症状/错误码 → `suspected_in` 边 → 嫌疑进程 → 进程链（`feeds` 边）
        → 各进程「关键属性」的日志标识/频度/自证性。
        `primary` = 首选嫌疑进程；`secondary` = 链上其余进程 + 守护（iahelper）；
        `analysis_order` = 建议查看顺序（自证性「需关联」者须与链上其他进程对照）。
        未命中症状返回 {}（缺省放行不报错）。
        """
        key = (symptom or "").strip()
        if not key:
            return {}
        processes = self.get_processes_for_symptom(key)
        if not processes:
            return {}

        def _short(pid: str) -> str:
            return pid.removeprefix("process:")

        def _log_of(pid: str) -> str:
            return self.get_process_attrs(pid).get("日志标识", "")

        primary = processes[0]
        chain = self.get_process_chain(primary)
        chain_ids = [c["process"] for c in chain]
        secondary: list[str] = []
        for pid in processes[1:] + chain_ids[1:]:
            s = _short(pid)
            if s != _short(primary) and s not in secondary:
                secondary.append(s)
        # 守护进程（生命周期管理）——排查进程存活/拉起问题时需要
        supervisor = "iahelper"
        if supervisor != _short(primary) and supervisor not in secondary:
            secondary.append(supervisor)

        analysis_order = []
        for pid in [primary] + [f"process:{s}" for s in secondary]:
            attrs = self.get_process_attrs(pid)
            analysis_order.append({
                "process": _short(pid),
                "log": attrs.get("日志标识", ""),
                "self_sufficient": attrs.get("日志自证性", ""),
                "note": ("需与链上其他进程对照时间线" if "需关联" in attrs.get("日志自证性", "")
                         else "本进程日志通常自证"),
            })

        return {
            "primary": _short(primary),
            "secondary": secondary,
            "analysis_order": analysis_order,
            "chain": [_short(p) for p in chain_ids],
            "process_duties": {
                _short(p): {
                    "log": _log_of(p),
                    "frequency": self.get_process_attrs(p).get("排查频度", ""),
                    "self_sufficient": self.get_process_attrs(p).get("日志自证性", ""),
                }
                for p in self._iter_process_ids()
            },
            "pattern_library_entry": (
                "search_qdrant(collection=log_patterns_collection, dimension=日志模式)"
            ),
            "derived_from": "bkn:relations/process_topology.bkn#suspected_in + bkn:objects/*.bkn#关键属性",
            "note": "23 号方案：症状→日志顺序由 suspected_in/feeds 边与进程属性派生（本体层），"
                    "跨进程对照的根因速查见 skill:demo_product-log-analyzer。",
        }

    # ========== 运行时对象域（20 号方案：进程拓扑推导链） ==========

    @staticmethod
    def _process_file(process_id: str) -> str:
        """process:* ID → 对应进程对象文件相对路径（小写规范化）。"""
        name = process_id.removeprefix("process:").lower()
        return f"objects/{name}.bkn"

    def get_process_attrs(self, process_id: str) -> dict:
        """读进程对象「关键属性」段，返回 {属性: 值}（剥 process: 前缀）。

        23 号方案：关键属性为 **KV bullet**（`- **属性**: 值`）——本体层定义段只允许
        KV 属性列表与实例登记表；兼容旧表格行（`| 属性 | 值 |`）解析。
        枚举值（频度/自证性）只取主枚举 token（如「高（现场问题最多）」→「高」）。
        """
        attrs: dict[str, str] = {}
        data = self.load(self._process_file(process_id))
        for sec_name, sec in data.items():
            for line in sec.get("raw", "").split("\n"):
                key = val = ""
                m_kv = re.match(r"-[ \t]*\*\*([^*]+)\*\*[ \t]*:[ \t]*(.+)$", line.strip())
                m_tbl = re.match(r"\|[ \t]*([^|]+)[ \t]*\|[ \t]*([^|]+)[ \t]*\|", line.strip())
                if m_kv:
                    key, val = m_kv.group(1), m_kv.group(2)
                elif m_tbl and m_tbl.group(1).strip() not in ("属性", "值", "---"):
                    key, val = m_tbl.group(1), m_tbl.group(2)
                key = key.strip().strip("`")
                val = val.strip().strip("`")
                if key and val and key not in attrs:
                    # 枚举属性截取主 token：`高（现场问题最多）` → `高`；`需关联（...）` → `需关联`
                    if key in ("排查频度", "日志自证性"):
                        val = val.split("（")[0].split("(")[0].strip().strip("*")
                    attrs[key] = val
        return attrs

    def get_processes_for_symptom(self, key: str) -> list[str]:
        """症状/错误码 → 嫌疑进程（suspected_in 边，20 号方案替代 has_class）。

        输入 `error:-4073` / `symptom:incremental_stuck` / 裸名（先归一，再补命名空间前缀）。
        """
        if ":" not in key:
            key = self.resolve_synonym(key)
        if ":" not in key:
            # 裸名无命名空间：先试 symptom: 前缀（现场描述多为症状），再试 error:
            for prefix in ("symptom:", "error:"):
                hits = self._get_traverser().get_targets(f"{prefix}{key}", "suspected_in")
                if hits:
                    return hits
        return self._get_traverser().get_targets(key, "suspected_in")

    def get_process_chain(self, process_id: str) -> list[dict]:
        """进程 → 数据流链（feeds 正向遍历，结构顺序 = 链路方向）。

        每段: {process, role, language, log, frequency, self_sufficient, checks}
        频度/自证性来自进程对象「关键属性」；语言 → 工具类别由 get_process_tools 推导。
        """
        chain: list[dict] = []
        seen: set[str] = set()
        queue = [process_id]
        while queue:
            cur = queue.pop(0)
            if cur in seen:
                continue
            seen.add(cur)
            attrs = self.get_process_attrs(cur)
            chain.append({
                "process": cur,
                "role": attrs.get("角色", ""),
                "language": attrs.get("语言", ""),
                "log": attrs.get("日志标识", ""),
                "frequency": attrs.get("排查频度", ""),
                "self_sufficient": attrs.get("日志自证性", ""),
                "checks": self.get_process_tools(cur),
            })
            # transitive 的消费者（C-20261013-04 接线）：只有 feeds 声明为**可传递**时才继续展开；
            # 摘掉 edge_semantics.yaml 的 feeds 声明 ⇒ 进程链退化为单点（不再是「只声明、无实现」）。
            for nxt in self._get_traverser().transitive_targets(cur, "feeds"):
                if nxt not in seen:
                    queue.append(nxt)
        return chain

    def get_process_tools(self, process_id: str) -> list[str]:
        """进程语言 → 工具类别（属性驱动排障的核心推导）。

        C++ → core dump/stderr/动态库；Java → JDK 工具链。
        语言含「按库而异」时（iadumper）返回空 + 提示（适用库清单待核，不得猜测）。
        """
        attrs = self.get_process_attrs(process_id)
        lang = attrs.get("语言", "")
        if "C++" in lang and "Java" in lang:
            return []  # iadumper 按库而异——适用库清单待核，不得推导
        if "C++" in lang:
            return ["core dump / stderr / 动态库（gdb / ldd / LD_LIBRARY_PATH）"]
        if "Java" in lang:
            return ["JDK 工具链（jstack / jmap / jstat / GC 日志 / JDK 版本）"]
        return []

    def get_process_skills(self, process_id: str) -> list[str]:
        """进程对象「关联」段里的 skill: 引用（与 diagnosed_by 对称的进程侧路由）。

        23 号方案：只扫「关联」段——「关键属性」段中的 `skill:` 是**值委托指针**
        （如日志路径由某 Skill 提供），不代表该进程的排查 Skill 归属。
        """
        data = self.load(self._process_file(process_id))
        skills: list[str] = []
        for sec_name, sec in data.items():
            if "关联" not in sec_name:
                continue
            for line in sec.get("raw", "").split("\n"):
                for m in re.finditer(r"`skill:([a-z0-9_-]+)`", line):
                    if m.group(1) not in skills:
                        skills.append(m.group(1))
        return skills

    # （21 号 2D）_extract_skills_from_block / _extract_text_after_header 已删：
    # 23 号 symptom-router 下延后的死代码，生产与测试零消费者。

    @staticmethod
    def _manifest_skill(skill_id: str, reason: str) -> dict:
        """经 manifest 解析 skill ID → 显示名（entry 目录尾段）；未命中回落 ID 本身。"""
        try:
            from .manifest import resolve_skill_id
            item = resolve_skill_id(skill_id)
            name = (item.get("entry", "") if item else "").rstrip("/").split("/")[-1]
            return {"name": name or skill_id.split(":", 1)[-1], "reason": reason}
        except Exception:
            return {"name": skill_id.split(":", 1)[-1], "reason": reason}

    @staticmethod
    def _fallback_symptom_skills() -> dict[str, Any]:
        return {
            "required": [BKNResolver._manifest_skill("skill:demo_product-db-diagnostics",
                                                     "按 DB 类型执行具体诊断")],
            "optional": [],
            "analysis_framework": "",
            "skill_capabilities": "",
        }

    def lookup_operation(self, operation: str) -> dict | None:
        """查询操作→capability 映射

        支持 capability/别名/中文名/英文名的归一化匹配。
        """
        if not operation or not operation.strip():
            return None

        def norm(s: str) -> str:
            return s.replace(" ", "").replace("_", "").lower()

        q = norm(operation)
        candidates = []
        for cap, info in self._operations.items():
            cap_norm = norm(cap)
            name_norm = norm(info.get("name", ""))
            aliases = info.get("aliases", [])
            alias_norms = [norm(a) for a in aliases if a]

            # 匹配优先级
            if q == cap_norm:
                candidates.append((0, cap, info, "capability"))
            elif q in alias_norms:
                candidates.append((1, cap, info, "alias"))
            elif q in name_norm:
                candidates.append((2, cap, info, "name"))
            elif q in cap_norm:
                candidates.append((3, cap, info, "capability_partial"))
            elif any(q in a for a in alias_norms):
                candidates.append((4, cap, info, "alias_partial"))

        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0])
        _, cap, info, matched_by = candidates[0]
        return {
            "capability": cap,
            "name": info["name"],
            "implements": info.get("implements", ""),
            "params": info.get("params", ""),
            "constraints": info.get("constraints", ""),
            "notes": info.get("notes", ""),
            "prerequisites": info.get("prerequisites", ""),
            "risks": info.get("risks", ""),
            "aliases": info.get("aliases", []),
            "matched_by": matched_by,
        }

    def list_operations(self) -> list[str]:
        """列出所有可用操作"""
        return [info["name"] for info in self._operations.values()]

    def list_scenarios(self) -> list[dict]:
        """扫描 objects/scenario-*.bkn（24 号：原 bkn/scenarios/ 已并入 objects/ 并加 `scenario-` 前缀）"""
        objects_dir = self.root / "objects"
        if not objects_dir.exists():
            return []

        results = []
        for path in sorted(objects_dir.glob("scenario-*.bkn")):
            rel = str(path.relative_to(self.root))
            data = self.load(rel)
            kv = data.get("基本信息", {}).get("kv", {})
            scenario_id = kv.get("场景 ID", "")
            name = kv.get("场景名称", "")
            keywords_raw = kv.get("关键词", "")

            if not scenario_id:
                # fallback: 用文件名生成 id（去掉 objects/ 前缀 `scenario-`）
                scenario_id = path.stem.removeprefix("scenario-")
            if not name:
                # fallback: 取第一个非 _head/基本信息 的 section 名
                for sec_name in data:
                    if sec_name not in ("_head", "基本信息"):
                        name = sec_name
                        break
            if not name:
                name = path.stem.removeprefix("scenario-")

            keywords = [k.strip() for k in re.split(r"[，,、 \t\n\r\f\v]+", keywords_raw) if k.strip()]

            results.append({
                "id": scenario_id,
                "name": name,
                "keywords": keywords,
                "file": rel,
            })
        return results

    def _load_scenario_rules(self):
        """加载场景匹配规则（Tool 层常量，23 号方案：原 BKN scenario-rules.bkn 已下延）。"""
        rules = [dict(r) for r in _SCENARIO_ROUTING_RULES]
        rules.sort(key=lambda r: r["priority"])
        self._scenario_rules = rules

    def _match_scenario_pattern(self, candidate: str, pattern: str) -> bool:
        """单条模式匹配: same / * / 逗号分隔列表"""
        if pattern == "*":
            return True
        if pattern == "same":
            # same 模式在 match_scenario 中组合使用
            return False
        for pat in re.split(r"[，,]+", pattern):
            pat = pat.strip()
            if not pat:
                continue
            if is_db_match(candidate, pat):
                return True
        return False

    # prerequisites.bkn 中「只读查询」段的段名前缀（无约束动作的兜底维度）
    _READONLY_DIMENSION_PREFIX = "只读查询"

    def get_prerequisites(self, operation: str) -> dict:
        """查询操作前置条件（批 2-1 起为派生实现，P-A：Tool 是 BKN 的投影）。

        逐 action 前置不再存于 prerequisites.bkn：约束类前置由
        relations/action_routing.bkn 的 constrained_by 边 × risks/constraints.bkn
        约束表实时派生；非约束类业务前置由各负责 Skill 承载。
        prerequisites.bkn 只提供按 risk_type 维度的通行指引（T-Box 常数段）。

        输出 raw 按「维度标题 + 通行指引 + 该操作具体约束」组装，末尾为
        `- **负责 Skill**: \\`xxx\\`` 行与 `<!-- type: action -->` 段尾标记——
        两条红线（supplement._extract_skill_from_result 靠 kv 中的
        `**负责 Skill**` 键提取 Skill，见 test_output_budget）。
        """
        info = self.lookup_operation(operation)
        if not info:
            return {}
        capability = info["capability"]

        # 约束边与负责 Skill：图键是裸 capability（action: 前缀查不到）
        traverser = self._get_traverser()
        constraint_ids = traverser.get_constraints_for_action(capability)
        skills = traverser.get_skills_for_action(capability)
        if not skills and info.get("implements", "").startswith("skill:"):
            skills = [info["implements"][len("skill:"):]]  # 无边动作回落 action 段 implements

        # constraints.bkn 约束行（跨段汇总；加载策略/排查入口等表无「约束ID」列，自动跳过）
        rows_by_id: dict[str, dict] = {}
        for sec_data in self.load("risks/constraints.bkn").values():
            for table in sec_data.get("tables", []):
                for row in table.get("rows", []):
                    cid = row.get("约束ID")
                    if cid:
                        rows_by_id[cid] = row
        matched_rows = [rows_by_id[cid] for cid in constraint_ids if cid in rows_by_id]

        # 维度段（T-Box 通行指引），段名形如 "state_prerequisite — 状态前置"
        prereq_data = self.load("risks/prerequisites.bkn")
        dimensions = [(name, sec) for name, sec in prereq_data.items() if name != "_head"]

        def _dimension_body(sec) -> str:
            raw = sec.get("raw", "")
            kept = [ln for ln in raw.split("\n") if not ln.strip().startswith("<!--")]
            return "\n".join(kept).strip()

        grouped: dict[str, list[str]] = {}
        orphans: list[str] = []
        for row in matched_rows:
            risk_type = (row.get("类型") or "").strip()
            label = (row.get("Risk") or "").strip()
            text = (row.get("约束") or "").strip()
            item = f"- [{label}] {text}" if label else f"- {text}"
            sec_name = next((n for n, _ in dimensions if risk_type and n.startswith(risk_type)), None)
            if sec_name:
                grouped.setdefault(sec_name, []).append(item)
            else:
                orphans.append(item)  # 类型暂无维度段：不静默丢弃，落「其他约束」

        lines = [f"# {info['name']}（{capability}）前置条件", ""]
        if matched_rows or orphans:
            for name, sec in dimensions:
                items = grouped.get(name)
                if not items:
                    continue
                lines.append(f"## {name}")
                body = _dimension_body(sec)
                if body:
                    lines.append(body)
                lines.extend(items)
                lines.append("")
        else:
            lines.append(f"## {self._READONLY_DIMENSION_PREFIX} — 无约束前置")
            sec = next((s for n, s in dimensions if n.startswith(self._READONLY_DIMENSION_PREFIX)), None)
            if sec:
                lines.append(_dimension_body(sec))
            lines.append("")
        if orphans:
            lines.append("## 其他约束")
            lines.extend(orphans)
            lines.append("")

        # 前置链（action 段 prerequisites kv，如 "[activate_node, register_source_db]"）
        chain_raw = (info.get("prerequisites") or "").strip().strip("[]")
        chain = [p.strip() for p in chain_raw.split(",") if p.strip()]
        if chain:
            lines.append(f"- 前置链: {' → '.join(chain)}")
        if skills:
            lines.append("- **负责 Skill**: " + ", ".join(f"`{s}`" for s in skills))
        lines.append("<!-- type: action -->")
        raw = "\n".join(lines)

        # 物化 kv：保证 _extract_skill_from_result 第一分支（kv 含 Skill 键）可命中
        section = _SectionDict(raw)
        _ = section["kv"]
        result = dict(section)
        result.update({
            "capability": capability,
            "matched_by": info.get("matched_by", ""),
            "skills": skills,
            "constraint_ids": list(constraint_ids),
        })
        return result


# ========== 通用操作前置知识合成 ==========

_OPERATION_DIMENSION_TEMPLATES = [
    ("前置条件", lambda op, cap: f"{op} 前置条件 准备工作 环境要求"),
    ("约束与注意事项", lambda op, cap: f"{op} 约束 禁止 注意事项"),
    ("常见错误", lambda op, cap: f"{op} 常见错误 错误码 排查"),
]


def _split_bkn_text(text: str) -> list[str]:
    """将 BKN 中的单行/分号/换行文本拆分为可读条目。"""
    if not text:
        return []
    items = []
    for part in re.split(r"[;；\n]", text):
        part = part.strip().strip("- *•")
        if part:
            items.append(part)
    return items


def _extract_error_codes(text: str) -> dict[str, str]:
    """从风险文本中提取错误码及其对应描述行。"""
    codes: dict[str, str] = {}
    if not text:
        return codes
    pattern = re.compile(r"((?:[A-Z]{2,}-)+[0-9]+|-[0-9]{3,})")
    for line in re.split(r"[;；\n]", text):
        line = line.strip().strip("- *•")
        if not line:
            continue
        found = pattern.findall(line)
        if found:
            for code in found:
                codes[code] = line
            break
    return codes


def synthesize_operation_knowledge(
    capability: str,
    operation_name: str,
    bkn_caps: dict | None = None,
    top_k: int = 3,
) -> dict:
    """基于 BKN capability 信息 + Qdrant 多维度检索，合成操作前置知识。

    返回结构:
        {
            "summary": "...",
            "what_you_need": [...],
            "constraints": [...],
            "common_errors": {"-4016": "...", ...},
            "dimensions": [{"name": "前置条件", "snippets": [...]}, ...],
            "top_references": [...],
        }
    """
    bkn_caps = bkn_caps or {}
    terms = [t for t in (operation_name, capability) if t]
    label = terms[0] if terms else "operation"

    what_you_need = _split_bkn_text(bkn_caps.get("prerequisites", ""))
    constraints = _split_bkn_text(bkn_caps.get("constraints", ""))
    risks_text = bkn_caps.get("risks", "")
    if risks_text:
        constraints.extend(item for item in _split_bkn_text(risks_text) if item not in constraints)
    common_errors = _extract_error_codes(risks_text)

    dimensions = []
    all_references: set[str] = set()

    for dim_name, template in _OPERATION_DIMENSION_TEMPLATES:
        query = template(label, capability)
        snippets = []
        try:
            hits = search_qdrant(query, top_k=top_k, hybrid=True)
        except Exception:
            hits = []
        for h in hits:
            content = h.get("content", "")
            if not content:
                continue
            snippets.append({
                "content": content[:500],
                "score": h.get("score", 0),
                "source": h.get("source", ""),
            })
            src = h.get("source", "")
            if src:
                all_references.add(src)
        if snippets:
            _track_dimension(dim_name, len(snippets))
        dimensions.append({"name": dim_name, "snippets": snippets})

    summary_parts = []
    if what_you_need:
        summary_parts.append(f"前置要求: {'; '.join(what_you_need[:3])}")
    if constraints:
        summary_parts.append(f"主要约束: {'; '.join(constraints[:3])}")
    if common_errors:
        summary_parts.append(f"涉及错误码: {', '.join(list(common_errors)[:5])}")
    summary = "；".join(summary_parts) if summary_parts else f"已整理 {label} 的前置知识与操作注意事项"

    return {
        "summary": summary,
        "what_you_need": what_you_need,
        "constraints": constraints,
        "common_errors": common_errors,
        "dimensions": dimensions,
        "top_references": sorted(all_references),
    }
