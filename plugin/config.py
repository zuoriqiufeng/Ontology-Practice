"""config.py — 从 config.yaml 加载配置

**依赖纪律（2026-10-12 事故后加固）**：pyyaml 缺失**不得**导致插件加载失败。
事故链：Hermes runtime 更新后缺 pyyaml → 内置 fallback 解析器把行内注释当值
（`timeout: 5  # 请求超时(秒)`）→ `int()` 在 import 顶层抛 ValueError → `register()`
从未执行（12 Tool + RiskGuard hook 全部未注册）。两手加固：

① fallback 解析器覆盖 config.yaml 实际用到的 YAML 子集（行内注释/嵌套映射/映射列表/
   流式列表/标量类型），且**与 pyyaml 的解析结果逐键等价**——由
   `plugin/tests/test_config.py::test_fallback_parser_matches_pyyaml_on_real_config` 钉住；
② 标量（int/float）转换失败**不再炸 import**：回退默认值 + `CONFIG_ERRORS` 警告。
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

#: 配置加载期的可报告问题（解析器降级 / 标量回退）；日志可见，供现场自检
CONFIG_ERRORS: list = []

try:
    import yaml
except ImportError:
    yaml = None


def _strip_inline_comment(line: str) -> str:
    """剥行内注释：引号外的 `#`（其前为空白或行首）才算注释起点（对齐 pyyaml 口径）。

    事故根因即此处缺失：`timeout: 5   # 请求超时(秒)` 的整个注释被当成值。
    """
    out = []
    quote = None
    prev = ""
    for ch in line:
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            out.append(ch)
        elif ch == "#" and (prev == "" or prev in " \t"):
            break
        else:
            out.append(ch)
        prev = ch
    return "".join(out)


def _parse_scalar(text: str):
    """标量解析（受限子集）：引号字符串 / bool / int / float / 流式列表 / 原样字符串。"""
    t = text.strip()
    if t == "":
        return None
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'":
        return t[1:-1]
    if t in ("true", "True"):
        return True
    if t in ("false", "False"):
        return False
    if t.startswith("[") and t.endswith("]"):
        inner = t[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(x) for x in inner.split(",")]
    body = t[1:] if t[:1] in ("+", "-") else t
    if body.isdigit():
        return int(t)
    if body.count(".") == 1 and body.replace(".", "").isdigit():
        return float(t)
    return t


class _Block:
    """按缩进组织的原始块：有 pairs → dict，有 items → list，两者皆空 → None。"""

    __slots__ = ("indent", "pairs", "items")

    def __init__(self, indent: int):
        self.indent = indent
        self.pairs = []   # [(key, value | _Block)]
        self.items = []   # [value | _Block]


def _materialize(block: _Block):
    if block.items:
        return [_materialize(x) if isinstance(x, _Block) else x for x in block.items]
    if block.pairs:
        return {k: (_materialize(v) if isinstance(v, _Block) else v) for k, v in block.pairs}
    return None


def _fallback_yaml_load(text: str) -> dict:
    """无 pyyaml 时的受限解析器（对真实 config.yaml 与 pyyaml 等价——测试钉住）。

    走到本函数说明环境缺 yaml（或 yaml 解析失败）；它只支持 config.yaml 用到的子集。
    若将来配置用到这里没有的 YAML 特性，等价性测试会红 —— **修法是扩展本函数或装上 pyyaml**，
    而不是去掉那条测试。
    """
    root = _Block(-1)
    stack = [root]
    for raw in text.splitlines():
        line = _strip_inline_comment(raw).rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        content = line.strip()
        while len(stack) > 1 and indent <= stack[-1].indent:
            stack.pop()
        parent = stack[-1]
        if content.startswith("- "):
            item_text = content[2:].strip()
            if ":" in item_text:
                key, _, val = item_text.partition(":")
                node = _Block(indent)
                if val.strip() == "":
                    child = _Block(indent)
                    node.pairs.append((key.strip(), child))
                else:
                    node.pairs.append((key.strip(), _parse_scalar(val)))
                parent.items.append(node)
                stack.append(node)
            else:
                parent.items.append(_parse_scalar(item_text))
        elif ":" in content:
            key, _, val = content.partition(":")
            if val.strip() == "":
                node = _Block(indent)
                parent.pairs.append((key.strip(), node))
                stack.append(node)
            else:
                parent.pairs.append((key.strip(), _parse_scalar(val)))
    return _materialize(root) or {}


def _as_int(raw, default: int) -> int:
    """int 转换软化：失败**不炸 import**，回退默认并记入 `CONFIG_ERRORS`（事故的第二道闸）。"""
    try:
        return int(raw)
    except (TypeError, ValueError):
        CONFIG_ERRORS.append(f"{raw!r} 不是整数，回退默认 {default!r}")
        return default


def _as_float(raw, default: float) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        CONFIG_ERRORS.append(f"{raw!r} 不是数值，回退默认 {default!r}")
        return default


def _load_yaml(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if yaml is not None:
        try:
            return yaml.safe_load(text) or {}
        except Exception as e:  # noqa: BLE001 —— 坏 YAML 也退内置解析器，不炸 import
            CONFIG_ERRORS.append(f"pyyaml 解析 {path.name} 失败（{e}）；改用内置受限解析器")
    else:
        CONFIG_ERRORS.append(f"pyyaml 不可用；{path.name} 改用内置受限解析器（等价性由测试钉住）")
    try:
        return _fallback_yaml_load(text) or {}
    except Exception as e:  # noqa: BLE001 —— 解析器自身异常同样不得炸 import
        CONFIG_ERRORS.append(f"内置解析器解析 {path.name} 失败（{e}）；配置按空处理")
        return {}


# 加载配置
_CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"
_config = _load_yaml(_CONFIG_PATH) if _CONFIG_PATH.exists() else {}

# Qdrant 配置
QDRANT = _config.get("qdrant", {})
QDRANT_HOST = os.environ.get("QDRANT_HOST", QDRANT.get("host", "localhost"))
QDRANT_PORT = _as_int(os.environ.get("QDRANT_PORT", QDRANT.get("port", 6333)), 6333)
QDRANT_COLLECTION = os.environ.get("QDRANT_COLLECTION", QDRANT.get("collection", "demo_product_collection"))
QDRANT_SECONDARY_COLLECTION = os.environ.get(
    "QDRANT_SECONDARY_COLLECTION", QDRANT.get("secondary_collection", "test_doc_chunks")
)
QDRANT_TIMEOUT = _as_int(os.environ.get("QDRANT_TIMEOUT", QDRANT.get("timeout", 5)), 5)

# 多集合注册表 (v1.7): name → description
# 优先读 qdrant.collections 列表；缺省时由 collection + secondary_collection 合成（向后兼容）
# 26 号：集合的**语义身份**（store: 检索源注册集）权威点在 Tool 层 skill_manifest.yaml 的 stores:；
# 本表只持物理连接与描述（分工制：检索源身份 → manifest，物理连接 → 此处）
_collections_list = QDRANT.get("collections") or []
QDRANT_COLLECTIONS: dict = {}
for _c in _collections_list:
    if isinstance(_c, dict) and _c.get("name"):
        QDRANT_COLLECTIONS[_c["name"]] = _c.get("description", "")
if not QDRANT_COLLECTIONS:
    QDRANT_COLLECTIONS = {
        QDRANT_COLLECTION: "主检索集合",
        QDRANT_SECONDARY_COLLECTION: "辅助集合",
    }

# Embedding 配置
EMB = _config.get("embedding", {})
EMB_MODE = EMB.get("mode", "local")
EMB_MODEL_NAME = EMB.get("model_name", "BAAI/bge-large-zh-v1.5")
EMBEDDING_DIMENSION = EMB.get("dimension", 1024)
EMB_DEVICE = EMB.get("device", "cpu")
EMB_HF_OFFLINE = EMB.get("hf_offline", True)
EMB_HF_HOME = EMB.get("hf_home", "")

# 搜索配置
SEARCH = _config.get("search", {})
SEARCH_TOP_K = SEARCH.get("top_k", 5)
SEARCH_SCORE_THRESHOLD = SEARCH.get("score_threshold", 0.3)
SEARCH_HYBRID = SEARCH.get("hybrid", True)
SEARCH_FALLBACK_NONE = SEARCH.get("fallback_on_bkn_none", True)
SEARCH_FALLBACK_PARTIAL = SEARCH.get("fallback_on_bkn_partial", True)
SEARCH_PARTIAL_ENRICH = SEARCH.get("partial_enrich", True)
SEARCH_MIN_CONTENT_LENGTH = SEARCH.get("min_content_length", 50)
# 21 号 2B: 默认 5→3。BKN 图中单场景 risks_of 边实测上限 3，阈值 5 高于数据天花板 = design_solution 永久 partial
SEARCH_MIN_RISK_COUNT = SEARCH.get("min_risk_count", 3)

# 查询分解 (v2.0)
SEARCH_DECOMPOSE = SEARCH.get("decompose", True)
SEARCH_DECOMPOSE_TOP_K = SEARCH.get("decompose_top_k", 5)
SEARCH_DECOMPOSE_MIN = SEARCH.get("decompose_min_queries", 3)
SEARCH_DECOMPOSE_MAX = SEARCH.get("decompose_max_queries", 8)
SEARCH_DECOMPOSE_DEDUP = SEARCH.get("decompose_dedup_threshold", 0.85)

# Hermes 原生分解 (v3.0)
SEARCH_DEFER_TO_HERMES = SEARCH.get("defer_to_hermes", True)

# BGE miss → BM25 fallback (v3.3)
SEARCH_BM25_FALLBACK_SCORE = SEARCH.get("bm25_fallback_score", 0.1)

# BGE precision guard (v3.4): 当查询含精确项(错误码等)但 BGE 结果不含时, 触发 BM25 兜底
SEARCH_BM25_PRECISION_GUARD = SEARCH.get("bm25_precision_guard", True)

# Chunk-aware search (v3.6)
# 84 号：码行确定性通道（0=关闭，退回旧 dense/BM25 路径）
EXACT_CODE_LOOKUP = os.environ.get("EXACT_CODE_LOOKUP", "1") not in ("0", "false", "False")
#: 码行交付的行文本上限（超长以命中位置切窗）
CODE_ROW_MAX_CHARS = _as_int(os.environ.get("CODE_ROW_MAX_CHARS", "400"), 400)
#: 单码最多保留的行引用数（超出丢弃，防内存膨胀）
CODE_ROWS_MAX = _as_int(os.environ.get("CODE_ROWS_MAX", "20"), 20)


SEARCH_CHUNK_MODE = os.environ.get("SEARCH_CHUNK_MODE", SEARCH.get("chunk_mode", "mini_first"))
MINI_FIRST_TOP_K_MULTIPLIER = _as_int(
    os.environ.get("MINI_FIRST_TOP_K_MULTIPLIER", SEARCH.get("mini_first_top_k_multiplier", 2)), 2
)
PARENT_EXPAND_LIMIT_MULTIPLIER = _as_int(
    os.environ.get("PARENT_EXPAND_LIMIT_MULTIPLIER", SEARCH.get("parent_expand_limit_multiplier", 2)), 2
)

# RiskGuard (v1.5, P0-4): 代码级风险护栏
RISK_GUARD = _config.get("risk_guard", {})
RISK_GUARD_ENABLED = os.environ.get(
    "RISK_GUARD_ENABLED", str(RISK_GUARD.get("enabled", True))
).lower() == "true"
# block=false → 只记录日志不阻断（灰度）; block=true → pre_tool_call 返回 block 消息
RISK_GUARD_BLOCK = os.environ.get(
    "RISK_GUARD_BLOCK", str(RISK_GUARD.get("block", False))
).lower() == "true"

# Tool 输出总量预算 (v1.5): 0=无限制(默认); >0 时按优先级截断
SEARCH_OUTPUT_MAX_CHARS = _as_int(
    os.environ.get("SEARCH_OUTPUT_MAX_CHARS", SEARCH.get("output_max_chars", 0)), 0
)

# 豁免 _wrap() 的 Tool 输出总量预算 (v3.9): 0=无限制(默认)
# 独立于 search.output_max_chars —— 后者语义是「检索类输出预算」，且 raw 模式会跳过它。
# search_qdrant / diagnose_db_link / check_action_risk 三个 handler 绕过 _wrap()，
# 需要自己的兜底上限。
TOOLS_OUTPUT_MAX_CHARS = _as_int(
    os.environ.get("TOOLS_OUTPUT_MAX_CHARS", _config.get("tools", {}).get("output_max_chars", 0)), 0
)

# 可观测性埋点（44 号 §3.4）：过程级事件写 trajectory 流。默认开；压测/门禁可 OBSERVABILITY=0 关。
_observability_raw = os.environ.get("OBSERVABILITY", "1").strip().lower()
OBSERVABILITY = _observability_raw not in ("0", "false", "no", "off")

# 日志轮转 (v1.7): gap_log/usage_log 大小触发轮转
LOG_ROTATE = _config.get("log_rotate", {})
LOG_ROTATE_GAP_MAX_BYTES = _as_int(
    os.environ.get("LOG_ROTATE_GAP_MAX_BYTES", LOG_ROTATE.get("gap_max_bytes", 524288)), 524288
)
LOG_ROTATE_USAGE_MAX_BYTES = _as_int(
    os.environ.get("LOG_ROTATE_USAGE_MAX_BYTES", LOG_ROTATE.get("usage_max_bytes", 262144)), 262144
)
LOG_ROTATE_TRAJ_MAX_BYTES = _as_int(
    os.environ.get("LOG_ROTATE_TRAJ_MAX_BYTES", LOG_ROTATE.get("traj_max_bytes", 262144)), 262144
)
LOG_ROTATE_BACKUPS = _as_int(
    os.environ.get("LOG_ROTATE_BACKUPS", LOG_ROTATE.get("backups", 3)), 3
)
# 日文件保留天数（2026-09-30 日期轮转）：0 = 永久保留；N = 清理早于 N 天的日文件及其分片
LOG_ROTATE_RETENTION_DAYS = _as_int(
    os.environ.get("LOG_ROTATE_RETENTION_DAYS", LOG_ROTATE.get("retention_days", 0)), 0
)

# 日志输出目录 (2A): 路径语义照抄 BKN_ROOT 先例——绝对路径/~ 开头直接用（expanduser），
# 相对值锚定仓库根（plugin 的上级，与历史默认 <repo>/logs 一致）。env: LOG_DIR。
_log_dir_raw = os.environ.get("LOG_DIR", LOG_ROTATE.get("dir", "logs"))
_log_dir_path = Path(_log_dir_raw).expanduser()
if _log_dir_path.is_absolute():
    LOG_DIR_PATH = _log_dir_path
else:
    LOG_DIR_PATH = Path(__file__).resolve().parent.parent / _log_dir_path


def resolve_log_path(filename: str) -> Path:
    """按 LOG_DIR_PATH 解析日志文件绝对路径；目录不存在则创建（自愈，修目录缺失静默丢日志）。

    创建失败不抛异常（调用方各自有静默容错语义），只返回路径。"""
    try:
        LOG_DIR_PATH.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return LOG_DIR_PATH / filename

# BKN 路径配置
BKN = _config.get("bkn", {})
_bkn_raw = os.environ.get("DEMO-PRODUCT_BKN_ROOT", BKN.get("root", "../bkn"))
if os.path.isabs(_bkn_raw) or _bkn_raw.startswith("~"):
    BKN_ROOT = str(Path(_bkn_raw).expanduser())
else:
    BKN_ROOT = str(Path(__file__).resolve().parent / _bkn_raw)

# 诊断关键词生成（批 6-4，18 号方案 §3.4/§5）：可选模型端点，未配置则模板兜底
LLM = _config.get("llm", {})
DIAGNOSTIC_KEYWORD_ENDPOINT = os.environ.get(
    "DIAGNOSTIC_KEYWORD_ENDPOINT", LLM.get("diagnostic_keyword_endpoint", "")
)
DIAGNOSTIC_KEYWORD_TIMEOUT = _as_int(os.environ.get(
    "DIAGNOSTIC_KEYWORD_TIMEOUT", LLM.get("diagnostic_keyword_timeout", 15)), 15)


def _report_config_errors() -> None:
    """把加载期问题（解析器降级 / 标量回退）写进日志——现场可见，不阻断。"""
    for err in CONFIG_ERRORS:
        logger.warning("plugin.config: %s", err)


_report_config_errors()
