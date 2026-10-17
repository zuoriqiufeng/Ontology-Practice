"""risk_guard.py — 代码级风险护栏 (v2.0, L2 打通)

通过 Hermes `pre_tool_call` hook 在动作执行前拦截受控动作。

数据源（L2 打通后，三源 join）:
  1. objects/*.bkn 状态机表 → 状态全集/状态族/状态归属（解析失败回退硬编码常量）
  2. relations/action_routing.bkn constrained_by/risks_of 图边 → 约束/风险 → 动作关联（单源）
  3. risks/constraints.bkn 约束表 → 约束类型/文案/错误码（按 rule_id 与图边 join）

约束类型 → 可判定性（L2 类型扩展）:
  - state_prerequisite: 状态前置约束，按调用方传入的 current_state 判定。
  - forbidden_sequence: "先做 X 才能做 Y"，靠 _session_action_log（hook 内存动作日志）判定（阶段 D）。
  - threshold: 时间窗约束（如 9:00-18:00 禁整库对比），hook 读本地时间判定（阶段 E）。
  - data_loss/param_constraint: 静态不可判定的保持提示，不进拦截。

拦截分阶段（阶段 A→B→C）:
  - 阶段 A（block=false）: 命中只 log，不阻断。
  - 阶段 B（block=true）: 仅拦截**可判定**的规则（state_prerequisite 且能推导出非空 forbidden_states）。
  - 阶段 C（block=true + FULL）: 全量 critical 规则拦截。

推导约定（见 bkn/SCHEMA.md）:
  - cannot_<verb>_<STATE>      → 禁止状态 = {STATE}（含该对象运行族状态）
  - cannot_<verb>_not_<STATE>  → 禁止状态 = 该对象全部状态 - {STATE}
  - <obj>_must_be_<STATE>      → 禁止状态 = 该对象全部状态 - {STATE}

回退保障（护栏永不空转）:
  _FALLBACK_RULES → _ASSOC_TO_ACTION → _OBJECT_STATES/_STATE_FAMILY/_STATE_OWNER
  任一层解析失败自动回退，逐层降级。

设计不变量: state 由调用方传参，护栏不查库（无网络、无副作用）。
会话日志属内存内前置校验，不查运行时状态。

灰度开关: RISK_GUARD_BLOCK=false 时只 log 不阻断。
受控动作识别保守：只拦明确命中 demo_product 管理语义的调用。
"""

from __future__ import annotations

import logging
import re
import time
from collections import defaultdict
from pathlib import Path

from .config import BKN_ROOT, RISK_GUARD_ENABLED, RISK_GUARD_BLOCK

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
# 硬编码回退层（仅当 BKN 解析失败时启用，保证护栏不失效）
# ═══════════════════════════════════════════════════════════════════

# 对象状态全集（forbidden_states 推导用）——回退用
_FALLBACK_OBJECT_STATES = {
    "syncrule": {"RUNNING", "FULLSYNC", "ABNORMAL", "STOPPED"},
    "worknode": {"INACTIVE", "ONLINE", "OFFLINE"},
    "dbnode": {"NORMAL", "ABNORMAL"},
}

# 运行族状态：cannot_delete_RUNNING 应同时覆盖 RUNNING 与 FULLSYNC
# （业务上 FULLSYNC 是 RUNNING 的特殊阶段，禁止删除运行中规则两者都拦）
_FALLBACK_STATE_FAMILY = {
    "RUNNING": {"RUNNING", "FULLSYNC"},
}

# 状态 → 归属对象（must_be/尾缀模式的状态归属由状态本身决定）
_FALLBACK_STATE_OWNER = {
    "INACTIVE": "worknode", "ONLINE": "worknode", "OFFLINE": "worknode",
    "NORMAL": "dbnode",
    "RUNNING": "syncrule", "FULLSYNC": "syncrule",
    "ABNORMAL": "syncrule", "STOPPED": "syncrule",
}

# ── 兜底规则（BKN 解析失败时使用，与 v1.5 试点一致）────────
_FALLBACK_RULES = {
    "cannot_delete_RUNNING": {
        "action": "delete_sync_rule", "object": "syncrule",
        "forbidden_states": {"RUNNING", "FULLSYNC"}, "severity": "critical",
        "message": "规则处于 {state} 状态，禁止删除。请先安全 stop，再执行删除。",
        "source": "fallback",
    },
    "worknode_must_be_ONLINE": {
        "action": "register_db", "object": "worknode",
        "forbidden_states": {"OFFLINE"}, "severity": "critical",
        "message": "工作节点处于 {state} 状态，禁止注册数据库节点。请先恢复节点在线。",
        "source": "fallback",
    },
    "cannot_restart_ABNORMAL": {
        "action": "restart_sync_rule", "object": "syncrule",
        "forbidden_states": {"ABNORMAL"}, "severity": "critical",
        "message": "规则处于 ABNORMAL 状态，禁止直接 restart。请先安全 stop、修复根因后再恢复。",
        "source": "fallback",
    },
}

# ── 约束类型白名单（可进拦截的类型）────────
_STATICALLY_DECIDABLE_TYPES = {"state_prerequisite", "forbidden_sequence", "threshold"}

# ── 动作别名 → 规范 action 名（hook 识别用）────────
_ACTION_ALIASES = {
    "delete_rule": "delete_sync_rule", "remove_rule": "delete_sync_rule",
    "delete_sync_rule": "delete_sync_rule",
    "modify_rule": "modify_sync_rule", "modify_sync_rule": "modify_sync_rule",
    "start_rule": "start_sync_rule", "start_sync_rule": "start_sync_rule",
    "stop_rule": "stop_sync_rule", "stop_sync_rule": "stop_sync_rule",
    "register_database": "register_db", "register_db": "register_db",
    "create_db_node": "register_db",
    "create_sync_rule": "create_sync_rule", "create_rule": "create_sync_rule",
    # restart 归一到 start_sync_rule：ABNORMAL/RUNNING 下 restart 语义为
    # "先 stop 再 start"，图边 action_routing 把 cannot_restart_* 约束挂在
    # start_sync_rule 上。归一后命令指纹识别的 restart 也能命中图边规则（护栏不失效）。
    "restart_rule": "start_sync_rule", "restart_sync_rule": "start_sync_rule",
    "activate_node": "activate_node", "create_compare": "create_compare",
}


def normalize_action(action: str) -> str:
    """动作别名归一（v1.6 公开 API，保持兼容）。"""
    return _ACTION_ALIASES.get(action, action)


# ── terminal/execute_code 命令中的 demo_product 管理操作指纹 ────────
_COMMAND_PATTERNS = [
    (re.compile(r"delete[^\n]{0,40}(rule|sync)", re.IGNORECASE), "delete_sync_rule"),
    (re.compile(r"(rule|sync)[^\n]{0,40}delete", re.IGNORECASE), "delete_sync_rule"),
    (re.compile(r"register[^\n]{0,40}(db|database|node)", re.IGNORECASE), "register_db"),
    (re.compile(r"restart[^\n]{0,40}(rule|sync)", re.IGNORECASE), "restart_sync_rule"),
    (re.compile(r"(rule|sync)[^\n]{0,40}restart", re.IGNORECASE), "restart_sync_rule"),
    (re.compile(r"modify[^\n]{0,40}(rule|sync)", re.IGNORECASE), "modify_sync_rule"),
    (re.compile(r"start[^\n]{0,40}(rule|sync)", re.IGNORECASE), "start_sync_rule"),
    (re.compile(r"stop[^\n]{0,40}(rule|sync)", re.IGNORECASE), "stop_sync_rule"),
]

_MUTATING_TOOLS = {"terminal", "execute_code", "write_file", "patch"}


def _detect_action_from_command(command: str) -> str:
    """从 terminal/execute_code 命令文本中识别 demo_product 管理动作。
    按 _COMMAND_PATTERNS 顺序匹配，首个命中即返回。未识别返回 ""。"""
    if not command:
        return ""
    for pattern, action in _COMMAND_PATTERNS:
        if pattern.search(command):
            return action
    return ""


# 约束ID 推导正则
_RE_CANNOT_STATE = re.compile(r"^cannot_[a-z]+_([A-Z][A-Z0-9_]*)$")
_RE_CANNOT_NOT_STATE = re.compile(r"^cannot_[a-z]+_not_([A-Z][A-Z0-9_]*)$")
_RE_MUST_BE_STATE = re.compile(r"_must_be_([A-Z][A-Z0-9_]*)$")
_RE_TRAILING_STATE = re.compile(r"_([A-Z][A-Z0-9_]*)$")

# ── lint 单点复用接口（38 号批 1：D1 约束状态引用检查）────────────────────
# 正则、状态集与归属**不重复定义**：lint 从这里取，与运行时护栏同源（照 32 号"单点"纪律）。
#: 约束ID → 状态名（**顺序＝先具体后泛化**；_RE_TRAILING_STATE 为兜底）
STATE_REF_REGEXES = (_RE_CANNOT_NOT_STATE, _RE_CANNOT_STATE, _RE_MUST_BE_STATE, _RE_TRAILING_STATE)
#: 状态名 → 归属对象（须与 _FALLBACK_STATE_OWNER 同步：新增状态族时两处一起改）
STATE_OWNER = dict(_FALLBACK_STATE_OWNER)


def state_index_for(bkn_root) -> dict:
    """给定 BKN 根的「对象 → 状态集」索引（lint D1 用；不写全局缓存）。

    口径与运行时 `_get_states()` 一致：**BKN 解析优先，对象缺失/为空才用硬编码回退补**
    （worknode 无状态段 → 回退 ONLINE/OFFLINE）。解析整体不完整时退回全量硬编码。
    """
    parsed: dict = {}
    try:
        parsed = _parse_object_states(Path(bkn_root)) or {}
    except Exception:
        parsed = {}
    if not parsed or not all(o in parsed for o in ("syncrule", "dbnode")):
        return {obj: set(states) for obj, states in _FALLBACK_OBJECT_STATES.items()}
    index = {obj: set(info.get("states") or set()) for obj, info in parsed.items()}
    for obj, states in _FALLBACK_OBJECT_STATES.items():
        if not index.get(obj):
            index[obj] = set(states)
    return index


# 阶段 E: 时间窗正则（HH:MM-HH:MM）
_RE_TIME_WINDOW = re.compile(r"(?<![0-9])([0-9]{1,2}:[0-9]{2})[ \t]*[-–~至][ \t]*([0-9]{1,2}:[0-9]{2})(?![0-9])")

# 会话动作日志（阶段 D，内存内，模块级）：[{action, ts}]
_session_action_log: list[dict] = []

# 缓存
_rules_cache: dict | None = None
_states_cache: dict | None = None
_edges_cache: dict | None = None


# ═══════════════════════════════════════════════════════════════════
# 步1: 状态机解析 —— objects/*.bkn → {states, families, owner}
# ═══════════════════════════════════════════════════════════════════

def _parse_object_states(bkn_root: Path) -> dict:
    """解析 objects/*.bkn 状态机段 → {obj: {states, families, state_owner}}

    兼容两种形态（24 号起 KV bullet 为现行形态）：
      1. **KV bullet**：`- **STOPPED**: 允许 start；无特殊禁止`（23 号后 BKN 只允许 KV/实例登记表）
      2. 表格（历史形态）：`| 当前状态 | 允许操作 | 禁止操作 |` / `| 状态 | 说明 | 可用于规则 |`
      3. worknode: 无状态段（ASCII 图），返回空，调用方回退硬编码。
    """
    result = {}
    objects_dir = bkn_root / "objects"
    if not objects_dir.is_dir():
        return result

    for path in sorted(objects_dir.glob("*.bkn")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        obj = path.stem.lower()

        states: set = set()
        families: dict[str, set] = {}

        # ── 状态机段落内找 KV bullet / 表格 ──
        lines = text.split("\n")
        in_state_machine = False
        for line in lines:
            if "## 状态机" in line or "## 状态约束" in line:
                in_state_machine = True
                continue
            if in_state_machine and line.startswith("## "):
                break  # 出了状态机段落
            if not in_state_machine:
                continue
            stripped = line.strip()
            # 形态 1：KV bullet（现行）：`- **STOPPED**: 允许 start`
            m_kv = re.match(r"^-[ \t]*\*\*([A-Za-z][A-Za-z0-9_]*)\*\*[ \t]*:", stripped)
            if m_kv:
                state = m_kv.group(1).upper()
                if re.match(r"^[A-Z][A-Z0-9_]*$", state):
                    states.add(state)
                continue
            # 形态 2：表格行（历史）
            if stripped.startswith("|"):
                cells = [c.strip() for c in stripped.split("|") if c.strip()]
                if not cells or "状态" in cells[0] and ("允许" in cells[1] if len(cells) > 1 else True):
                    continue  # 表头/分隔行
                if not cells[0] or cells[0].startswith("-"):
                    continue
                state = cells[0].strip("`*").upper()
                # 状态名过滤：只取全大写字母数字下划线
                if re.match(r"^[A-Z][A-Z0-9_]*$", state):
                    states.add(state)

        # ── 运行族声明（kv 行）: > 运行族: RUNNING={RUNNING,FULLSYNC} ──
        for m in re.finditer(r"运行族[:：][ \t]*([A-Z][A-Z0-9_]*)[ \t]*=[ \t]*\{([^}]+)\}", text):
            parent = m.group(1).strip()
            children = {s.strip().upper() for s in m.group(2).split(",") if s.strip()}
            if parent and children:
                families[parent] = children

        if states:
            result[obj] = {"states": states, "families": families, "state_owner": {}}

    # ── 构建 state → owner 反向索引（全库扫描）──
    state_owner: dict[str, str] = {}
    for obj, info in result.items():
        for st in info["states"]:
            state_owner.setdefault(st, obj)
    for obj, info in result.items():
        info["state_owner"] = dict(state_owner)

    return result


def _get_states() -> dict:
    """获取状态集缓存；解析失败回退硬编码。"""
    global _states_cache
    if _states_cache is not None:
        return _states_cache

    try:
        parsed = _parse_object_states(Path(BKN_ROOT))
        if parsed and all(o in parsed for o in ("syncrule", "dbnode")):
            # 补充硬编码回退（worknode 无表，从硬编码补）
            for obj in _FALLBACK_OBJECT_STATES:
                if obj not in parsed:
                    parsed[obj] = {
                        "states": set(_FALLBACK_OBJECT_STATES[obj]),
                        "families": {},
                        "state_owner": {},
                    }
            # 合并运行族：BKN 声明优先，硬编码按"族状态归属哪个对象"补入该对象
            # （族只在目标状态所属的对象内生效，避免全局族污染其他对象的推导）
            all_owner: dict[str, str] = {}
            for obj, info in parsed.items():
                for st in info["states"]:
                    all_owner.setdefault(st, obj)
            for parent, children in _FALLBACK_STATE_FAMILY.items():
                owner = all_owner.get(parent)
                if owner:
                    parsed[owner]["families"].setdefault(parent, set(children))
            for obj, info in parsed.items():
                info["state_owner"] = dict(all_owner)
            _states_cache = parsed
            logger.debug("risk_guard states parsed from BKN: %s", list(parsed.keys()))
        else:
            logger.warning("objects/*.bkn 状态机解析不完整, 使用硬编码状态集")
            _states_cache = _build_fallback_states()
    except Exception as e:
        logger.warning("objects/*.bkn 状态机解析失败(%s), 使用硬编码状态集", e)
        _states_cache = _build_fallback_states()
    return _states_cache


def _build_fallback_states() -> dict:
    """从硬编码常量构建 states 缓存结构。"""
    result = {}
    for obj, states in _FALLBACK_OBJECT_STATES.items():
        result[obj] = {
            "states": set(states),
            "families": dict(_FALLBACK_STATE_FAMILY),
            "state_owner": dict(_FALLBACK_STATE_OWNER),
        }
    return result


# ═══════════════════════════════════════════════════════════════════
# 步2: 约束→动作图边 join —— relations/action_routing.bkn（单源）
# ═══════════════════════════════════════════════════════════════════

def _parse_action_edges(bkn_root: Path) -> tuple[dict, dict]:
    """解析 relations/action_routing.bkn 的 constrained_by / risks_of 映射规则。
    返回 ({action: [rule_id]}, {action: [risk_id]})。解析失败返回空 dict。"""
    constraints: dict[str, list[str]] = defaultdict(list)
    risks: dict[str, list[str]] = defaultdict(list)
    path = bkn_root / "relations" / "action_routing.bkn"
    if not path.exists():
        return constraints, risks
    text = path.read_text(encoding="utf-8", errors="ignore")
    pat = re.compile(r"`([^`]+)`[ \t]*→[ \t]*`([^`]+)`")
    current_rel = None
    for line in text.split("\n"):
        if "关系类型" in line:
            if "constrained_by" in line:
                current_rel = "constrained_by"
            elif "risks_of" in line:
                current_rel = "risks_of"
            else:
                current_rel = None
            continue
        if current_rel and line.strip().startswith("-"):
            m = pat.search(line.split("#", 1)[0])
            if m:
                src = m.group(1).strip()
                if src.startswith("action:"):
                    src = src[len("action:"):]
                tgt = m.group(2).strip()
                if current_rel == "constrained_by":
                    constraints[src].append(tgt)
                else:
                    risks[src].append(tgt)
    return constraints, risks


def _get_edges() -> tuple[dict, dict]:
    """获取图边缓存：({action: [rule_id]}, {action: [risk_id]})。"""
    global _edges_cache
    if _edges_cache is not None:
        return _edges_cache
    try:
        _edges_cache = _parse_action_edges(Path(BKN_ROOT))
    except Exception as e:
        logger.warning("action_routing 图边解析失败(%s), 关联回退硬编码", e)
        _edges_cache = ({}, {})
    return _edges_cache


def _parse_constraints_detail(bkn_root: Path) -> dict:
    """解析 constraints.bkn 全部行 → {rule_id: {risk_name, risk_type, assoc, text}}。"""
    details: dict[str, dict] = {}
    path = bkn_root / "risks" / "constraints.bkn"
    if not path.exists():
        return details
    for line in path.read_text(encoding="utf-8", errors="ignore").split("\n"):
        if not line.startswith("|") or "约束ID" in line or "---" in line:
            continue
        cells = [c.strip() for c in line.split("|") if c.strip()]
        if len(cells) < 4:
            continue
        risk_name, rule_id, risk_type, text = cells[0], cells[1], cells[2], cells[3]
        if not re.match(r"^[a-z][a-zA-Z0-9_]*$", rule_id):
            continue
        details[rule_id] = {
            "risk_name": risk_name, "risk_type": risk_type,
            "text": text,
        }
    return details


# ═══════════════════════════════════════════════════════════════════
# 步3: 规则装配 —— 三源 join + 推导禁止状态
# ═══════════════════════════════════════════════════════════════════

def _derive_forbidden_states(rule_id: str, obj: str) -> set:
    """按约束ID 命名约定 + BKN 状态机推导禁止状态集合。无法推导时返回空集。"""
    states = _get_states()
    obj_states = states.get(obj, {}).get("states", set())
    families = states.get(obj, {}).get("families", {})
    state_owner = states.get(obj, {}).get("state_owner", {})

    m = _RE_CANNOT_NOT_STATE.match(rule_id)
    if m:
        return obj_states - {m.group(1)}
    m = _RE_CANNOT_STATE.match(rule_id)
    if m:
        state = m.group(1)
        family = families.get(state, {state})
        return family & obj_states if obj_states else family
    m = _RE_MUST_BE_STATE.search(rule_id) or _RE_TRAILING_STATE.search(rule_id)
    if m:
        state = m.group(1)
        owner = state_owner.get(state, obj)
        owner_states = states.get(owner, {}).get("states", set())
        return owner_states - {state}
    return set()


def _assemble_rules() -> dict:
    """三源 join 装配规则：图边关联 + 约束详情 + 状态机推导。"""
    bkn_root = Path(BKN_ROOT)
    edge_constraints, _ = _get_edges()
    details = _parse_constraints_detail(bkn_root)
    rules: dict[str, dict] = {}

    # 关联源 = 图边（25 号：关联列已删，动作绑定以 constrained_by 边为权威；
    # 无边 → 无装配，lint `_check_constraint_edge_alignment` 正向检查兜底提示）
    action_to_rules: dict[str, list[str]] = defaultdict(list)
    if edge_constraints:
        for action, rids in edge_constraints.items():
            action_to_rules[action].extend(rids)
        assoc_source = "graph_edges"
    else:
        assoc_source = "no_edges"

    for action, rule_ids in action_to_rules.items():
        for rule_id in rule_ids:
            if rule_id in rules:
                continue
            det = details.get(rule_id)
            if not det:
                continue  # 图边指向的约束在表中无定义，跳过（保底不误拦）
            if det["risk_type"] not in _STATICALLY_DECIDABLE_TYPES:
                continue  # data_loss/param_constraint 不进拦截
            if det["risk_type"] == "state_prerequisite":
                # 状态前置：对象由 action 名派生（25 号：关联列已删，能力名即对象约定）
                obj = "syncrule" if "rule" in action else "worknode" if "node" in action else "dbnode"
                forbidden = _derive_forbidden_states(rule_id, obj)
                if not forbidden:
                    # 语义为顺序类（如 must_use_stop_parse_yes），降级为阶段 D 会话时序
                    logger.debug("约束ID %s 无 _STATE 后缀，降级为阶段 D 会话时序判定", rule_id)
                    forbidden = set()
                    seq_semantic = True
                else:
                    seq_semantic = False
            else:
                # forbidden_sequence / threshold：不走状态推导（阶段 D/E 判定）
                obj = "syncrule" if "rule" in action else "worknode" if "node" in action else "dbnode"
                forbidden = set()
                seq_semantic = det["risk_type"] == "forbidden_sequence"
            message = re.sub(r"\*\*", "", det["text"]).strip()
            rules[rule_id] = {
                "action": action, "object": obj,
                "forbidden_states": forbidden, "severity": "critical",
                "risk_type": det["risk_type"],
                "sequence_semantic": seq_semantic,
                "source": assoc_source,
                "message": message if "{state}" in message else (
                    f"违反约束 [{det['risk_name']}]: {message}（当前状态: {{state}}）"
                ),
            }
    return rules


def _load_rules() -> dict:
    """加载规则：优先 BKN 三源 join，失败/为空时回退内置兜底。"""
    global _rules_cache
    if _rules_cache is not None:
        return _rules_cache
    _assemble_error = None
    try:
        rules = _assemble_rules()
        if rules:
            merged = dict(_FALLBACK_RULES)
            merged.update(rules)
            _rules_cache = merged
            logger.debug("risk_guard rules assembled: %d (source=%s)",
                         len(rules), next(iter(rules.values()))["source"])
        else:
            logger.warning("constraints.bkn 未装配出可判定规则, 使用兜底规则")
            _rules_cache = dict(_FALLBACK_RULES)
    except Exception as e:
        _assemble_error = f"{type(e).__name__}: {e}"
        logger.warning("BKN 规则装配失败(%s), 使用兜底规则", e)
        _rules_cache = dict(_FALLBACK_RULES)
    _emit_assembly_event(_rules_cache, error=_assemble_error)
    return _rules_cache


def _emit_assembly_event(rules: dict, error: str | None = None) -> None:
    """4-1 兜底可见化（22 号批 4，2026-10-12）：装配结果写**一条** usage 事件。

    - 只增日志：`check_action_risk` 的返回结构不变（22 号 §0.4-4）；
    - 每进程一次（`_load_rules` 有缓存守卫，重复调用不再写）；
    - 收益：可算 **BKN 约束覆盖率 = 1 − fallback 占比**（43 号 D9 此前抓不到）。
    """
    try:
        from .usage_log import log_usage
        from .config import BKN_ROOT
        fallback_ids = sorted(rid for rid, r in rules.items()
                              if str(r.get("source", "")) == "fallback")
        assembled = sum(1 for r in rules.values() if str(r.get("source", "")) != "fallback")
        log_usage("risk_guard_assembly",
                  record_type="process",     # 44 号 §6 批 3：进程级事件（无 args/confidence）
                  rules_assembled=assembled,
                  fallback_ids=fallback_ids,
                  assoc_source="graph_edges" if assembled else "no_edges",
                  bkn_root=str(BKN_ROOT),
                  degraded=assembled == 0,
                  error=error)
    except Exception:
        pass


def reset_rules_cache():
    """清空全部缓存（BKN reload 后或测试用）。

    `_rules_cache` / `_edges_cache` / `_states_cache` 都是 BKN_ROOT 派生缓存——
    测试用 `patch(BKN_ROOT)` 换根后不重置它们会互相污染（曾致真 BKN 测试误落兜底）。
    """
    global _rules_cache, _edges_cache, _states_cache
    _rules_cache = None
    _edges_cache = None
    _states_cache = None


def get_risk_rules() -> dict:
    """返回当前生效的规则表（浅拷贝，供 Tool 输出/测试）。"""
    return {k: dict(v) for k, v in _load_rules().items()}


# ═══════════════════════════════════════════════════════════════════
# 步6/7: 会话时序 + 时间窗判定
# ═══════════════════════════════════════════════════════════════════

def _check_forbidden_sequence(action: str, rules: dict) -> dict | None:
    """阶段 D：会话时序判定。检查是否有规则要求"先做 X 才能做 Y"。

    靠 _session_action_log（内存动作日志）判定前驱动作是否已发生。
    映射不到前驱动作的规则保持提示不拦截。"""
    # 可判定的前置操作：前驱动作可通过命令指纹或受控动作识别（设计：映射不到→保持提示）
    _PREREQ_KEYWORDS = {
        "must_dry_run_first": ("dry_run", "先 dry-run"),
        "must_dry_run_before_delete": ("dry_run", "先 dry-run"),
        "must_backup_before_write": ("backup", "先备份"),
        "must_backup_before_etcd_import": ("backup", "先备份"),
        "must_backup_target_table": ("backup", "先备份"),
        "must_use_stop_parse_yes": ("stop_parse_yes", "确认日志解析"),
    }
    # "确认"类规则：语义是用户确认而非前置操作，命中时只提示不拦截（blockable=False）
    _CONFIRM_RULES = {
        "must_confirm_reset_reason", "must_confirm_target_SCN",
        "must_confirm_connectivity_check",
    }
    performed = {e["action"] for e in _session_action_log}
    for rule_id, rule in rules.items():
        if rule.get("action") != action:
            continue
        if rule_id in _CONFIRM_RULES:
            # 确认类：需用户确认，返回提示但不设为 blockable
            msg = rule["message"]
            if "{state}" in msg:
                msg = msg.replace("{state}", "需用户确认")
            return {
                "passed": False, "rule_id": rule_id, "block_reason": msg,
                "action": action, "state": "", "severity": "info",
                "risk_type": "forbidden_sequence",
                "blockable": False,
            }
        req = _PREREQ_KEYWORDS.get(rule_id)
        if not req:
            continue
        prereq_action, _label = req
        if prereq_action not in performed:
            msg = rule["message"]
            if "{state}" in msg:
                msg = msg.replace("{state}", "前置动作未完成")
            return {
                "passed": False, "rule_id": rule_id, "block_reason": msg,
                "action": action, "state": "", "severity": rule["severity"],
                "risk_type": "forbidden_sequence",
            }
    return None


def _check_time_window(action: str, rules: dict) -> dict | None:
    """阶段 E：时间窗判定。hook 读本地时间，判定是否落在禁止窗口内。"""
    for rule_id, rule in rules.items():
        if rule.get("action") != action or rule.get("risk_type") != "threshold":
            continue
        m = _RE_TIME_WINDOW.search(rule["message"])
        if not m:
            continue

        def _to_min(t):
            h, mi = t.split(":")
            return int(h) * 60 + int(mi)
        start_min, end_min = _to_min(m.group(1)), _to_min(m.group(2))
        now = time.localtime()
        now_min = now.tm_hour * 60 + now.tm_min
        in_window = start_min <= now_min < end_min
        if in_window:
            msg = rule["message"]
            if "{state}" in msg:
                msg = msg.replace("{state}", f"{m.group(1)}-{m.group(2)}")
            return {
                "passed": False, "rule_id": rule_id, "block_reason": msg,
                "action": action, "state": "", "severity": rule["severity"],
                "risk_type": "threshold",
            }
    return None


def _log_session_action(action: str):
    """阶段 D：记录会话内已执行的动作（内存内，无副作用）。"""
    _session_action_log.append({"action": action, "ts": time.time()})


# ═══════════════════════════════════════════════════════════════════
# 步4/5: check_action_risk —— 分阶段拦截判定
# ═══════════════════════════════════════════════════════════════════

def _track_guard_shadow(action: str, state: str, rule_id: str, severity) -> None:
    """B4（44 号 §3.3 `guard_shadow`）：灰度期「本该拦却放行」的现场证据。

    **只在「passed=False 且 blockable=True」这一处发**——放行出口不埋点（否则每次放行一条，全是噪音）；
    `enforced` 取灰度开关 `config.RISK_GUARD_BLOCK`（`config.py:253`，`risk_guard.block=false` → 只记录不阻断），
    两者一对照就是「本该拦却放行」的实录（`provenance.yaml` 8 条 unknown 最需要的现场证据）。
    任何异常只丢日志：`check_action_risk` 的返回 dict **一个键都不改**（22 号 §0.4-4）。
    """
    try:
        from .config import RISK_GUARD_BLOCK
        from .observability import track
        track("guard_shadow", action=action, state=state, rule_id=rule_id,
              severity=severity, blockable=True, would_block=True,
              enforced=bool(RISK_GUARD_BLOCK))
    except Exception:
        pass


def _blocked_result(action: str, state: str, rule_id: str, rule: dict, msg: str,
                    source: str) -> dict:
    """**可拦出口的唯一收口**：所有「passed=False 且 blockable=True」的返回都走这里。

    为什么收口：B4 的留痕（`_track_guard_shadow`）与返回体构造绑在**同一处**——
    出口一多，裸 return 前手写 track 就会漏（上一轮就是把 track 放在单个 return 前，
    且作用域还没建立，等于没接）。新增可拦规则/新判定阶段时，只要经这里返回就自带留痕。

    返回 dict 的键与取值与旧实现逐字节一致（22 号 §0.4-4：埋点只增日志，不改主输出）。
    """
    _track_guard_shadow(action, state, rule_id, rule.get("severity"))
    return {
        "passed": False, "rule_id": rule_id, "block_reason": msg,
        "action": action, "state": state, "severity": rule.get("severity"),
        "risk_type": rule.get("risk_type", "state_prerequisite"),
        "source": source, "blockable": True,
    }


def check_action_risk(action: str, current_state: str = "") -> dict:
    """检查动作在当前对象状态下是否违反状态前置约束。

    Returns:
        {"passed": bool, "rule_id": str|None, "block_reason": str|None,
         "action": str, "state": str, "severity": str|None,
         "risk_type": str, "source": str, "blockable": bool}
    """
    action_norm = _ACTION_ALIASES.get(action, action)
    state = (current_state or "").strip().upper()
    rules = _load_rules()
    source = next(iter(rules.values())).get("source", "fallback") if rules else "fallback"

    # 状态前置判定（步3 装配的规则）——运维语义优先：先看对象能否执行，再看顺序/时间
    for rule_id, rule in rules.items():
        if rule.get("action") != action_norm:
            continue
        if state and state in rule.get("forbidden_states", set()):
            msg = rule["message"]
            if "{state}" in msg:
                msg = msg.replace("{state}", state)
            blockable = rule.get("risk_type") == "state_prerequisite" and bool(rule.get("forbidden_states"))
            if blockable:
                # B4：passed=False 且 blockable=True → 唯一收口（留痕 + 返回体同处构造）
                return _blocked_result(action_norm, state, rule_id, rule, msg, source)
            return {
                "passed": False, "rule_id": rule_id, "block_reason": msg,
                "action": action_norm, "state": state, "severity": rule["severity"],
                "risk_type": rule.get("risk_type", "state_prerequisite"),
                "source": source, "blockable": blockable,
            }

    # 阶段 D: 会话时序判定
    seq = _check_forbidden_sequence(action_norm, rules)
    if seq:
        seq["source"] = source
        seq["blockable"] = False  # 顺序语义无状态可判，不进阶段 B 拦截
        return seq

    # 阶段 E: 时间窗判定
    tw = _check_time_window(action_norm, rules)
    if tw:
        tw["source"] = source
        tw["blockable"] = False  # 时间窗语义不进阶段 B 拦截
        return tw

    return {
        "passed": True, "rule_id": None, "block_reason": None,
        "action": action_norm, "state": state, "severity": None,
        "risk_type": "", "source": source, "blockable": False,
    }


def pre_tool_call_hook(tool_name: str = "", args: dict = None, **kwargs):
    """Hermes pre_tool_call hook — 受控动作执行前的风险拦截。

    契约: 返回 {"action": "block", "message": ...} 阻断; 返回 None 放行。
    灰度模式 (RISK_GUARD_BLOCK=false) 只记录日志, 不阻断。
    阶段 B (block=true + blockable): 仅拦截可判定的状态前置约束（能推导出禁止状态集）。
    """
    if not RISK_GUARD_ENABLED:
        return None
    args = args if isinstance(args, dict) else {}

    # 路径1: 动作类工具（args 直接给 action/current_state）
    action = args.get("action") or args.get("operation")
    state = args.get("current_state") or args.get("state")

    # 路径2: 命令文本识别
    if not action and tool_name in _MUTATING_TOOLS:
        command = args.get("command") or args.get("code") or args.get("content") or ""
        action = _detect_action_from_command(command)
        if not state:
            m = re.search(
                r"(RUNNING|FULLSYNC|ABNORMAL|STOPPED|ONLINE|OFFLINE|NORMAL)",
                command, re.IGNORECASE,
            )
            if m:
                state = m.group(1).upper()

    if not action:
        return None
    action_norm = _ACTION_ALIASES.get(action, action)

    # 放行前记录会话动作（阶段 D 需要前驱动作日志）
    _log_session_action(action_norm)

    # B4 第 2 轮：hook **也是** B4 的真入口（Hermes 在受控动作执行前调它，与
    # check_action_risk Tool 是两条不同的调用路径）。track() 只在观测作用域内累积，
    # 故这里必须自己开一次 call_scope——否则 hook 路径上的「本该拦却放行」照样发不出去。
    # 无 task_id（Hermes 未传）时 scope 只是空转：轨迹写入本就要求 task_id 非空。
    from .observability import call_scope
    with call_scope("pre_tool_call", kwargs):
        result = check_action_risk(action_norm, state or "")
    if result["passed"]:
        return None

    msg = f"[RiskGuard:{result['rule_id']}] {result['block_reason']}"
    if not RISK_GUARD_BLOCK:
        logger.warning("RiskGuard(gray) would block: tool=%s action=%s state=%s rule=%s",
                       tool_name, action_norm, state, result["rule_id"])
        return None

    # 阶段 B: 仅拦截 blockable 规则（可判定的状态前置约束）
    if not result.get("blockable"):
        logger.warning("RiskGuard提示(不拦截): tool=%s action=%s rule=%s reason=%s",
                       tool_name, action_norm, result["rule_id"], result["block_reason"])
        return None

    logger.warning("RiskGuard blocked: tool=%s action=%s state=%s rule=%s",
                   tool_name, action_norm, state, result["rule_id"])
    return {"action": "block", "message": msg}
