#!/usr/bin/env python3
"""code_id_coverage.py — 错误码 ID 空间覆盖（24 号批 C1）

**为什么需要**：本体声称拥有错误码的**规范 ID 空间**（`bkn/SKILL.md:26`「清单在边里」；
`bkn/templates/error.bkn:19-20`「不要在任何 `.bkn` 里重建错误码/症状表」）。
但 Skills 里**成表教学**的码长期多于已登记的码——用户拿着日志里的码来问时，
`resolver.get_risk()` 对未登记码返回 `{}`，只能落兜底。

**两个模式**（刻意分开）：
- `--scan`（盘点，**仅供参考**）：扫全仓的「码形态」token 分类计数。
  **不再构成待办**——码不进本体、也不在任何一层穷举（用户裁定 Q27，见《BKN 设计哲学》§0）。
- `--check`（契约，**已换范式**）：校验 `plugin/error_semantics.yaml` 的**有界完备性**——
  ① 每个检查维度（除 `unknown`）至少一条规则 ② 规则里**不得出现码形态**（Q27 红线）
  ③ `fallback` 存在 ④ 规则 id 唯一、`match` 非空。
  旧契约「教学码必须在边里登记」随错误码退出本体而**作废**（它要求的就是旧的枚举范式）。

**噪声是设计出来的**：原样扫全仓会得到大量假阳性（UUID 片段、模式目录 ID `LP-*`、
行号区间 `L312-315`、`head -200` 这类 shell 参数、resolver 派生的机械变体）。
`--scan` 用**权威来源**过滤：厂商前缀取自 `plugin/constants.py::DB_ERROR_PREFIXES`，
历史语境取自 `_HISTORICAL` 类词表——被过滤的每一类都在报告里写明理由，不静默丢。

用法:
  python3 scripts/code_id_coverage.py --scan            # 打印审计清单
  python3 scripts/code_id_coverage.py --scan --out /tmp/x.md
  python3 scripts/code_id_coverage.py --check           # 教学契约（退出码 0/1）

退出码: 0 通过 / 1 契约不满足 / 2 环境错误
依据: doc/optimize/24-ontology-build-sources.md §批 B-3（第一次落地）与本文件头部说明；审计报告 §1
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOPOLOGY = ROOT / "bkn" / "relations" / "process_topology.bkn"
CONSTANTS = ROOT / "plugin" / "constants.py"
SEMANTICS = ROOT / "plugin" / "error_semantics.yaml"
CODES = ROOT / "plugin" / "error_codes.yaml"   # 63 号：官方码表侧车（Q27：不入本体）
DIMENSIONS_FILE = ROOT / "bkn" / "objects" / "dimensions.bkn"

#: 码形态（显式字符类；plugin/** 约定禁 \\d \\w \\s \\b）
CODE_SHAPE = re.compile(r"(-[0-9]{3,}|[A-Z][A-Z0-9]{1,6}-[0-9]{3,})")

# 裸 4-5 位数字：官方码表以数字为键（4002 / 4071），写成裸数字同样是按码枚举
# （Q27 的精神）；而 CODE_SHAPE 只认 -NNNN / PREFIX-NNNN，会漏掉它。
BARE_NUM = re.compile(r"(?<![0-9A-Za-z])[0-9]{4,5}(?![0-9])")
DIMENSION_ID = re.compile(r"`(dimension:[a-z_]+)`")


def ontology_dimensions() -> set:
    """本体登记的检查维度 ID（在 `bkn/objects/dimensions.bkn`）。"""
    if not DIMENSIONS_FILE.is_file():
        return set()
    return set(DIMENSION_ID.findall(DIMENSIONS_FILE.read_text(encoding="utf-8")))

#: 边行（`- \`error:<码>\` → \`<目标>\``）——suspected_in 与 has_class 两段都算"已登记"
EDGE_ROW = re.compile(r"^[ \t]*-[ \t]+`error:([^`]+)`[ \t]*→[ \t]*`([^`]+)`")
#: 内部码形态 `-NNNN`（显式字符类：本项目约定避免 \\d 一类简写）
INTERNAL_CODE = re.compile(r"(?<![A-Za-z0-9_.-])(-[0-9]{3,5})(?![0-9])")
#: 厂商码形态 `PREFIX-NNNN`（前缀须在 DB_ERROR_PREFIXES 里，否则按噪声处理）
VENDOR_CODE = re.compile(r"(?<![A-Za-z0-9_.-])([A-Z][A-Z0-9]{1,6}-[0-9]{3,6})(?![0-9])")
#: 历史语境（提到退场/删除不算"现行指路"）——沿用 lint_bkn 的 `_HISTORICAL` 先例
HISTORICAL = ("已废止", "已删除", "已退场", "已归档", "旧架构", "历史文档", "迁出")

SCAN_PATTERNS = (
    "skill/**/*.md", "bkn/**/*.md", "bkn/**/*.bkn",
    # 注：`doc/update/` 已于 2026-10-15 整体清理（74 号批 S-2）；模式**保留**（历史/外部树仍可能命中）
    "doc/update/**/*.md", "doc/process/**/*.md",
    "plugin/*.py", "log-mode/**/*.md", "log-mode/**/*.jsonl",
)
SKIP_PARTS = {".git", "__pycache__", ".pytest_cache", "archive", "_archived"}

#: **教学契约**：这些码在 Skills 里被"成表教学"（表格行 / 专文小节），必须已登记或在 EXEMPT 里。
#: 键 = 码；值 = {"src": [出处…], "to": 目标（供 --scan 标为"契约内待落盘"）, "why": 一句话}
TEACHING_CODES: dict = {
    # ── 装载侧「错误分类速查」+「数据装载错误码速查」（load-log-analysis.md；语境=装载日志）──
    "ORA-01918": {"src": ["skill/demo_product-log-analyzer/references/load-log-analysis.md:53"], "to": "process:ialoader", "why": "目标库未创建 schema 用户 → 该 schema 的 TYPE 全跳过（用户/Schema 错误）"},
    "ORA-02303": {"src": ["skill/demo_product-log-analyzer/references/load-log-analysis.md:61"], "to": "process:ialoader", "why": "目标库同名 TYPE 有依赖，无法直接替换（TYPE 对象错误·DictLd）"},
    "ORA-02260": {"src": ["skill/demo_product-log-analyzer/references/load-log-analysis.md:71"], "to": "process:ialoader", "why": "表已有主键，重复 ALTER ADD PRIMARY KEY（IdxLoader 阶段）"},
    "ORA-02261": {"src": ["skill/demo_product-log-analyzer/references/load-log-analysis.md:72"], "to": "process:ialoader", "why": "unique/primary key 已存在（IdxLoader 阶段）"},
    "ORA-00955": {"src": ["skill/demo_product-log-analyzer/references/load-log-analysis.md:73"], "to": "process:ialoader", "why": "对象名已被占用（索引/约束名冲突）"},
    "ORA-01756": {"src": ["skill/demo_product-log-analyzer/references/load-log-analysis.md:81"], "to": "process:ialoader", "why": "DDL 含中文引号等导致 SQL 解析失败"},
    "ORA-04063": {"src": ["skill/demo_product-log-analyzer/references/load-log-analysis.md:98"], "to": "process:ialoader", "why": "视图因依赖对象缺失编译失败（目标对象缺失·DictLd）"},
    "ORA-01031": {"src": ["skill/demo_product-log-analyzer/references/load-log-analysis.md:99"], "to": "process:ialoader", "why": "目标用户无 GRANT/CREATE 权限"},
    "ORA-01749": {"src": ["skill/demo_product-log-analyzer/references/load-log-analysis.md:100"], "to": "process:ialoader", "why": "自我授权被 Oracle 拒绝（DictLd 阶段）"},
    "ORA-01400": {"src": ["skill/demo_product-log-analyzer/references/load-log-analysis.md:150"], "to": "process:ialoader", "why": "cannot insert NULL（IRP/URP 数据行装载）"},
    "ORA-00001": {"src": ["skill/demo_product-log-analyzer/references/load-log-analysis.md:151"], "to": "process:ialoader", "why": "唯一约束冲突（URP.RM 冲突管理）"},
    "ORA-01410": {"src": ["skill/demo_product-log-analyzer/references/load-log-analysis.md:152"], "to": "process:ialoader", "why": "invalid ROWID（URP.RM）"},
    "ORA-24381": {"src": ["skill/demo_product-log-analyzer/references/load-log-analysis.md:153"], "to": "process:ialoader", "why": "error(s) in array DML——批量装载包装错误（内嵌具体行级码）"},
    "ORA-39780": {"src": ["skill/demo_product-log-analyzer/references/load-log-analysis.md:154"], "to": "process:ialoader", "why": "Direct Path context aborted（TabLd，InsertDp.cpp）"},
    "ORA-01451": {"src": ["skill/demo_product-log-analyzer/references/load-error-ora01451-urp-pk-null.md:13"], "to": "process:ialoader", "why": "DDL 并行时序竞争：Ld[0] MODIFY 与 Ld[1] DROP PK 竞争（专文）"},
    # ── 单码 ──
    "-3522": {"src": ["skill/demo_product-iadebug/SKILL.md:159"], "to": "process:ialoader", "why": "Loader IPC 端口未响应（loader 未就绪/端口配置错误）"},
    "-4074": {"src": ["skill/demo_product-log-analyzer/references/full-failure-triage.md:16"], "to": "process:ialoader", "why": "Loader 返回 -4074 → 全量启动失败模式（查目标端配置/端口冲突/规则状态）"},
    # ── 注入目录（S4；并合自候选 C-20261011-01，其证据见该候选 review.md §3）──
    "-4000": {"src": ["skill/demo_product-test-case-templates/references/fault-injection-catalog.md:12"], "to": "process:iatrack", "why": "数据库连接错误（连接源库失败）"},
    "-4001": {"src": ["skill/demo_product-test-case-templates/references/fault-injection-catalog.md:22"], "to": "process:iahelper", "why": "控制连接断开（节点侧控制通道）"},
    "-4003": {"src": ["skill/demo_product-test-case-templates/references/fault-injection-catalog.md:51"], "to": "dimension:resource", "why": "磁盘空间不足（跨进程，锚维度）"},
    "-4004": {"src": ["skill/demo_product-test-case-templates/references/fault-injection-catalog.md:68"], "to": "process:iatrack", "why": "RAC 实例连接失败"},
    "-4005": {"src": ["skill/demo_product-test-case-templates/references/fault-injection-catalog.md:81"], "to": "process:iatrack", "why": "数据字典导出失败"},
    "-4006": {"src": ["skill/demo_product-test-case-templates/references/fault-injection-catalog.md:96"], "to": "process:iatrack", "why": "分析线程退出/HisReader 崩溃"},
    "-4007": {"src": ["skill/demo_product-test-case-templates/references/fault-injection-catalog.md:111"], "to": "process:iatrack", "why": "ASM 实例连接失败"},
    "-4008": {"src": ["skill/demo_product-test-case-templates/references/fault-injection-catalog.md:124"], "to": "process:iatrack", "why": "TF 文件数据错误"},
    "-4009": {"src": ["skill/demo_product-test-case-templates/references/fault-injection-catalog.md:137"], "to": "process:iahelper", "why": "等待超时（网络/控制通道）"},
    "-4012": {"src": ["skill/demo_product-test-case-templates/references/fault-injection-catalog.md:153"], "to": "process:ialoader", "why": "字符集不一致（两端不匹配 → 脏数据）"},
}

#: 显式豁免（每条必须写理由）。**不是"以后再说"的抽屉**——确无进程/维度可锚才允许在此。
EXEMPT: dict = {
    "-4030": "版本不兼容类：同一码在 track 与 dumper 两个进程都出现（iadebug-version-compat.md:12-13），"
             "suspected_in 是 N:1，硬锚会误导——保持未登记（走兜底），待机制层（29 号 M-1，卡 Q23/Q26）定表达方式",
    "-3565": "版本不兼容类（同上，helper 侧）：Unknown message = 进程不识别该 IPC 消息；同 -4030 理由",
}


def read_edges() -> dict:
    edges: dict = defaultdict(list)
    for line in TOPOLOGY.read_text(encoding="utf-8").splitlines():
        m = EDGE_ROW.match(line)
        if m:
            edges[m.group(1)].append(m.group(2))
    return dict(edges)


def db_prefixes() -> tuple:
    """厂商前缀（权威来源 = plugin/constants.py::DB_ERROR_PREFIXES）——用于过滤 UUID 片段等噪声。

    前缀键**含尾随的 `-`**（如 `"ORA-"`），故字符类必须收 `-`：只收字母数字会解析出空表，
    结果是所有厂商码被当噪声丢掉（写这段时踩过）。
    """
    prefixes = set()
    text = CONSTANTS.read_text(encoding="utf-8")
    inside = False
    row = re.compile(r'^[ \t]*"([A-Za-z0-9-]+)"')
    for line in text.splitlines():
        if line.startswith("DB_ERROR_PREFIXES"):
            inside = True
            continue
        if inside:
            if line.strip().startswith("}"):
                break
            if line.lstrip().startswith("#"):
                continue
            m = row.match(line)
            if m:
                prefixes.add(m.group(1).upper().rstrip("-"))
    return tuple(sorted(prefixes))


def scan_files() -> list:
    out = []
    for pat in SCAN_PATTERNS:
        out.extend(p for p in ROOT.glob(pat) if not any(x in SKIP_PARTS for x in p.parts))
    return sorted(set(out))


def scan(edges: dict) -> dict:
    prefixes = db_prefixes()
    hits = defaultdict(lambda: {"n": 0, "srcs": defaultdict(int), "sample": "", "kind": ""})
    for p in scan_files():
        rel = str(p.relative_to(ROOT))
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            historical = any(w in line for w in HISTORICAL)
            for m in INTERNAL_CODE.finditer(line):
                code = m.group(1)
                if code in edges:
                    continue
                rec = hits[code]
                rec["n"] += 1
                rec["srcs"][rel] += 1
                rec["kind"] = rec["kind"] or ("历史语境" if historical else "内部码")
                if not rec["sample"]:
                    rec["sample"] = f"{rel}:{i} {line.strip()[:88]}"
            for m in VENDOR_CODE.finditer(line):
                code = m.group(1)
                prefix = code.split("-")[0]
                if prefix not in prefixes or code in edges:
                    continue
                rec = hits[code]
                rec["n"] += 1
                rec["srcs"][rel] += 1
                rec["kind"] = rec["kind"] or ("历史语境" if historical else "厂商码")
                if not rec["sample"]:
                    rec["sample"] = f"{rel}:{i} {line.strip()[:88]}"
    return hits


def cmd_check() -> int:
    """契约（Q27 后）：`plugin/error_semantics.yaml` 的**有界完备性**。

    守四件：① 每个检查维度（除 `unknown`）至少一条规则 ② 规则内**不得出现码形态**
    ③ `fallback` 存在 ④ 规则 id 唯一、`match` 非空。
    退出码：0 通过 / 1 不满足（含"规则表未就位"）。
    """
    if not SEMANTICS.is_file():
        print(f"✗ 语义规则表未就位：{SEMANTICS}（随候选 C-20261011-04 落盘）", file=sys.stderr)
        return 1
    try:
        import yaml
        data = yaml.safe_load(SEMANTICS.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001
        print(f"✗ 语义规则表不可解析：{exc}", file=sys.stderr)
        return 1

    rules = data.get("rules") or []
    problems = []
    ids = [str(r.get("id", "")) for r in rules]
    if len(ids) != len(set(ids)):
        problems.append(f"规则 id 重复：{ids}")
    for r in rules:
        if not r.get("id"):
            problems.append(f"规则缺 id：{r}")
        if not r.get("match"):
            problems.append(f"规则 {r.get('id')} 的 match 为空")
        for kw in r.get("match") or []:
            if CODE_SHAPE.search(str(kw)) or BARE_NUM.search(str(kw)):
                problems.append(f"规则 {r.get('id')} 的 match 里出现**码形态**（Q27 红线）：{kw!r}")
    # 63 号：**第二个入口**同样受 Q27 约束——match_official 只吃官方含义文本，
    # 也必须无码形态、非空、无空项（否则"官方含义"这条路由会变成绕过红线的后门）。
    for r in rules:
        kws2 = r.get("match_official")
        if kws2 is None:
            continue
        rid2 = r.get("id")
        if not isinstance(kws2, list) or not kws2:
            problems.append("规则 %s 的 match_official 必须是非空列表" % rid2)
            continue
        for kw in kws2:
            if not str(kw).strip():
                problems.append("规则 %s 的 match_official 有空项" % rid2)
            if CODE_SHAPE.search(str(kw)) or BARE_NUM.search(str(kw)):
                problems.append("规则 %s 的 match_official 里出现**码形态**（Q27 红线，第二入口）：%r" % (rid2, kw))

    covered = {str(r.get("dimension", "")) for r in rules}
    missing = sorted(ontology_dimensions() - covered - {"dimension:unknown"})
    if missing:
        problems.append(f"这些维度没有任何规则覆盖：{missing}")
    if not (data.get("fallback") or {}).get("dimension"):
        problems.append("缺 fallback.dimension")

    # 63 号：官方码表侧车（plugin/error_codes.yaml）的 dimension_map 值域——
    # 值必须是 dimensions.bkn 的注册维度（或 unknown），否则"码 → 维度"会指到不存在的类。
    covered_note = ""
    if CODES.is_file():
        try:
            cdata = yaml.safe_load(CODES.read_text(encoding="utf-8")) or {}
        except Exception as exc:  # noqa: BLE001
            problems.append(f"官方码表侧车不可解析：{exc}")
            cdata = {}
        registered = ontology_dimensions() | {"dimension:unknown"}
        dm = cdata.get("dimension_map") or []
        bad = sorted({str(e.get("dimension")) for e in dm
                      if str(e.get("dimension") or "") not in registered})
        if bad:
            problems.append("dimension_map 出现未注册维度：%s" % bad)
        cov = cdata.get("coverage") or {}
        if cov:
            covered_note = ("；侧车 %s 条码表、已归类 %s（%s%%）"
                            % (cov.get("entries"), cov.get("classified"), cov.get("rate_pct")))

    if problems:
        print("✗ 语义规则未达契约：", file=sys.stderr)
        for x in problems:
            print(f"    {x}", file=sys.stderr)
        return 1
    print(f"✓ 语义规则契约满足：{len(rules)} 条规则覆盖 {len(covered)} 个维度"
          f"（全部维度已覆盖、无码形态、fallback 就位）{covered_note}")
    return 0


def cmd_scan(edges_only: bool = False, out: str | None = None) -> int:
    edges = read_edges()
    hits = scan(edges)
    teaching = [c for c in hits if c in TEACHING_CODES]
    exempt = [c for c in hits if c in EXEMPT]
    rest = sorted((c for c in hits if c not in TEACHING_CODES and c not in EXEMPT),
                  key=lambda c: -hits[c]["n"])
    lines = []
    lines.append("# 错误码覆盖扫描（`scripts/code_id_coverage.py --scan`，勿手改）")
    lines.append("")
    lines.append(f"- 本体已登记（边）：**{len(edges)} 码**")
    lines.append(f"- 扫描面：{len(scan_files())} 个文件；命中未登记 token **{len(hits)} 种**")
    lines.append(f"- 其中：教学契约内待落盘 **{len(teaching)}**｜显式豁免 **{len(exempt)}**｜**待分类 {len(rest)}**")
    lines.append("")
    lines.append("## 1. 教学契约内但尚未落盘（应随补边候选一起落地）")
    lines.append("")
    for c in sorted(teaching):
        r = hits[c]
        lines.append(f"- `{c}`｜拟 → `{TEACHING_CODES[c]['to']}`｜出现 {r['n']} 次｜{r['sample']}")
    lines.append("")
    lines.append("## 2. 显式豁免（每条有理由，见脚本 EXEMPT）")
    lines.append("")
    for c in sorted(exempt):
        lines.append(f"- `{c}`｜出现 {hits[c]['n']} 次｜理由：{EXEMPT[c]}")
    lines.append("")
    lines.append("## 3. 待分类（**需人核**：教学语态 → 补边；顺带提及/噪声 → 记理由排除）")
    lines.append("")
    for c in rest:
        r = hits[c]
        top = ", ".join(f"{s}({n})" for s, n in sorted(r["srcs"].items(), key=lambda kv: -kv[1])[:2])
        lines.append(f"- `{c}`｜{r['n']} 次｜{top}｜{r['kind']}")
        lines.append(f"    - {r['sample']}")
    text = "\n".join(lines) + "\n"
    if out:
        Path(out).write_text(text, encoding="utf-8")
        print(f"✅ 已写 {out}（已登记 {len(edges)}；待分类 {len(rest)}；教学待落盘 {len(teaching)}）")
    else:
        print(text)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="错误码 ID 空间覆盖（24 号批 C1）")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true", help="教学契约：教学码必须已登记（退出码 0/1）")
    g.add_argument("--scan", action="store_true", help="扫描并分类全仓码形态 token")
    ap.add_argument("--out", default=None, help="--scan 时写入文件（默认打印）")
    ns = ap.parse_args(argv)
    if ns.check:
        return cmd_check()
    return cmd_scan(out=ns.out)


if __name__ == "__main__":
    raise SystemExit(main())
