#!/usr/bin/env python3
"""scan_gaps.py — 扫描 gap_log.jsonl 生成待补充清单

定期执行, 按 BKN 层分类展示缺失项, 辅助知识沉淀。

44 号 §3.4-5（批 4）：报表最前新增「缺口簇（归并去噪）」与「新形态」两段——
把 98.7% 的重复提示语压成计数，只把**新出现的形态**推到人眼前。

用法:
    python3 scan_gaps.py           # 生成报告（默认写 plugin/gaps_report.md）
    python3 scan_gaps.py --help    # 只打印用法，不读日志、不写任何文件
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

# 2A: 与运行时同源——日志路径从 plugin/config.py 读取（env LOG_DIR 可覆盖）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import resolve_log_path  # noqa: E402
from log_rotate import iter_data_files  # noqa: E402

GAP_LOG = resolve_log_path("gap_log.jsonl")  # 逻辑基名（实际文件含日期）
OUTPUT = Path(__file__).resolve().parent.parent / "gaps_report.md"

BKN_LAYER = {
    "query_product": "L1_product",
    "explain_architecture": "L2_architecture",
    "design_solution": "L3_scenarios",
    "list_scenarios": "L3_scenarios",
    "check_compatibility": "L4_compatibility",
    "diagnose_error": "L5_risks",
    "diagnose_db_link": "L5_risks",
    "diagnose_mechanism": "L5_mechanisms",
    "check_action_risk": "L5_actions",
    "get_prerequisites": "L5_actions",
    "resolve_relation": "relations",
    "resolve_operation": "L5_actions",
    "search_qdrant": "L6_fallback",
}

# ── 来源过滤（22 号 §1.1 判据）──────────────────────────────────────────
# 自身写入者的行首**带空格**（`json.dumps` 默认分隔符）；外来写入者用紧凑分隔符
# （`{"tool":"…`，逗号后无空格）。2026-09-24 那批 45 行由后者写成，内容为**已退场的旧文案**
# （「返回内容过短」「关键字段 diagnosis 内容过短」）——统计前必须按来源过滤，否则缺口簇排序被带偏。
OWN_LINE_PREFIX = '{"tool": '

#: 归一化占位符（顺序敏感）：UUID → 路径 → 引号内数字 → 其余数字。
#: 一律用显式字符类——`plugin/**` 禁用 `\\s` `\\d` `\\w` `\\b`（test_bkn_boundary 有牙齿）。
_PLACEHOLDERS = (
    (re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"), "<uuid>"),
    (re.compile(r"(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+"), "<path>"),
    (re.compile(r"'[0-9]+'"), "'<n>'"),
    (re.compile(r"[0-9]+"), "<n>"),
    (re.compile(r"\.\.\."), "…"),
)

#: 「建议归属」四档（与 02 号 §0 的判定口径对齐；取代 22 号原写的三档含「BKN」）。
#: 判据是**文案特征**，只出建议——最终归属由人/复盘定（与 dimension:unknown 人工评审同一纪律）。
#: **顺序敏感**：先看文案里**显式的处置建议**（「建议查 Qdrant 补充…」），再看结构缺失，最后看特征词——
#: 否则「缺详细参数/版本」会被「参数/版本」带去 Skill，而它的补救其实在语料里。
OWNER_RULES = (
    ("Qdrant 语料", ("建议查 Qdrant", "查 Qdrant 补充", "语料", "案例", "修复步骤", "排查步骤")),
    ("本体/结构", ("缺少关键字段", "内容过短", "缺字段", "prerequisite", "缺少关系", "无边")),
    ("Skill", ("参数", "命令", "阈值", "版本", "路径", "端口")),
)
OWNER_DEFAULT = "机制字典"

# ── 归并去噪（44 号 §3.4-5，批 4）──────────────────────────────────────
# 为什么要有这一层：`get_prerequisites` 的固定提示语（「BKN 仅提供基础骨架，建议查 Qdrant
# 补充详细参数/案例/版本信息」）在 gap_log 里出现过 5258/5331 次（98.7%），彼此只差**具体值**；
# 不归并就是各占一行的五千条清单 → 报表 401 字节、零信息量。归并的键必须是「形态」而非「这一条」。
# 注：正则一律用显式字符类——`plugin/**` 禁用反斜杠简写类（test_bkn_boundary 硬机检）。
GAP_SKELETON_MAX = 120   # 骨架截断长度（超出部分丢弃：长尾差异留给「新形态」段暴露）
CLUSTER_TOP_N = 20       # 「缺口簇」段展示条数（44 号 §3.4-5 指定 Top 20）
NEW_SHAPE_DAYS = 7       # 「新形态」窗口：最近 7 个自然日（含日志最大日期当天）

#: 引号字符集：直引号 + 中文弯引号（具体值可能是 'failover…' / "STOPPED" / 「…」）
_QUOTE_CHARS = "'\u0022\u2018\u2019\u201c\u201d"
#: 引号值 → <VAL>：**先于**数字处理，且惰性匹配——`'a' 与 'b'` 是两个值，不是一个长值
_QUOTED_VALUE_RE = re.compile("[" + _QUOTE_CHARS + "][^" + _QUOTE_CHARS + "]{0,120}?[" + _QUOTE_CHARS + "]")
#: 数字 → <N>：整数/小数/百分数一视同仁（98.7% → <N>），阈值与条数同理
_NUMBER_RE = re.compile(r"[0-9]+(?:[.][0-9]+)*%?")


def _norm_gap(text: str) -> str:
    """把一条缺口文案压成「骨架」：引号值 → <VAL>，数字 → <N>，空白折叠，截 120 字。

    规则（44 号 §3.4-5）：只有具体值（错误码/条数/阈值/状态字面量）不同的同形缺口必须
    能聚成一簇，否则「一长串清单」不可读。**顺序敏感**：先引号值再数字——`'failover-2026'`
    整体记为 <VAL>，裸的 `48` 记为 <N>。
    **幂等**：骨架里已无数字/引号/连续空白，再压一次仍是它自己（测试硬断言）。
    """
    raw = str(text or "")
    try:
        out = _NUMBER_RE.sub("<N>", _QUOTED_VALUE_RE.sub("<VAL>", raw))
    except Exception:
        # ③ 归一化失败不得影响主流程：退化为「只折叠空白」的最弱形态
        return " ".join(raw.split())[:GAP_SKELETON_MAX]
    return " ".join(out.split())[:GAP_SKELETON_MAX]


def _md_cell(text: str) -> str:
    """表格单元格转义：竖线不转义会把一行骨架切成两列。"""
    return str(text or "").replace("|", "\\|")


def normalize_gap_text(text: str) -> str:
    """归一化缺口文案：UUID/路径/数字 → 占位符，空白折叠，截 160 字。

    目的：只有 UUID、路径、容量数字不同的**同一类**缺口，要能聚成一簇。
    """
    out = str(text or "")
    for rx, rep in _PLACEHOLDERS:
        out = rx.sub(rep, out)
    return " ".join(out.split())[:160]


def suggest_owner(text: str) -> str:
    """按文案特征给「建议归属」（四档；默认机制字典 = M-1 的 HOW 层）。"""
    for owner, keys in OWNER_RULES:
        if any(k in text for k in keys):
            return owner
    return OWNER_DEFAULT


def load_own_entries(gap_log: Path) -> tuple:
    """只读**自身写入者**的行；返回 (entries, 被过滤的外来行数)。

    为什么不改 `log_rotate.load_jsonl_entries`：它被别处调用，改它影响面更大；
    判据（行首 `{"tool": `）只在本脚本内生效即可。
    """
    entries, foreign = [], 0
    for path in iter_data_files(gap_log):
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for line in lines:
            if not line.strip():
                continue
            if not line.startswith(OWN_LINE_PREFIX):
                foreign += 1
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                foreign += 1
    return entries, foreign


def _ts_date(entry: dict) -> str:
    """条目时间戳 → YYYY-MM-DD（坏值返回空串）。"""
    try:
        return datetime.fromtimestamp(float(str(entry.get("timestamp") or 0))).strftime("%Y-%m-%d")
    except (ValueError, OSError):
        return ""


def build_clusters(unresolved: list, top_n: int) -> list:
    """按 `(tool × 归一化文案)` 聚类，按「频次 × 影响面」排序返回 Top N。

    影响面 = 该簇内**不同 params 组合数**（＝这簇覆盖了几个现场场景）。
    """
    clusters = defaultdict(list)
    for g in unresolved:
        for text in g.get("gaps") or []:
            key = (str(g.get("tool", "")), normalize_gap_text(text))
            clusters[key].append(g)
    rows = []
    for (tool, text), items in clusters.items():
        scenes = len({json.dumps(i.get("params") or {}, ensure_ascii=False, sort_keys=True)
                      for i in items})
        dates = sorted(d for d in (_ts_date(i) for i in items) if d)
        rows.append({
            "tool": tool, "text": text, "count": len(items), "scenes": scenes,
            "first": dates[0] if dates else "—", "last": dates[-1] if dates else "—",
            "owner": suggest_owner(text),
        })
    rows.sort(key=lambda r: (-(r["count"] * max(r["scenes"], 1)), r["tool"], r["text"]))
    return rows[:top_n]


# ── 归并去噪：缺口簇 / 新形态（44 号 §3.4-5，批 4）────────────────────


def _entry_gaps(entry: dict) -> list:
    """取一条记录的缺口文案列表；缺字段/坏类型一律当空（③ 异常不影响主流程）。"""
    try:
        gaps = entry.get("gaps") or []
        return [str(x) for x in gaps if str(x or "").strip()]
    except Exception:
        return []


def build_gap_clusters(unresolved: list) -> tuple:
    """按 `(tool, _norm_gap(gaps[0]))` 归并去噪，返回 (Top N 簇, 全部簇, 总缺口数)。

    **口径**（44 号 §3.4-5）：每条记录只看**首个缺口** `gaps[0]`——同一次调用的其余缺口
    是同一现场的附属信息，全量展开会把簇计数重复放大。这与既有的「缺口簇 Top N」段
    （全量展开 ＋ 频次×影响面排序，22 号批 0-2）是两套口径：两段并存，互不改语义。
    排序：计数降序（同计数按 tool、骨架稳定排序，保证报告可 diff）。
    """
    buckets = defaultdict(list)
    total = 0
    for g in unresolved or []:
        gaps = _entry_gaps(g)
        if not gaps:
            continue
        total += 1
        buckets[(str(g.get("tool", "")), _norm_gap(gaps[0]))].append(g)
    rows = []
    for (tool, skeleton), items in buckets.items():
        dates = sorted(d for d in (_ts_date(i) for i in items) if d)
        rows.append({
            "tool": tool, "skeleton": skeleton, "count": len(items),
            "days": len(set(dates)),
            "first": dates[0] if dates else "—",
            "last": dates[-1] if dates else "—",
        })
    rows.sort(key=lambda r: (-r["count"], r["tool"], r["skeleton"]))
    return rows[:CLUSTER_TOP_N], rows, total


def build_new_shapes(all_clusters: list) -> list:
    """只挑「最近 NEW_SHAPE_DAYS 天内**首次**出现」的骨架（44 号 §3.4）。

    为什么以**日志中最大日期**为基准而不是 today：日志是快照，离线分析/观测期结束时用
    today 会把整批骨架判成「新形态」，噪音原样回来。窗口含最大日期当天，共 N 个自然日。
    为什么单独成段：重复项没有信息量，**真正要看的是新出现的形态**（44 号 §3.4）。
    """
    dated = [c for c in (all_clusters or []) if c.get("first") and c["first"] != "—"]
    if not dated:
        return []
    try:
        newest = max(c["first"] for c in dated)
        cutoff = (datetime.strptime(newest, "%Y-%m-%d")
                  - timedelta(days=NEW_SHAPE_DAYS - 1)).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return []
    rows = [c for c in dated if c["first"] >= cutoff]
    rows.sort(key=lambda c: (c["first"], c["count"]), reverse=True)
    return rows


def render_gap_cluster_section(unresolved: list) -> list:
    """生成「缺口簇（归并去噪）」＋「新形态」两段（44 号 §3.4-5）。

    放在报表**最前**：98.7% 的重复项没有信息量，这两段是当前唯一有信息量的部分。
    **只增段**：既有各段的语义由调用方保证不动（本函数只返回新行）。
    """
    top, all_rows, total = build_gap_clusters(unresolved)
    lines = ["\n## 缺口簇（归并去噪 · 44 号 §3.4-5）\n"]
    if not all_rows:
        lines.append("（未解决记录里没有可归并的缺口文案）\n")
        return lines
    largest = all_rows[0]
    share = (largest["count"] / total * 100) if total else 0.0
    lines.append("> 口径：按 `(tool, gaps[0] 骨架)` 归并计数，降序取 Top "
                 f"{len(top)}。骨架 = 引号值 → `<VAL>`、数字 → `<N>`、"
                 "空白折叠、截 120 字（`_norm_gap`）。**只看形态、不看单条**"
                 "——同形记录各占一行正是 401 字节报表的成因。\n")
    lines.append("| # | 计数 | 工具 | 骨架 | 涉及天数 | 首次 | 最近 |")
    lines.append("|---|------|------|------|---------|------|------|")
    for i, c in enumerate(top, 1):
        lines.append(f"| {i} | {c['count']} | `{_md_cell(c['tool'])}` | "
                     f"{_md_cell(c['skeleton'])} | {c['days']} | {c['first']} | {c['last']} |")
    if len(all_rows) > len(top):
        lines.append(f"\n> Top {len(top)} 之外另有 {len(all_rows) - len(top)} 簇（长尾；"
                     "需要时调大 `CLUSTER_TOP_N`）。")
    lines.append(f"\n> **汇总**：总缺口数 {total} · 簇数 {len(all_rows)} · "
                 f"最大簇占比 {share:.1f}%（`{_md_cell(largest['tool'])}` · "
                 f"{_md_cell(largest['skeleton'])} · {largest['count']} 条）\n")

    new_shapes = build_new_shapes(all_rows)
    lines.append(f"\n## 新形态（最近 {NEW_SHAPE_DAYS} 天内首次出现 · 相对日志最大日期）\n")
    lines.append("> 重复项没有信息量，**真正要看的是新出现的形态**（44 号 §3.4）："
                 "窗口内的新骨架才是本轮该分诊的候选。\n")
    if not new_shapes:
        lines.append("（窗口内无首次出现的骨架——缺口全是已知形态）\n")
    else:
        lines.append("| 首次 | 计数 | 工具 | 骨架 | 最近 |")
        lines.append("|------|------|------|------|------|")
        for c in new_shapes:
            lines.append(f"| {c['first']} | {c['count']} | `{_md_cell(c['tool'])}` | "
                         f"{_md_cell(c['skeleton'])} | {c['last']} |")
        lines.append("")
    return lines


def parse_args():
    ap = argparse.ArgumentParser(
        description="扫描 gap_log.jsonl 生成 BKN 待补充清单报告。不带参数时使用默认路径。")
    ap.add_argument("--log", type=Path, default=GAP_LOG,
                    help=f"gap_log.jsonl 路径（默认: {GAP_LOG}）")
    ap.add_argument("--output", "-o", type=Path, default=OUTPUT,
                    help=f"报告输出路径（默认: {OUTPUT}）")
    ap.add_argument("--top", type=int, default=10,
                    help="缺口簇 Top N（默认 10；排序 = 频次 × 影响面）")
    return ap.parse_args()

def main():
    args = parse_args()
    gap_log = args.log
    output = args.output

    files = iter_data_files(gap_log)
    if not files:
        print("gap_log 数据文件不存在（新旧命名均未找到）, 无缺失记录")
        return

    # 来源过滤（22 号 §1.1）：外来写入者的行不入统计——否则它们会把缺口簇排序带偏
    gaps, foreign = load_own_entries(gap_log)

    unresolved = [g for g in gaps if not g.get("resolved", False)]
    if not unresolved:
        # 就地首轮 S1-P2（2026-10-12）：此前这里直接 return → **报告文件不重写**，留下与源数据矛盾的
        # 陈旧报告（实测：源数据 4/4 resolved，报告仍写「未解决 4」）。现改为照常重写（显式 0）——
        # 报告是缺口分诊与第三期信号②的输入，"当前没有缺口"本身就是必须落盘的结论。
        report = "\n".join([
            "# BKN 待补充清单\n",
            f"> 生成日期: {date.today().isoformat()} | 源: {gap_log}"
            f"（共 {len(gaps)} 条记录，未解决 0 条）"
            f"｜已过滤外来写入者 {foreign} 行（判据：行首 `{{\"tool\": `——带空格）\n",
            "共 0 条缺失——**所有缺失已解决**（本报告由 `scan_gaps.py` 照常重写；"
            "缺口清零不等于停止观测：新缺口会在下次运行前累积出现）\n",
        ])
        output.write_text(report, encoding="utf-8")
        print("所有缺失已解决")
        print(f"报告已重写: {output}（未解决 0 条——避免留下与源数据矛盾的陈旧报告）")
        return

    by_layer = defaultdict(list)
    for g in unresolved:
        layer = BKN_LAYER.get(g["tool"], "unknown")
        by_layer[layer].append(g)

    # ── 按诊断类聚合（O-域 gap 反哺闭环）──
    # classes 字段由 tools._diag_class_extra 在诊断类 Tool 的 gap 上写入。
    # 这给出「数据驱动的类扩充依据」：某类缺口次数高 → 该类知识/映射需补强；
    # dimension:unknown 次数高 → 有实际错误码长期无法归类，是 T-Box 扩维度的信号。
    by_class = defaultdict(list)
    for g in unresolved:
        for c in g.get("classes") or []:
            by_class[c].append(g)

    # ── 按未命中原文聚合（批 3-7：盲区 3「猜错但查到了别的」可统计）──
    # synonym_candidates 由 tools._synonym_candidates_extra 在标识符解析失败时写入
    # （resolve_synonym 未命中 → BM25 top-1 候选 + 分数）。
    # 判据（16 号批 3-1）：同一未命中原文出现 ≥3 次，且检索命中分散在多个不同实体
    # （或 top-1 分数持续偏低）= LLM 拿不准 → 值得固化进同址字段；命中集中且高分则不用管。
    by_unmatched = defaultdict(list)
    for g in unresolved:
        if g.get("synonym_candidates"):
            text = json.dumps(g.get("params") or {}, ensure_ascii=False)
            by_unmatched[text].append(g)

    lines = [
        "# BKN 待补充清单\n",
        f"> 生成日期: {date.today().isoformat()} | 源: {gap_log}"
        f"（共 {len(gaps)} 条记录，未解决 {len(unresolved)} 条）"
        f"｜已过滤外来写入者 {foreign} 行（判据：行首 `{{\"tool\": `——带空格）\n",
        f"共 {len(unresolved)} 条缺失\n",
    ]

    # ── 归并去噪段（44 号 §3.4-5，批 4）：放在报表最前 ──────────────────
    # 98.7% 的重复提示语没有信息量，「缺口簇 / 新形态」是当前唯一有信息量的部分。
    # ③ 全程异常不影响主流程：本段整体兜底，出错只留一行提示，既有各段照常产出。
    try:
        lines.extend(render_gap_cluster_section(unresolved))
    except Exception as exc:
        lines.append(f"\n## 缺口簇（归并去噪）\n\n（本段生成失败：{exc}；不影响既有段）\n")


    # ── 缺口簇 Top N（22 号批 0-2）──────────────────────────────────────
    # 把「一长串清单」变成「可执行队列」：按 (tool × 归一化文案) 聚类，
    # 以 频次 × 影响面 排序；每条簇都能定位到具体 Tool 与文案，并给**建议归属**（四档，见 OWNER_RULES）。
    clusters = build_clusters(unresolved, args.top)
    if clusters:
        lines.append(f"\n## 缺口簇 Top {len(clusters)}（按 频次 × 影响面；建议归属由人复核）\n")
        lines.append("| # | Tool | 归一化文案 | 条数 | 场景数 | 首次 | 末次 | 建议归属 |")
        lines.append("|---|------|-----------|------|--------|------|------|----------|")
        for i, c in enumerate(clusters, 1):
            text = c["text"].replace("|", "\\|")
            lines.append(f"| {i} | `{c['tool']}` | {text} | {c['count']} | {c['scenes']} | "
                         f"{c['first']} | {c['last']} | {c['owner']} |")
        lines.append("\n> **建议归属四档**：本体/结构（该由本体承载的字段或边缺失）· Skill（参数/命令/阈值/版本）· "
                     "Qdrant 语料（含义与处置经验）· 机制字典（HOW 层，见 `doc/optimize/32 号`）。"
                     "判定口径见 `doc/build/demo_product-bkn/02-bkn_design_philosophy.md` §0。\n"
                     "> **例外（Q27）**：`缺少关键字段: retrieval_guide` 这类**未登记码**造成的缺口，"
                     "按 02 号 §0 **不新增码行**——走含义入口（消息文本 → 检索 → 兜底），其处置在 32 号候选一，不在本表四档内。")
    else:
        lines.append("\n## 缺口簇\n\n（本批无缺口簇——观测期计数已从 0 重开，等新数据积累）\n")

    if by_class:
        lines.append("\n## 按诊断类聚合（O-域 gap 反哺）\n")
        lines.append("| 诊断类 | 缺口次数 | 涉及 Tool |")
        lines.append("|--------|---------|-----------|")
        for c in sorted(by_class, key=lambda k: (-len(by_class[k]), k)):
            items = by_class[c]
            tools = ", ".join(sorted({i["tool"] for i in items}))
            lines.append(f"| {c} | {len(items)} | {tools} |")
        if "dimension:unknown" in by_class:
            lines.append(
                f"\n> `dimension:unknown` 计 {len(by_class['dimension:unknown'])} 次 "
                "—— 这些错误码/症状长期无类可归，是 T-Box 扩类的优先候选（见 §2.6 人工评审）。"
            )
        uncovered = len(unresolved) - sum(len(v) for v in by_class.values())
        if uncovered > 0:
            lines.append(f"> 另有 {uncovered} 条缺口来自非诊断类 Tool，不参与按类聚合。")

    if by_unmatched:
        lines.append("\n## 按未命中原文聚合（同义词反哺候选）\n")
        lines.append("> `params` = 用户原文（未归一化）；`top-1 候选` = 该次解析失败时 BM25 检索命中的")
        lines.append("> 最近实体及其分数。**固化判据**：同一原文出现 ≥3 次且候选分散/低分 → 写进同址字段；")
        lines.append("> 命中集中且高分说明 LLM 联想得稳，不用管（16 号批 3-1）。\n")
        lines.append("| 未命中原文（params） | 次数 | top-1 候选（最近一次） | 涉及 Tool |")
        lines.append("|---------------------|------|----------------------|-----------|")
        for text in sorted(by_unmatched, key=lambda k: (-len(by_unmatched[k]), k)):
            items = by_unmatched[text]
            cands = items[-1].get("synonym_candidates") or []
            cand_str = "; ".join(f"{cid} ({score})" for cid, score in cands)
            tools = ", ".join(sorted({i["tool"] for i in items}))
            lines.append(f"| {text} | {len(items)} | {cand_str} | {tools} |")

    for layer in sorted(by_layer):
        items = by_layer[layer]
        lines.append(f"\n## {layer} ({len(items)} 条)\n")
        lines.append("| Tool | 参数 | 缺失项 |")
        lines.append("|------|------|--------|")
        for item in items[:30]:
            params = json.dumps(item["params"], ensure_ascii=False)
            gaps_str = "; ".join(item["gaps"])
            lines.append(f"| {item['tool']} | {params} | {gaps_str} |")

    report = "\n".join(lines)
    output.write_text(report, encoding="utf-8")
    print(f"报告已生成: {output}")
    print(f"未解决: {len(unresolved)} 条")

if __name__ == "__main__":
    main()
