#!/usr/bin/env python3
"""lint_bkn.py — BKN 结构质量检查 (v1.5, P0-9)

枚举源: plugin/constants.py (VALID_*) 与 plugin/relations.py (RELATION_TYPES)，不重复定义。
严重级别: error > warning > info。默认全量输出；--error-only 只看 error；
--ignore < substr > 可忽略含指定子串的条目（可重复）。

用法:
  python3 plugin/scripts/lint_bkn.py [--error-only] [--ignore xxx] [--bkn-root PATH]
退出码: 0 = 无 error; 1 = 有 error
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = PLUGIN_ROOT.parent
sys.path.insert(0, str(PROJECT_ROOT))

from plugin.constants import (  # noqa: E402
    VALID_ATTRIBUTE_TYPES, VALID_RISK_TYPES, VALID_SEVERITY, SEVERITY_LEGACY_MAP,
    VALID_ACCESS_TYPES, VALID_BINDING_TYPES, VALID_SECTION_TYPES, PROCESS_IDS,
    KNOWN_DBS, DB_ALIASES, DB_ERROR_PREFIXES, is_db_match,
    RELATION_TARGET_NAMESPACES,
)
from plugin.relations import RelationTraverser  # noqa: E402

RELATION_TYPES = RelationTraverser.RELATION_TYPES

#: D3② 豁免表**已退役**（乙-1 ／ C-20261013-03）：机制集落盘后 `manifests_as` 已有 `symptom:`/`dimension:` 实例，
#: 零使用不再需要豁免。**不留空表**——空表 ＋ 下面那条 `continue` 就是「无内容的机器」（R-2 同类）：
#: 现在零使用**一律报 warning**；将来若真需要豁免，须重新论证并走候选落盘，而不是在这里加一行。

SKILL_ROOT = PROJECT_ROOT / "skill"

# 实例登记的命名空间 ID 模式（23 号：本体层表格只允许实例登记，行首带命名空间 ID）
NAMESPACE_ID_PATTERN = re.compile(r"^`?[a-z][a-z0-9_]*:[^`|\t\n\r ]+`?$")

# 已退场的段类型（22 号批 2-3 漂移机检用）：index/matrix（23 号废止）、
# symptom/class（24 号退役）、scenario（26 号归档为 entity；`scenario:` 命名空间仍保留）
RETIRED_SECTION_TYPES = ("scenario", "symptom", "class", "index", "matrix")

# ── 命名空间**清单一致性**机检用（D-批，2026-10-14）─────────────────────────
# 从**反引号 token** 里取 `ns:` 前缀。只看 token、不看自由散文——否则散文里的
# `plugin/constants.py::KNOWN_DBS` 会被误读成 `py:`、`rdfs:subClassOf` 会被误读成 `rdfs:`。
NS_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_:.])([a-z][a-z_]{1,23}):(?=[A-Za-z0-9_*\u4e00-\u9fff])")
#: 不是命名空间的 `x:` 词（豁免表；每条须能说明为什么它不是 ID 空间）
NS_NOT_A_NAMESPACE = frozenset({"rdfs"})   # `rdfs:subClassOf` 是对 W3C 词汇的**引用**，不是本体命名空间
_NS_PATHLIKE_RE = re.compile(r"[/\\]|\.(py|md|bkn|yaml|yml|json|sh|txt)$")
#: 权威载荷类数（bkn/SCHEMA.md §0.2：KV 属性列表 / 实例登记表 / 定义性散文）
AUTHORITATIVE_PAYLOAD_KINDS = 3

#: **已退场的 .bkn 文件名注册表**（C3，2026-10-11）：文件名 -> 它退场后由什么承接。
#: 用途：`_check_dead_refs` 用"注册表 + 语境豁免"抓**现行时态的死指路**——
#: 26 号把 diagnostics/ 与 network.bkn 一类文件退场后，**已接线**的生成指引里仍留着
#: "新错误码 → `bkn/objects/diagnostics.bkn` 加行"这种指路（Agent 照做会写进不存在的文件）。
#: 为什么带注册表而不裸查"所有不存在的 .bkn 引用"：实测裸查假阳性极高
#: （示例占位名 `Object1.bkn`、反例举例、正确的退场陈述都会命中）——注册表把范围钉在**确实退场过**的那些。
RETIRED_BKN_FILES = {
    "network.bkn": "23 号废止（路由索引/实体语义索引/文件导航/同义词中央表）",
    "risks.bkn": "旧 risks 结构（现 risks/constraints.bkn 等分文件）",
    "all.bkn": "旧 risks 结构（risks/all.bkn）",
    "env_matrix.bkn": "旧路由架构（对象 × 环境矩阵）",
    "symptom-router.bkn": "19/20 号收拢（症状/错误码 → process_topology 的 suspected_in/has_class 边）",
    "classes.bkn": "诊断类退场（class:* → dimension:*，见 objects/dimensions.bkn）",
    "class-db-matrix.bkn": "下延 Skill（skill:demo_product-db-diagnostics/references/db-checkpoints.md）",
    "diagnostics.bkn": "26 号溶解（对象 → objects/dimensions.bkn）；Q27 起**错误码不进本体也不穷举**（码只作入口：含义 → plugin/error_semantics.yaml 与三源检索）",
    "error-codes.bkn": "同上（错误码 → 含义入口 plugin/error_semantics.yaml；症状/维度归类的边在 process_topology.bkn）",
    "routing.bkn": "同上（归类边 → process_topology.bkn）",
    "store-registry.bkn": "26 号退场（检索源身份 → plugin/skill_manifest.yaml 的 stores）",
    "log-map.bkn": "26 号退场（日志导航 → diagnose_db_link 的 log_navigation 字段）",
    "related-skills.bkn": "26 号退场（Skill 路由 → skill_manifest.yaml）",
}
#: `_check_dead_refs` 的语境豁免词：命中这些词的**同一行**视为历史/退场陈述，不报。
#: （与 `_check_skill_file_refs` 的 `_HISTORICAL` 同思路，另加"归档横幅"用的词。）
DEAD_REF_HISTORICAL = ("已删", "删除", "已废止", "废止", "已退场", "退场", "已归档",
                       "归档", "迁出", "迁入", "迁移", "并入", "下沉", "下延", "取代",
                       "历史", "旧架构", "已无", "不再有", "溶解", "~~")
#: 归档横幅（文件级豁免）：文件头部若干行内出现即整文件跳过——2-1 收敛里 12 个文件带此类横幅
ARCHIVE_BANNER = "历史文档（已归档）"
#: 路径级豁免（每条必须写理由）：文件整体属"历史事实记录/测试用例"，不是现行指路。
DEAD_REF_EXEMPT_PATHS = {
    "skill/bkn-test/doc/05-freshness.md":
        "「陈旧性测试」的用例与发现记录——它**故意**引用陈旧路径来测漂移，命中即其结论",
    "skill/bkn-plugin/references/bge-precision-failure-4002.md":
        "案例记录：描述当时那次查询的结果（`risks.bkn` 无此条目），属历史事实而非现行指路",
    "skill/demo_product-log-analyzer/references/error-code-4002.md":
        "同上（案例的来源注记：当时 `risks.bkn` 未收录，经 Qdrant 兜底发现）",
}
#: 显式空白/数字类——项目约定：plugin/** 禁用正则简写类 \s \d \w \b
#: （见 plugin/tests/test_bkn_boundary.py::test_all_plugin_files_avoid_regex_shorthand_classes）
_BLANK = r"[ \t\u3000]"
_DIGIT = r"[0-9]"

# ── BKN 零冗余规则（用户裁定 2026-10-10）────────────────────────────────
# `.bkn` 只承载本体内容与必要指引，不得出现元信息：批次/方案号、日期、修改/变更记录、
# 来源或创建注记、迁移/归档/删除说明、工作文档指针。迭代记录 → 90-history/bkn-changelog.md。
# 允许（不属冗余）：定义/属性/关系映射/实例登记、值委托指针（skill:/store:）、
# ⚠️ 待核证据状态、机制说明（lint/白名单/注册集）、数字语义（如「15 错误码」「9.0+」）。
META_INFO_PATTERNS = (
    (r"[0-9]{1,2}" + _BLANK + r"*号方案", "批次方案号"),
    (r"[0-9]{1,2}" + _BLANK + r"*号（", "批次号括注"),
    (r"（" + _BLANK + r"*[0-9]{1,2}" + _BLANK + r"*号", "批次号括注"),
    (r"[0-9]{1,2}" + _BLANK + r"*号后", "批次号后"),
    (r"[0-9]{1,2}" + _BLANK + r"*号起", "批次号起"),
    (r"[0-9]{1,2}" + _BLANK + r"*号", "批次/文档号"),
    (r"批" + _BLANK + r"*[0-9]+[-–—][0-9]+", "批号"),
    (r"20[0-9]{2}-[0-9]{2}-[0-9]{2}", "日期"),
    # 注意：不含「迭代记录」——「迭代记录 → changelog」是**规则本体**（指向记录去哪儿），不是记录
    (r"修改记录|变更记录|修订记录|更新记录", "记录块"),
    (r"迁入|迁移为|移出", "迁移说明"),
    (r"文件已删|原文已删|已归档|归档为", "归档删除说明"),
    (r"^>?" + _BLANK + r"*来源[:：]|创建于|生成于|整理自", "来源创建注记"),
    # 排除 changelog 自身路径：规则**要求**指向记录去处，那不算冗余
    (r"doc/optimize/|doc/build/(?!demo_product-bkn/90-history/)|drafts/", "工作文档指针"),
)

#: 元信息豁免清单（过渡用）：`"<相对路径>|类别|行首 36 字"` -> 理由。
#: **由 `lint_bkn.py --list-meta-info` 生成**；清理一处删一条，清空即检查转严。
#: 键含行内容片段——**该行一旦被编辑，豁免自动失效并重新报错**（刻意如此：防陈旧豁免）。
KNOWN_META_INFO: dict = {
    # ✅ **清理已完成（2026-10-10，候选 C-20261010-02）**——本表由 82 条待清理清至 0 条。
    #   仅保留「规则本体」条目：零冗余规则表（bkn/SCHEMA.md §0.5）**必须点名被禁类别**，故不清。
    #   新增条目 = 新增技术债：只有「规则文本本身必须含被禁词」才可加入，且须说明理由。
    #   ⚠ 检查现已转严：任何新写入的元信息都会直接报 error（这是本规则的目的）。
    'SCHEMA.md|记录块|| 修改/变更/修订/更新记录 | 任何形式的记录块；文件的变更历史不属': '规则本体：零冗余规则表须点名被禁类别（不清）',
}


class Linter:
    def __init__(self, bkn_root: Path):
        self.root = bkn_root
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.infos: list[str] = []
        self._traverser = None  # 惰性构建（症状归类校验用）

    # ---------- 汇总入口 ----------

    def run(self):
        for f in sorted(self.root.rglob("*.bkn")):
            rel = str(f.relative_to(self.root))
            if rel.startswith("templates/"):
                continue  # 模板含占位符，非正式内容，跳过检查
            content = f.read_text(encoding="utf-8", errors="ignore")
            self._check_skills_referenced(f, rel, content)
            self._check_section_types(f, rel, content)
            self._check_ref_resolution(f, rel, content)
            self._check_no_explanatory_tables(f, rel, content)
            self._check_bkn_file_refs(f, rel, content)
            self._check_skill_file_refs(f, rel, content)
            self._check_form_semantics(f, rel, content)
            self._check_relation_sections_outside_dir(f, rel, content)
            self._check_no_error_nodes(f, rel, content)
            self._check_no_bare_error_codes(f, rel, content)
            self._check_no_code_symbols(f, rel, content)
            if rel.startswith("actions/"):
                self._check_action_file(f, rel, content)
            elif rel.startswith("relations/"):
                self._check_relation_file(f, rel, content)
                self._check_relation_target_namespace(f, rel, content)
            elif rel.startswith("risks/"):
                self._check_risk_file(f, rel, content)
        self._check_prerequisites_coverage()
        self._check_constraint_edge_alignment()
        self._check_constraint_state_refs()
        self._check_relation_declaration_completeness()
        self._check_action_constraint_refs()
        self._check_namespace_registry_consistency()
        self._check_domain_map_consistency()
        self._check_edge_semantics_consumers()
        self._check_relation_type_count_consistency()
        self._check_namespace_inventory_consistency()
        self._check_process_registry()
        self._check_symptom_edges()
        self._check_symptom_registry()
        self._check_alias_constants()
        self._check_alias_table()
        self._report_todo_markers()
        self._check_db_coverage()
        self._check_manifest_orphans()
        self._check_skill_manifest_bkn_contract()
        self._check_retired_terms()
        self._check_no_meta_info()
        self._check_provenance_coverage()
        self._check_dead_refs()

    # ---------- 死指路机检（C3，2026-10-11）----------

    def _dead_ref_targets(self) -> list:
        """扫面：`skill/**`、`bkn/**`（含 .md 与 .bkn）、`doc/update/**` 的 md。

        排除：`archive/`、`_archived/` 目录（已归档，历史路径合法）、`90-history/`（迭代记录，
        按 26 号它**就该**写历史文件名）、以及带归档横幅的文件（2-1 收敛的 12 个文件级状态标识）。
        """
        targets = []
        for pat in ("skill/**/*.md", "bkn/**/*.md", "bkn/**/*.bkn", "doc/update/**/*.md"):
            targets.extend(self.root.parent.glob(pat))
        out = []
        for f in sorted(set(targets)):
            parts = f.parts
            if any(p in ("archive", "_archived") for p in parts):
                continue
            rel = str(f.relative_to(self.root.parent))
            if rel.startswith("bkn/90-history/"):
                continue
            try:
                head = "\n".join(f.read_text(encoding="utf-8", errors="ignore").splitlines()[:6])
            except OSError:
                continue
            if ARCHIVE_BANNER in head:
                continue
            out.append(f)
        return out

    def scan_dead_refs(self) -> list:
        """返回未豁免的命中列表（供 run() 报 info 与 `--list-dead-refs` 导出）。

        命中条件：**提到 `RETIRED_BKN_FILES` 里的文件名**（可带路径前缀，如
        `objects/diagnostics.bkn` / `diagnostics/error-codes.bkn`），且该行不是历史/退场语境。
        """
        names = "|".join(re.escape(n) for n in RETIRED_BKN_FILES)
        # 词边界很关键：缺少 `(?<![A-Za-z0-9_])` 时 `routing.bkn` 会命中**在用的**
        # `action_routing.bkn`（前缀贪婪吃掉 `action_`）——实测 100 处里大半是这种假阳性。
        rx = re.compile(r"(?<![A-Za-z0-9_])(?:[A-Za-z0-9_./-]*/)?(" + names + r")(?![A-Za-z0-9_])")
        hits = []
        for f in self._dead_ref_targets():
            rel = str(f.relative_to(self.root.parent))
            if rel in DEAD_REF_EXEMPT_PATHS:
                continue
            content = f.read_text(encoding="utf-8", errors="ignore")
            for lineno, line in enumerate(content.split("\n"), 1):
                if not line.strip() or any(w in line for w in DEAD_REF_HISTORICAL):
                    continue
                for m in rx.finditer(line):
                    hits.append({
                        "rel": rel, "line": lineno, "name": m.group(1),
                        "why": RETIRED_BKN_FILES[m.group(1)],
                        "text": line.strip()[:96],
                    })
        return hits

    def _check_dead_refs(self):
        """现行时态的"死指路"机检（**info 级**，不阻断门禁）。

        与 `_check_retired_terms` 的分工：那条明写"不查已删文件名的提及"（怕误报）；
        本条用**注册表 + 语境豁免**把范围钉住后再查——因为"已接线的生成指引教人去写一个
        不存在的文件"是真实缺陷（C-20261011-02 修的就是这一类，6 处）。
        """
        for h in self.scan_dead_refs():
            self.infos.append(
                f"{h['rel']}:{h['line']}: 提到已退场文件 `{h['name']}`（{h['why']}）"
                f"，且非历史语境——若为现行指路请改指现行落点")

    # ---------- 来源侧车覆盖（24 号 D4 / 22 号批 2-4；不变量 I5）----------

    def _check_provenance_coverage(self):
        """`bkn/risks/constraints.bkn` 的每个 constraint ID 必须在 `plugin/provenance.yaml` 有条目。

        **为什么机检**：02 号 §7 判定——诊断方向写错只是"思路偏了"可恢复，**约束写错则护栏直接
        失效或误伤**。这一档的断言因此最需可追溯；而 26 号零元信息禁止把来源写进 `.bkn`，
        故来源落在 Tool 层侧车，由本检查强制两边不脱节（22 号 §5 I5：侧车缺失即 error，不允许 warning 级）。

        作用域：约束 + 状态机公理。约束 ID 从 `constraints.bkn` 的「约束ID」列（第 2 列）抽取——
        注意**约束 ID 可含大写状态名**（`cannot_delete_RUNNING`），字符类须含 A-Z。
        """
        constraints = self.root / "risks" / "constraints.bkn"
        if not constraints.is_file():
            return  # fixture 树可能没有该文件
        ids = set()
        for line in constraints.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not line.startswith("|") or line.count("|") < 4:
                continue
            cols = [c.strip() for c in line.strip("|").split("|")]
            if len(cols) < 2 or not cols[1] or set(cols[1]) <= set("-: "):
                continue
            cid = cols[1].strip("`")
            if re.fullmatch(r"[a-z][A-Za-z0-9_]*", cid) and cid != "约束ID":
                ids.add(cid)
        if not ids:
            return

        sidecar = PROJECT_ROOT / "plugin" / "provenance.yaml"
        if not sidecar.is_file():
            self.errors.append(
                f"来源侧车缺失: {sidecar}——约束类断言必须可追溯（22 号 I5）")
            return
        try:
            import yaml  # 延迟导入：与本文件其它检查保持最小依赖
            data = yaml.safe_load(sidecar.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            self.errors.append(f"来源侧车不可解析: {sidecar}（{exc}）")
            return

        covered = set()
        for entry in data.get("entries") or []:
            target = str((entry or {}).get("target", ""))
            if target.startswith("constraint:"):
                covered.add(target.split(":", 1)[1])

        for cid in sorted(ids - covered):
            self.errors.append(
                f"constraint:{cid} 在 plugin/provenance.yaml 无来源条目（I5）"
                f"——本体的约束断言必须可追溯")

    # ---------- BKN 零冗余（用户裁定 2026-10-10）----------

    def _meta_info_targets(self):
        """三档范围：内容文件（从严）/ 规范件（去装饰）/ 模板（去装饰）。"""
        targets = []
        for f in sorted(self.root.rglob("*.bkn")):
            targets.append(f)
        for f in sorted(self.root.glob("*.md")):
            targets.append(f)                      # SCHEMA.md / SKILL.md / SYNONYMS.md
        rel_dir = self.root / "relations"
        if rel_dir.is_dir():
            for f in sorted(rel_dir.glob("*.md")):
                targets.append(f)                  # RELATION_TYPES.md
        tpl_dir = self.root / "templates"
        if tpl_dir.is_dir():
            for f in sorted(tpl_dir.glob("*.bkn")):
                targets.append(f)
        return targets

    def scan_meta_info(self):
        """返回命中列表（供 run() 报错与 --list-meta-info 导出）。

        **按键去重**：同一文件里内容相同的两行会产生同一个键（`rel|类别|行首36字`）；
        不去重则同一处会报两次、导出清单出现重复条目、豁免表随之冗余
        （实测 83 条字面条目 / 80 个唯一键）。去重后只保留**首次出现**的行号——
        错误信息已含行内容，足以定位全部同内容行。
        """
        compiled = [(re.compile(p), label) for p, label in META_INFO_PATTERNS]
        found = []
        seen: set = set()
        for f in self._meta_info_targets():
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            try:
                rel = str(f.relative_to(self.root))
            except ValueError:
                rel = str(f)
            for lineno, line in enumerate(content.splitlines(), 1):
                stripped = line.strip()
                for rx, label in compiled:
                    if rx.search(line):
                        key = f"{rel}|{label}|{stripped[:36]}"
                        if key in seen:
                            break            # 同键已在更早的行报过
                        seen.add(key)
                        found.append({"rel": rel, "line": lineno, "label": label,
                                      "text": stripped[:96], "key": key})
                        break
        return found

    def _check_no_meta_info(self):
        """零冗余机检：批次/日期/记录块/迁移说明/工作文档指针一律不得出现。

        过渡期对照 `KNOWN_META_INFO` 豁免清单（由 `--list-meta-info` 生成）；
        豁免键含行内容片段——行被编辑即失效并重新报错，防陈旧豁免。
        """
        for hit in self.scan_meta_info():
            if hit["key"] in KNOWN_META_INFO:
                continue
            self.errors.append(
                f"{hit['rel']}:{hit['line']}: 含元信息（{hit['label']}）：{hit['text']}"
                f"—— `.bkn` 不得含演进注记；迭代记录写 "
                f"CHANGELOG.md")

    # ---------- 已退场术语漂移机检（22 号批 2-3） ----------

    def _check_retired_terms(self):
        """活跃面上的"文档说 A、代码说 B"机检。

        范围：`bkn/**/*.md`（排除 `90-history/`——历史留档允许原措辞）、`bkn/templates/*.bkn`
        （主 walk 跳过模板，但它正是漂移高发区）、`doc/update/**/*.md`。

        只查两件**形式明确**的事：
        ① 已退场段类型被当作**标注**使用（`<!-- type: scenario -->` 这类）；
        ② 与权威枚举数不符的**计数表述**（"段类型白名单 7 种" / "只允许两类载荷"）。

        **不查已删文件名的提及**——"23 号已无 network.bkn 索引"这类历史注记是合法的，
        误报比漏报更糟（22 号 §3 批 2-3 的判据是"出现已退场**枚举值**"，不是"出现旧文件名"）。
        """
        targets: list[Path] = []
        for f in sorted(self.root.rglob("*.md")):
            rel = str(f.relative_to(self.root))
            if rel.startswith("90-history/"):
                continue
            targets.append(f)
        templates = self.root / "templates"
        if templates.is_dir():
            targets += sorted(templates.glob("*.bkn"))
        # doc/update 随 bkn 根定位（真实仓库 = <repo>/doc/update；fixture 树里通常不存在 → 跳过），
        # 不用模块级 PROJECT_ROOT——否则单测会连带扫描真实仓库，产生意外耦合
        update_dir = self.root.parent / "doc" / "update"
        if update_dir.is_dir():
            targets += sorted(update_dir.rglob("*.md"))

        for f in targets:
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            try:
                rel = str(f.relative_to(PROJECT_ROOT))
            except ValueError:
                rel = str(f)

            for m in re.finditer(r"<!--" + _BLANK + r"*type:" + _BLANK + r"*([A-Za-z_]+)" + _BLANK + r"*-->",
                                 content):
                if m.group(1) in RETIRED_SECTION_TYPES:
                    self.errors.append(
                        f"{rel}: 段类型标注用了已退场类型 `{m.group(1)}`"
                        f"（白名单 {len(VALID_SECTION_TYPES)} 种，见 bkn/SCHEMA.md §0.1）")

            for m in re.finditer(r"段类型白名单" + _BLANK + r"*\*{0,2}" + _BLANK + r"*(" + _DIGIT
                                 + r"+,?)" + _BLANK + r"*\*{0,2}" + _BLANK + r"*种", content):
                if int(m.group(1)) != len(VALID_SECTION_TYPES):
                    self.errors.append(
                        f"{rel}: 段类型白名单写作 {m.group(1)} 种，权威为"
                        f" {len(VALID_SECTION_TYPES)} 种（bkn/SCHEMA.md §0.1）")

            zh = {"一": 1, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6}
            for m in re.finditer(r"只允许" + _BLANK + r"*([一二两三四五六])" + _BLANK + r"*类载荷", content):
                if zh.get(m.group(1)) != AUTHORITATIVE_PAYLOAD_KINDS:
                    self.errors.append(
                        f"{rel}: 载荷写作「{m.group(1)}类」，权威为三类"
                        "（KV 属性列表 / 实例登记表 / 定义性散文；bkn/SCHEMA.md §0.2）")

    # ---------- 数据库覆盖完整性（23 号后仅常量自洽） ----------

    def _parse_section_table(self, rel_path: str, section_name: str) -> list[dict]:
        """提取 .bkn 文件指定 section 下第一个 markdown 表格为 row dict 列表"""
        f = self.root / rel_path
        if not f.exists():
            return []
        lines = f.read_text(encoding="utf-8", errors="ignore").splitlines()
        in_section = False
        table_lines: list[str] = []
        for line in lines:
            if line.startswith("## "):
                if in_section:
                    break
                in_section = line.strip() == f"## {section_name}"
                continue
            if in_section and line.strip().startswith("|"):
                table_lines.append(line.strip())
        if len(table_lines) < 3:
            return []

        def cells(l: str) -> list[str]:
            return [c.strip() for c in l.strip("|").split("|")]

        header = cells(table_lines[0])
        rows = []
        for l in table_lines[2:]:  # 跳过表头与分隔行
            body = l.replace("|", "").replace("-", "").strip()
            if not body:
                continue
            rows.append(dict(zip(header, cells(l))))
        return rows

    def _check_db_coverage(self):
        """DB 别名 / 错误码前缀 ↔ KNOWN_DBS 对账（23 号后兼容性数据已下延 Skill，
        仅保留常量层面的自洽校验：别名与前缀不得指向未知库）。

        error: 数据一致性错误（别名/前缀指向未知库）
        """
        # 1. 别名指向未知库 → error
        for alias, canonical in DB_ALIASES.items():
            if not any(is_db_match(canonical, k) for k in KNOWN_DBS):
                self.errors.append(
                    f"db-coverage: 别名 '{alias}' 指向未知库 '{canonical}'")

        # 2. 错误码前缀指向未知库 → error
        for prefix, db in DB_ERROR_PREFIXES.items():
            if not any(is_db_match(db, k) for k in KNOWN_DBS):
                self.errors.append(
                    f"db-coverage: 错误码前缀 '{prefix}' 指向未知库 '{db}'")

    def _check_alias_table(self):
        """aliases.yaml 自洽（别名机制 v2；43 号 §7 D11）。

        error: ① canonical 未登记（悬空/幽灵别名）② 别名键是可生成变体（应由 L1 生成）
               ③ 缺 provenance
        """
        path = Path(__file__).resolve().parent.parent / "aliases.yaml"
        if not path.is_file():
            return
        try:
            import yaml
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception as exc:  # noqa: BLE001 —— 坏 YAML 必须报出来
            self.errors.append(f"aliases.yaml: 解析失败（{exc}）")
            return
        canon = set()
        try:
            from plugin.constants import SYMPTOM_ALIASES, DIMENSION_ALIASES, PROCESS_IDS
            canon.update(str(v) for v in SYMPTOM_ALIASES.values() if v)
            canon.update(str(v) for v in DIMENSION_ALIASES.values() if v)
            canon.update(str(v) for v in PROCESS_IDS if v)
        except Exception:  # noqa: BLE001 —— 取不到常量就跳过（不误报）
            pass
        try:
            from plugin.resolver import _load_error_codes
            codes = _load_error_codes() or {}
            canon.update(str(k) for k in codes)
            canon.update(str(k).lstrip("-") for k in codes)
        except Exception:  # noqa: BLE001
            pass
        for msg in _validate_alias_entries(data.get("entries") or [], canon):
            self.errors.append(msg)

    # ---------- 检查项 ----------

    # ---------- 检查项 ----------

    def _report_todo_markers(self):
        """P2-3: 统计「待补充」标记（info 级，缺口显性化）"""
        count = 0
        files = []
        for f in sorted(self.root.rglob("*.bkn")):
            content = f.read_text(encoding="utf-8", errors="ignore")
            n = content.count("待补充")
            if n:
                count += n
                files.append(f"{f.relative_to(self.root)}({n})")
        if count:
            self.infos.append(
                f"当前共 {count} 处「待补充」标记: {', '.join(files)}")

    # ---------- 检查项 ----------

    def _check_constraint_edge_alignment(self):
        """P1-2: constraints.bkn 约束ID ↔ action_routing.bkn constrained_by 边双向覆盖。

        只取 constrained_by 段的边（risks_of/implements_skill 段的目标不是约束）。
        25 号（同构精简）：「关联」列已删——**约束登记表只含边绑定的动作级约束**，
        ID 空间与动作绑定以边为权威；表内 ID 没有边 → warning
        （新增约束忘补边 = risk_guard 静默不拦截，必须响亮提示）。
        全局/对象级约束（无动作可绑）在「全局约束」KV 段，不在此表 → 天然豁免。
        """
        constraints_file = self.root / "risks" / "constraints.bkn"
        routing_file = self.root / "relations" / "action_routing.bkn"
        if not constraints_file.exists() or not routing_file.exists():
            return

        c_text = constraints_file.read_text(encoding="utf-8", errors="ignore")
        # 约束ID 列：表格第二列（| Risk | 约束ID | 类型 | 约束 |）
        # 注意: 约束ID 可含大写状态名（如 cannot_delete_RUNNING），字符类须含 A-Z
        constraint_ids = set()       # 全部表内约束（校验 边→约束 / 约束→边 双向）
        for line in c_text.split("\n"):
            if not line.startswith("|") or "约束ID" in line or "---" in line:
                continue
            cells = [c.strip() for c in line.split("|") if c.strip()]
            if len(cells) >= 2 and re.match(r"^[a-z][a-zA-Z0-9_]*$", cells[1]):
                constraint_ids.add(cells[1])

        ar_text = routing_file.read_text(encoding="utf-8", errors="ignore")
        # 只解析 constrained_by 段的映射规则
        edges = set()
        for section in re.split(r"^## ", ar_text, flags=re.MULTILINE):
            if "**关系类型**: constrained_by" not in section:
                continue
            for m in re.finditer(r"→ `([a-z][a-zA-Z0-9_]+)`", section):
                edges.add(m.group(1))

        for edge in sorted(edges - constraint_ids):
            self.warnings.append(
                f"constrained_by 边 '{edge}' 在 constraints.bkn 中无对应约束ID")
        for cid in sorted(constraint_ids - edges):
            self.warnings.append(
                f"约束ID '{cid}' 未被 constrained_by 边引用"
                "（25 号：登记表 = 边绑定的 ID 属性登记；补边后 risk_guard 才装配；"
                "全局/对象级约束请放「全局约束」KV 段而非登记表）")

    # ---------- 检查项 ----------

    def _check_constraint_state_refs(self):
        """D1（38 号批 1）：约束 ID 引用的状态必须存在于**对象状态机**。

        病灶：`cannot_delete_RUNNING` 一类 ID 把状态写进了约束名，但状态机取值改动后
        无人发现**悬空引用**（risk_guard 推导会静默漏拦截）。
        口径（单点复用 `plugin/risk_guard`，正则与状态集不重复定义）：
          `constraint_id → 状态名（STATE_REF_REGEXES，先具体后泛化）→ 归属对象（STATE_OWNER）`
          `→ 有效集 = state_index_for(本根)`（BKN 解析优先，对象缺失用硬编码回退补）。
        分级：状态不在有效集 → **error**；状态无归属登记 → info（新增状态族须登记）。
        精度：尾缀兜底模式（`_…_<STATE>`）**只认登记表内的状态名**——`must_confirm_target_SCN`
        一类缩略语不是状态引用；显式模式（`cannot_*` / `*_must_be_*`）仍照抽照查（含未知 → info）。
        """
        from plugin.risk_guard import STATE_REF_REGEXES, STATE_OWNER, state_index_for

        risks_dir = self.root / "risks"
        if not risks_dir.is_dir():
            return
        index = state_index_for(self.root)

        # 抽 ID：登记表第二列 + 全局 KV 段的 `constraint:xxx` / `rule:xxx`（口径同既有对齐检查）
        ids: dict[str, str] = {}  # id → 出处文件名
        for f in sorted(risks_dir.glob("*.bkn")):
            text = f.read_text(encoding="utf-8", errors="ignore")
            for line in text.split("\n"):
                if line.startswith("|") and "约束ID" not in line and "---" not in line:
                    cells = [c.strip() for c in line.split("|") if c.strip()]
                    if len(cells) >= 2 and re.match(r"^[a-z][a-zA-Z0-9_]*$", cells[1]):
                        ids.setdefault(cells[1], f.name)
            for m in re.finditer(r"`(?:constraint|rule):([a-z][a-zA-Z0-9_]*)`", text):
                ids.setdefault(m.group(1), f.name)

        for cid in sorted(ids):
            state = ""
            for idx, pattern in enumerate(STATE_REF_REGEXES):
                m = pattern.search(cid)
                if not m:
                    continue
                token = m.group(1)
                # 尾缀兜底：只认登记表内的状态名（避免 SCN 一类缩略语误报）
                if idx == len(STATE_REF_REGEXES) - 1 and token not in STATE_OWNER:
                    break
                state = token
                break
            if not state:
                continue
            owner = STATE_OWNER.get(state, "")
            if not owner:
                self.infos.append(
                    f"约束ID '{cid}'（{ids[cid]}）引用状态 '{state}'，但该状态无归属登记"
                    "（新增状态族时须在 risk_guard.STATE_OWNER / _FALLBACK_OBJECT_STATES 登记）")
                continue
            if state not in index.get(owner, set()):
                self.errors.append(
                    f"约束ID '{cid}'（{ids[cid]}）引用状态 '{state}'，但 '{owner}' 状态机无此取值"
                    f"（现有：{sorted(index.get(owner, set()))}）——悬空引用，risk_guard 推导会静默漏拦截")

    def _check_relation_declaration_completeness(self):
        """D3（38 号批 1）：关系类型声明完备 + 命名空间白名单值零使用。

        ① `RELATION_TYPES` 每种类型必须在 `bkn/relations/*.bkn` **有声明段且源/目标齐**
           （代码白名单有、本体无声明 → 只能读代码才知道它能连什么）→ 否则 error。
        ② `RELATION_TARGET_NAMESPACES` 的白名单值若在映射规则里**零使用** → warning
           （Q27 去码后的残留清理；首个实例＝`risks_of` 的 `error:`）。
        仅对**真实 BKN 根**运行（含 SKILL.md 与 objects/）——fixture 不该被要求声明全部 24 种类型
        （先例：`_check_symptom_edges` / `_check_symptom_registry`）。
        """
        if not self._real_bkn_root():
            return
        rel_dir = self.root / "relations"
        if not rel_dir.is_dir():
            return
        declared: dict[str, list] = {}   # rel → [(domain_range_ok, 文件名)]
        targets_by_rel: dict[str, list] = {}
        for f in sorted(rel_dir.glob("*.bkn")):
            text = f.read_text(encoding="utf-8", errors="ignore")
            for section in re.split(r"^## ", text, flags=re.MULTILINE):
                m = re.search(r"\*\*关系类型\*\*:[ \t]*([a-z_]+)", section)
                if not m:
                    continue
                rel = m.group(1)
                ok = "**目标对象**:" in section and (
                    "**源对象**:" in section or "**映射规则**:" in section)
                declared.setdefault(rel, []).append((ok, f.name))
                targets_by_rel.setdefault(rel, []).extend(
                    t for t in re.findall(r"→ `([^`]+)`", section))

        for rel in RELATION_TYPES:
            blocks = declared.get(rel)
            if not blocks:
                self.errors.append(
                    f"关系类型 '{rel}' 在 bkn/relations/ 无声明段"
                    "（代码白名单有、本体无声明——domain/range 无从可查）")
            elif not any(ok for ok, _ in blocks):
                names = "、".join(sorted({n for _, n in blocks}))
                self.errors.append(
                    f"关系类型 '{rel}' 的声明段缺 源对象/目标对象（{names}）——domain/range 不完整")

        for rel, namespaces in sorted(RELATION_TARGET_NAMESPACES.items()):
            targets = targets_by_rel.get(rel, [])
            for ns in namespaces:
                if not any(str(t).startswith(ns) for t in targets):
                    self.warnings.append(
                        f"命名空间白名单值 '{ns}'（{rel}）在映射规则里零使用"
                        "——残留清理项（白名单与本体实际目标脱节）")

    def _check_domain_map_consistency(self):
        """C-20261012-14（42 号 §3.2）：`edge_semantics.yaml` 的 `domains` 映射表 ↔ `RELATION_TYPES` 恰好一致。

        为什么：域映射是「按域声明继承」的基础（42 号 Q2）——它把「哪些边可继承」从逐边列举
        变成域名声明。映射表一旦与白名单漂移（少列/多列/幽灵键），继承范围会**静默错位**。
        口径：键集须**恰好等于** RELATION_TYPES（既防漏、也防幽灵键）；每个类型**恰属一个域**。
        """
        try:
            from plugin.relations import RelationTraverser
            sem = RelationTraverser.edge_semantics()
        except Exception:
            return
        domains = sem.get("domains")
        if not domains:
            return  # 尚未声明域映射：不阻塞（本检查随 C-20261012-14 引入）
        seen: dict = {}
        for dom, members in domains.items():
            for m in members or []:
                if m in seen:
                    self.errors.append(
                        f"edge_semantics.domains：'{m}' 同时属于域 {seen[m]} 与 {dom}（每个类型须恰属一个域）")
                seen[m] = dom
        for rt in RELATION_TYPES:
            if rt not in seen:
                self.errors.append(
                    f"edge_semantics.domains：关系类型 '{rt}' 未归属任何域"
                    "（域映射表须与 RELATION_TYPES 恰好一致——防继承范围静默错位）")
        for rt in seen:
            if rt not in RELATION_TYPES:
                self.errors.append(
                    f"edge_semantics.domains：'{rt}' 不在 RELATION_TYPES 中（幽灵键）")
        for key in ("inherited_domains", "inherited_incoming_domains"):
            for dom in sem.get(key) or []:
                if dom not in domains:
                    self.errors.append(
                        f"edge_semantics.{key} 引用了不存在的域 {dom}"
                        "（域名须是 domains 的键——否则继承白名单静默失效）")

    def _check_relation_type_count_consistency(self):
        """C-20261012-16：关系类型的**计数**三处必须一致。

        为什么：关系类型口径散在三处（代码白名单 / RELATION_TYPES.md / SCHEMA.md §2），
        无机检时改一处忘一处 → 漂移（C-20261012-15 就是这么补的）。
        口径：len(RELATION_TYPES) == RELATION_TYPES.md 的「## N 种...」 == SCHEMA.md 的「（共 N 种」 == SCHEMA.md §2 各域小节计数之和。
        仅对**真实 BKN 根**运行。"""
        if not self._real_bkn_root():
            return
        import re as _re
        n = len(RELATION_TYPES)
        rtf = self.root / "relations" / "RELATION_TYPES.md"
        if rtf.is_file():
            m = _re.search(r"^##[ \t]*([0-9]+)[ \t]*种", rtf.read_text(encoding="utf-8", errors="ignore"), _re.M)
            if m and int(m.group(1)) != n:
                self.errors.append(f"RELATION_TYPES.md 计数 {m.group(1)} ≠ RELATION_TYPES 的 {n}（口径漂移）")
        scf = self.root / "SCHEMA.md"
        if scf.is_file():
            txt = scf.read_text(encoding="utf-8", errors="ignore")
            m = _re.search(r"（共[ \t]*([0-9]+)[ \t]*种", txt)
            if m and int(m.group(1)) != n:
                self.errors.append(f"SCHEMA.md 计数 {m.group(1)} ≠ RELATION_TYPES 的 {n}（口径漂移）")
            parts = [int(x) for x in _re.findall(r"^###[ \t]*2\.[0-9a-z]+[ \t]*[^（(]*[（(]([0-9]+)[ \t]*种", txt, _re.M)]
            if parts and sum(parts) != n:
                self.errors.append(f"SCHEMA.md 各域小节计数之和 {sum(parts)}（{parts}）≠ RELATION_TYPES 的 {n}（口径漂移）")

    def _check_namespace_inventory_consistency(self):
        """D-批（2026-10-14）：命名空间**清单**必须覆盖本体实际在用的全部命名空间。

        为什么：`bkn/SCHEMA.md` §0.1「命名空间约定」是「谁承载有哪些 ID」的入口，
        但它此前是**散文块**、无机检——新增命名空间会**静默不进清单**。实测 2026-10-14：
        本体 40 件实际用 **17** 个命名空间，SCHEMA §0.1 只列 **11** 个，**缺 9 个**，
        其中 `skill:` 是**用得最多的一个**（166 次 / 29 件）。

        口径（沿用 `_check_relation_type_count_consistency` 的"跨处口径一致性"范式）：
          - **声明集** = SCHEMA §0.1「命名空间约定」区段（到 `### 0.2` 为止）内反引号 token 的 `ns:`；
          - **使用集** = 本体 4 目录（objects/relations/actions/risks，**不含 templates**）
            内反引号 token 的 `ns:` ∪ `**源对象**`/`**目标对象**` 行；
          - 使用集 ⊄ 声明集 → **error**，逐项列出缺失命名空间。

        **只做单向检查**：声明集允许有本体零出现的项——`error:` 只作入口（§2.6）、
        `store:`/`tool:` 是 Tool 层权威（§1.3），它们是**合法**的，不是漂移。
        扫描**只看反引号 token**（`_namespaces_in`），理由见 `NS_TOKEN_RE` 注释。
        仅对**真实 BKN 根**运行（同 `_check_process_registry`）。
        """
        if not self._real_bkn_root():
            return
        schema = self.root / "SCHEMA.md"
        if not schema.is_file():
            return
        text = schema.read_text(encoding="utf-8", errors="ignore")
        if "命名空间约定" not in text or "### 0.2" not in text:
            return
        seg = text.split("命名空间约定", 1)[1].split("### 0.2", 1)[0]
        declared = self._namespaces_in(seg)

        used: set = set()
        for sub in ("objects", "relations", "actions", "risks"):
            d = self.root / sub
            if not d.is_dir():
                continue
            for f in sorted(d.glob("*.bkn")):
                used |= self._namespaces_in(f.read_text(encoding="utf-8", errors="ignore"))

        missing = sorted(used - declared)
        if missing:
            self.errors.append(
                "SCHEMA §0.1 命名空间清单缺 %d 个本体在用命名空间：%s"
                "（新增命名空间须同时进本清单与 RELATION_TARGET_NAMESPACES）"
                % (len(missing), " ".join("%s:" % m for m in missing))
            )

    @staticmethod
    def _namespaces_in(text: str) -> set:
        """取一段文本里反引号 token 的 `ns:` 前缀（跳过路径样 token 与豁免表）。

        源/目标对象行额外**整行**扫一遍：`- **目标对象**: architecture:*, target:*, topology:*`
        里的值不带反引号，只扫 token 会漏。
        """
        out: set = set()
        for raw in text.splitlines():
            for tok in re.findall(r"`([^`]+)`", raw):
                if _NS_PATHLIKE_RE.search(tok):
                    continue
                out |= {m.group(1) for m in NS_TOKEN_RE.finditer(tok)}
            if "**源对象**" in raw or "**目标对象**" in raw:
                out |= {m.group(1) for m in NS_TOKEN_RE.finditer(raw)}
        return out - NS_NOT_A_NAMESPACE

    def _check_action_constraint_refs(self):
        """D4（C-20261012-11）：动作文件 `constraints:` 字段 ↔ `constrained_by` 边 **双向一致**。

        病灶：该字段此前是自由散文，与边（权威）已多处漂移，且零机检
        （实测 30 处字段 / 27 条边：4 处语义完全对不上、2 处少列、1 处把有约束标成 read-only）。

        口径（2026-10-12 用户裁定）：
          - 字段形态**只有两种**：ID 列表 `[a, b]` 或空列表 `[]`；
          - 字段**必须存在**（缺失 → error，与 capability/object/implements 同级）；
          - 有边的动作：字段集合与边集合**逐项相等**（双向，缺一报一）；
          - 无边的动作：字段必须为空列表。
        散文中承载的、无边可绑的操作提示已**同批下延到对应 Skill**（见候选 review.md §6），
        所以"字段里有边、边里有字段"就是完整口径，不需要豁免表。

        与 `_check_constraint_edge_alignment` 的分工：那条管 **constraints.bkn 表 ↔ 边**，
        本条管 **动作文件字段 ↔ 边**；ID 是否存在仍由前者的双向校验负责，不重复。
        """
        if not (self.root / "SKILL.md").exists() or not (self.root / "objects").is_dir():
            return  # 只对真实 BKN 根运行（同 _check_alias_constants，避免 fixture 误报）
        actions_dir = self.root / "actions"
        routing_file = self.root / "relations" / "action_routing.bkn"
        if not actions_dir.is_dir() or not routing_file.exists():
            return

        # 边：只取 constrained_by 段的「源 → 目标」映射规则
        edges: dict = {}
        for section in re.split(r"^## ", routing_file.read_text(encoding="utf-8", errors="ignore"),
                                flags=re.MULTILINE):
            if "**关系类型**: constrained_by" not in section:
                continue
            for m in re.finditer(r"^[ \t]*-[ \t]*`([a-z][a-zA-Z0-9_]*)`[ \t]*→[ \t]*`([a-z][a-zA-Z0-9_]*)`",
                                 section, re.MULTILINE):
                edges.setdefault(m.group(1), set()).add(m.group(2))

        for f in sorted(actions_dir.glob("*.bkn")):
            rel = f"actions/{f.name}"
            text = f.read_text(encoding="utf-8", errors="ignore")
            for section in re.split(r"^## ", text, flags=re.MULTILINE):
                if not section.startswith("Action:"):
                    continue
                title = section.split("\n", 1)[0].strip()
                title = re.sub(r"^Action:[ \t]*", "", title)
                cap_m = re.search(r"^- capability:[ \t]*(\S+)", section, re.MULTILINE)
                if cap_m is None:
                    continue  # 缺 capability 已由 _check_action_file 报 error
                cap = cap_m.group(1)
                want = edges.get(cap, set())

                field_m = re.search(r"^- constraints:[ \t]*(.*)$", section, re.MULTILINE)
                if field_m is None:
                    self.errors.append(
                        f"{rel}: Action '{title}'（{cap}）缺 constraints 字段"
                        "（口径：ID 列表或空列表，字段必须存在）")
                    continue
                raw = field_m.group(1).strip()
                if raw in ("", "[]"):
                    got: set = set()
                elif raw.startswith("[") and raw.endswith("]"):
                    items = [c.strip() for c in raw[1:-1].split(",") if c.strip()]
                    bad = [c for c in items if not re.match(r"^[a-z][a-zA-Z0-9_]*$", c)]
                    if bad:
                        self.errors.append(
                            f"{rel}: Action '{title}'（{cap}）constraints 含非约束ID项 {bad}"
                            "（口径：只能是约束ID列表；自由散文须下延到对应 Skill）")
                        continue
                    got = set(items)
                else:
                    self.errors.append(
                        f"{rel}: Action '{title}'（{cap}）constraints 不是 ID 列表: {raw!r}"
                        "（口径：ID 列表或空列表）")
                    continue

                for cid in sorted(got - want):
                    self.errors.append(
                        f"{rel}: Action '{title}'（{cap}）constraints 列了 '{cid}'，"
                        "但 action_routing.bkn 无对应 constrained_by 边（双向一致性，字段侧多余）")
                for cid in sorted(want - got):
                    self.errors.append(
                        f"{rel}: Action '{title}'（{cap}）constraints 缺 '{cid}'，"
                        "但 action_routing.bkn 有该 constrained_by 边（双向一致性，字段侧漏列）")

    def _check_action_file(self, f: Path, rel: str, content: str):
        """1/2/5: Action 段含 capability/object/implements; implements 以 skill: 开头且 skill 存在"""
        for section in re.split(r"^## ", content, flags=re.MULTILINE):
            if not section.startswith("Action:"):
                continue
            title = section.split("\n", 1)[0].strip()
            for field in ("capability", "object", "implements"):
                if not re.search(rf"^[ \t-]*{field}:", section, re.MULTILINE):
                    self.errors.append(f"{rel}: Action '{title}' 缺少 {field}")
            m = re.search(r"implements:[ \t]*(\S+)", section)
            if m:
                target = m.group(1)
                if not target.startswith("skill:"):
                    self.warnings.append(f"{rel}: Action '{title}' implements 应以 skill: 开头: {target}")
                else:
                    skill_name = target[len("skill:"):]
                    if not (SKILL_ROOT / skill_name).exists():
                        self.errors.append(f"{rel}: Action '{title}' 引用的 skill 不存在: {skill_name}")
            # access_type / binding_type 枚举校验（出现才校验）
            m = re.search(r"access_type:[ \t]*([a-zA-Z0-9_]+)", section)
            if m and m.group(1) not in VALID_ACCESS_TYPES:
                self.warnings.append(f"{rel}: Action '{title}' 非法 access_type: {m.group(1)}")
            m = re.search(r"binding_type:[ \t]*([a-zA-Z0-9_]+)", section)
            if m and m.group(1) not in VALID_BINDING_TYPES:
                self.warnings.append(f"{rel}: Action '{title}' 非法 binding_type: {m.group(1)}")

    def _check_relation_file(self, f: Path, rel: str, content: str):
        """3/4/6: 关系类型白名单; Relation 段缺关系类型警告; 中文名建议"""
        # 「像 Relation 但缺关系类型」的段落
        for section in re.split(r"^## ", content, flags=re.MULTILINE):
            if section.startswith("Relation:") and "**关系类型**" not in section:
                title = section.split("\n", 1)[0].strip()
                self.warnings.append(f"{rel}: Relation 段缺「关系类型」，将被跳过不入图: {title}")
        # 关系类型白名单
        for m in re.finditer(r"\*\*关系类型\*\*:[ \t]*([a-zA-Z0-9_]+)", content):
            rt = m.group(1)
            if rt not in RELATION_TYPES:
                self.errors.append(f"{rel}: 非法关系类型: {rt}")
        # 中文名建议
        n_type = len(re.findall(r"\*\*关系类型\*\*:", content))
        n_zh = len(re.findall(r"\*\*中文名\*\*:", content))
        if n_type > n_zh:
            self.infos.append(f"{rel}: {n_type - n_zh} 个 Relation 段缺「中文名」")

    def _check_risk_file(self, f: Path, rel: str, content: str):
        """8: severity / risk_type 枚举校验"""
        for m in re.finditer(r"\*\*风险级别\*\*:[ \t]*([a-zA-Z0-9_]+)", content):
            sev = m.group(1)
            if sev not in VALID_SEVERITY:
                hint = SEVERITY_LEGACY_MAP.get(sev)
                msg = f"{rel}: 非标准 severity: {sev}"
                if hint:
                    msg += f"（建议归一为 {hint}）"
                    self.warnings.append(msg)
                else:
                    self.errors.append(msg)
        for m in re.finditer(r"\*\*risk_type\*\*:[ \t]*([a-zA-Z0-9_]+)", content):
            rt = m.group(1)
            if rt not in VALID_RISK_TYPES:
                self.errors.append(f"{rel}: 非法 risk_type: {rt}")
        # 约束表格「类型」列（constraints.bkn 风格）
        for m in re.finditer(r"\|[^|\n]*\| ([a-z_]+) \|[^|\n]*\|[^|\n]*\|", content):
            t = m.group(1)
            if t not in VALID_RISK_TYPES and t not in ("类型",):
                # 只报告看起来像类型位置的非法值（避免误报正文表格）
                if t.startswith(("state_", "param_", "forbidden", "threshold", "resource")):
                    self.warnings.append(f"{rel}: 约束表类型列疑为非枚举值: {t}")

    def _check_ref_resolution(self, f: Path, rel: str, content: str):
        """批 7-3：双向引用完整性——BKN 的 skill:/tool:/store: 引用必须在 manifest 中存在（正向防悬空）。

        反向（manifest 每项须被 ≥1 条边引用，防孤儿/清单膨胀）在 run() 收尾统一做。
        """
        try:
            from plugin.manifest import load_manifest
            m = load_manifest()
            skill_ids = {s.get("id") for s in m.get("skills", [])}
            tool_ids = {t.get("id") for t in m.get("tools", [])}
            store_ids = {st.get("id") for st in m.get("stores", [])}
        except Exception:
            return  # manifest 不可用时不阻塞（兜底）
        for mm in re.finditer(r"(?:skill|tool):[a-z0-9_-]+", content):
            token = mm.group(0)
            if token.startswith("skill:") and token not in skill_ids:
                self.errors.append(f"{rel}: skill 引用 {token} 未在 manifest 登记（悬空）")
            elif token.startswith("tool:") and token not in tool_ids:
                self.errors.append(f"{rel}: tool 引用 {token} 未在 manifest 登记（悬空）")
        for mm in re.finditer(r"store:[a-z0-9_]+", content):
            token = mm.group(0)
            if token.endswith((":xxx", ":yyy")):  # 占位符示例（store-registry 说明文字）
                continue
            if token not in store_ids:
                self.errors.append(f"{rel}: store 引用 {token} 未在 manifest 登记（悬空）")

    def _check_manifest_orphans(self):
        """批 7-3 反向：manifest 每项须被 ≥1 条边引用（防孤儿/清单膨胀，Q3「清单走」配套牙齿）。"""
        try:
            from plugin.manifest import load_manifest
            m = load_manifest()
        except Exception:
            return
        bkn_text = ""
        for f in sorted(self.root.rglob("*.bkn")):
            if f.name.startswith("templates"):
                continue
            bkn_text += f.read_text(encoding="utf-8", errors="ignore")
        # 26 号：stores/tools 是 Tool 层基础设施（检索路由/查询引擎，manifest 权威），BKN 不再引用——豁免孤儿检查；
        # skills 仍须被 BKN 引用（防清单膨胀）。
        for section in ("skills",):
            for item in m.get(section, []):
                id_ = item.get("id", "")
                if id_ and id_ not in bkn_text:
                    self.warnings.append(
                        f"manifest.{section}: {id_} 未被任何 .bkn 引用（孤儿项，清单膨胀）")

    def _check_skill_manifest_bkn_contract(self):
        """G-15（对照驱动，2026-10-14 采纳）：`skill_manifest.yaml` 的 `bkn_contract`
        只能声明**本体里真实存在**的 ID。

        为什么：本仓 34 个 Skill 与本体之间此前**没有显式接口**——「这个 Skill 依赖哪些
        对象 / 动作 / 风险策略」只能靠读 SKILL.md 推断。

        口径（宽松但不容错）：
          - 字段**可选**：未声明 ⇒ 视为「尚未登记契约」，**不报错**（不搞"必须填"）；
          - 声明了就必须**双通过**：① 命名空间在 `SCHEMA.md` §0.1 清单内；
            ② 该 ID 在本体 4 目录（objects / relations / actions / risks）里**出现过**；
          - 任一不过 ⇒ **error**（**声明错比不声明更坏**：它让人以为本体里有这个 ID）。

        实现：只认 **6 空格缩进**的 `objects:` / `actions:` / `risk_policy:` 行（`bkn_contract`
        的下一层）；`treatment_entry` 的下一层是 file/section/note，不会误命中。
        仅对**真实仓库**运行（需要 `plugin/skill_manifest.yaml`）。
        """
        if not self._real_bkn_root():
            return
        manifest = self.root.parent / "plugin" / "skill_manifest.yaml"
        if not manifest.is_file():
            return

        declared_ns: set = set()
        schema = self.root / "SCHEMA.md"
        if schema.is_file():
            text = schema.read_text(encoding="utf-8", errors="ignore")
            if "命名空间约定" in text and "### 0.2" in text:
                declared_ns = self._namespaces_in(
                    text.split("命名空间约定", 1)[1].split("### 0.2", 1)[0])

        corpus = ""
        for sub in ("objects", "relations", "actions", "risks"):
            d = self.root / sub
            if not d.is_dir():
                continue
            for f in sorted(d.glob("*.bkn")):
                corpus += f.read_text(encoding="utf-8", errors="ignore")

        cur = ""
        for lineno, raw in enumerate(
                manifest.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            m = re.match(r"[ \t]*-[ \t]*id:[ \t]*([A-Za-z0-9_:.+-]+)", raw)
            if m:
                cur = m.group(1)
                continue
            m = re.match(r"^ {6}(objects|actions|risk_policy):[ \t]*\[(.*)\][ \t]*$", raw)
            if not m or not cur:
                continue
            for ident in [x.strip() for x in m.group(2).split(",") if x.strip()]:
                ns = ident.split(":", 1)[0] if ":" in ident else ""
                if not ns or ns not in declared_ns:
                    self.errors.append(
                        "%s: skill_manifest.yaml:%d 的 bkn_contract.%s 声明 %r："
                        "命名空间不在 SCHEMA §0.1 清单内（或缺少前缀）"
                        % (cur, lineno, m.group(1), ident))
                elif ident not in corpus:
                    self.errors.append(
                        "%s: skill_manifest.yaml:%d 的 bkn_contract.%s 声明 %r："
                        "本体 4 目录内**查无此 ID**（拼写错？或本体已删？）"
                        % (cur, lineno, m.group(1), ident))

    def _check_skills_referenced(self, f: Path, rel: str, content: str):
        """7: implements 绑定只允许出现在 actions/ 与 relations/action_routing.bkn。

        注意: 「负责 Skill: `skill:xxx`」式的 Skill 指针是 BKN 的合法设计
        （BKN 保留语义与 Skill 指针），只在 implements 绑定意义上强制单一事实源。
        """
        if rel.startswith("actions/") or rel == "relations/action_routing.bkn":
            return
        for m in re.finditer(r"implements[^:\n]*:[ \t]*skill:([a-zA-Z0-9_\-]+)", content):
            self.errors.append(
                f"{rel}: implements 绑定出现在非单一事实源文件: skill:{m.group(1)}"
                "（skill 绑定只允许在 actions/ 与 action_routing.bkn）")

    # ---------- O-域 段类型与症状归类 (14-symptom-ontology-design 批次二) ----------

    def _get_traverser(self) -> RelationTraverser:
        """惰性构建关系图遍历器（症状归类校验用）。"""
        if self._traverser is None:
            self._traverser = RelationTraverser(str(self.root))
        return self._traverser

    def _check_section_types(self, f: Path, rel: str, content: str):
        """11: `<!-- type: xxx -->` 取值必须在 VALID_SECTION_TYPES 内（4 种本体形态）。

        23 号：`index` / `matrix` 已废止——导航下延 Tool/SKILL.md；交叉矩阵下延 Skill references。
        24 号：`symptom` / `class` 随目录收拢退役（零使用者）；26 号 diagnostics.bkn 溶解后，
        诊断内容由边承载（`suspected_in` / `has_class`）。
        """
        _RETIRED = {
            "index": "23 号：本体层只留定义/关系/实例登记——导航下延 Tool 层/SKILL.md，"
                     "表格下延 Skill references，视图由边派生",
            "matrix": "23 号：交叉矩阵下延 Skill references（本体层只留定义/关系/实例登记）",
            "symptom": "24 号：目录收拢后退役（零使用者）——规范症状 ID 空间归边"
                       "（`suspected_in` / `has_class`），别名在 `plugin/constants.py`",
            "class": "24 号：随 `class:*` 命名空间退场一并退役——诊断目标用 `process:*` / `dimension:*`",
            "scenario": "26 号：归档为 entity 类定义——方案类对象用 `entity` 段 + `scenario:` 命名空间（四元收敛）",
        }
        for m in re.finditer(r"<!--[ \t]*type:[ \t]*([a-zA-Z0-9_]+)[ \t]*-->", content):
            t = m.group(1)
            if t not in VALID_SECTION_TYPES:
                if t in _RETIRED:
                    self.errors.append(f"{rel}: 段类型 '{t}' 已废止（{_RETIRED[t]}）")
                else:
                    self.errors.append(f"{rel}: 非法 section type: {t}")

    def _symptom_nodes(self, traverser) -> set:
        """图里的全部 `symptom:*` 节点（源 ∪ 目标）。"""
        nodes = {n for n in traverser.graph if n.startswith("symptom:")}
        for rels in traverser.graph.values():
            for targets in rels.values():
                nodes.update(t for t in targets if t.startswith("symptom:"))
        return nodes

    def _real_bkn_root(self) -> bool:
        """两条症状检查仅对**真实 BKN 根**运行（含 SKILL.md 与 objects/）——fixture 目录跳过，
        先例 `_check_process_registry`。"""
        return (self.root / "SKILL.md").exists() and (self.root / "objects").is_dir()

    def _check_symptom_edges(self):
        """症状节点必须有归类边（`suspected_in` / `has_class` 任一）。

        扫**图**而非 `## Symptom:` 段——症状已不建段（只作为边端点），旧实现（扫段）是**死检查**
        （2026-10-12 第七条收口批发现并替换；见 doc/optimize/34 号）。
        """
        if not self._real_bkn_root():
            return
        traverser = self._get_traverser()
        for node in sorted(self._symptom_nodes(traverser)):
            if not traverser.get_targets(node, "suspected_in") \
               and not traverser.get_classes_for_symptom(node):
                self.errors.append(
                    f"{node}: 症状节点无归类边（`suspected_in` / `has_class` 至少一条，"
                    "在 bkn/relations/process_topology.bkn 补一行）")

    def _check_symptom_registry(self):
        """症状注册集一致性：图里的 `symptom:*` 集合 == `SYMPTOM_ALIASES` 的**值集**。

        防两端漂移：别名指向不存在的症状（幽灵值）／症状节点漏登别名表。
        先例：`DIMENSION_ALIASES ↔ objects/dimensions.bkn`。仅对真实 BKN 根运行。
        """
        if not self._real_bkn_root():
            return
        try:
            from plugin.constants import SYMPTOM_ALIASES
        except Exception:
            return
        graph_ids = {n.split(":", 1)[1] for n in self._symptom_nodes(self._get_traverser())}
        alias_ids = set(SYMPTOM_ALIASES.values())
        for miss in sorted(alias_ids - graph_ids):
            self.errors.append(
                f"constants.SYMPTOM_ALIASES: 值 '{miss}' 没有对应的 symptom:{miss} 节点（幽灵值）")
        for miss in sorted(graph_ids - alias_ids):
            self.errors.append(f"symptom:{miss}: 不在 SYMPTOM_ALIASES 值集（别名表漏登）")

    def _check_prerequisites_coverage(self):
        """5: prerequisites.bkn 为按约束维度的 T-Box 常数段（批 2-1 收敛后口径）。

        逐 action 前置已改由 constrained_by 边 × constraints.bkn 派生
        （resolver.get_prerequisites 实时组装），本文件不再承载逐 Action 条目；
        段名须为 `<risk_type> — <中文名>`（risk_type ∈ SCHEMA 枚举）或
        「只读查询」兜底段。新增维度属 T-Box 常数变更，须人工评审（C5）。
        """
        prereq = self.root / "risks" / "prerequisites.bkn"
        if not prereq.exists():
            self.warnings.append("risks/prerequisites.bkn 不存在")
            return
        content = prereq.read_text(encoding="utf-8", errors="ignore")
        readonly_prefix = "只读查询"
        for title, sec_type, _body in self._iter_sections(content):
            if sec_type != "risk":
                self.warnings.append(
                    f"risks/prerequisites.bkn: 段「{title}」类型标注应为 "
                    f"risk（T-Box 维度段），现为 {sec_type}")
            risk_type = title.split(" — ")[0].strip()
            if risk_type.startswith(readonly_prefix):
                continue
            if risk_type not in VALID_RISK_TYPES:
                self.errors.append(
                    f"risks/prerequisites.bkn: 段「{title}」的维度 {risk_type!r} "
                    "不在 SCHEMA risk_type 枚举内（新增维度属 T-Box 常数变更，须人工评审并登记）")

    # ---------- 本体 vs 索引 / 图谱完整性 (15-ontology-conformance-audit) ----------

    @staticmethod
    def _iter_sections(content: str) -> list:
        """按 `## ` 切段, 回填每段紧邻其前的 `<!-- type: xxx -->` 标注。

        产出 (标题, 段类型或 None, 段正文)。文件级标注（出现在首个 `## ` 之前）
        会被后续标注覆盖, 不会误挂到第一段。
        """
        sections = []
        marker = None
        for line in content.split("\n"):
            if re.match(r"<!--[ \t]*type:[ \t]*[a-zA-Z0-9_]+[ \t]*-->", line.strip()):
                marker = re.findall(r"type:[ \t]*([a-zA-Z0-9_]+)", line)[0]
                continue
            if line.startswith("## "):
                sections.append([line[3:].strip(), marker, []])
                marker = None
                continue
            if sections:
                sections[-1][2].append(line)
        return [(h, t, "\n".join(b)) for h, t, b in sections]

    def _check_relation_target_namespace(self, f: Path, rel: str, content: str):
        """11c: relations/*.bkn 中 O-域与 risks_of 关系的目标须带命名空间前缀。

        仅覆盖 `RELATION_TARGET_NAMESPACES` 列出的 5 种关系（目标为受控命名空间）；
        其余关系的目标是对象/动作/中文操作名，不强制前缀，避免误报。
        """
        for heading, _stype, body in self._iter_sections(content):
            m = re.search(r"\*\*关系类型\*\*:[ \t]*([a-zA-Z0-9_]+)", body)
            if not m:
                continue
            rt = m.group(1)
            allowed = RELATION_TARGET_NAMESPACES.get(rt)
            if not allowed:
                continue
            for line in body.split("\n"):
                em = re.match(r"-[ \t]*`([^`]+)`[ \t]*→[ \t]*`([^`]+)`", line.strip())
                if not em:
                    continue
                src, tgt = em.group(1).strip(), em.group(2).strip()
                # 括号注释：源/目标都不允许（标识符内混入说明文字）
                for ident in (src, tgt):
                    if "(" in ident or ")" in ident:
                        self.warnings.append(
                            f"{rel}: 段「{heading}」标识符混入括号注释: {ident}"
                            "（说明文字应放 `#` 注释或 `中文名` 字段）")
                # 非 ASCII 实例名：只查目标（源侧实例名如 scenario:跨平台迁移 属既有约定）
                if not tgt.isascii():
                    self.warnings.append(
                        f"{rel}: 段「{heading}」({rt}) 目标含非 ASCII 实例名: {tgt}"
                        "（应用 snake_case 标识符，中文名放 `中文名` 字段或 `#` 注释）")
                if not tgt.startswith(tuple(allowed)):
                    self.warnings.append(
                        f"{rel}: 段「{heading}」({rt}) 目标 '{tgt}' 缺少命名空间前缀"
                        f"（应为 {' / '.join(allowed)}）")

    def _check_namespace_registry_consistency(self):
        """4-1：命名空间注册表防漂移（机制固化）。

        新增关系类型时若它需要受控命名空间，必须同时在
        `plugin/constants.py::RELATION_TARGET_NAMESPACES` 登记——否则
        `_check_relation_target_namespace` 对它的目标**静默跳过**（`allowed` 为空 → continue），
        命名空间约束形同虚设。本检查把「该登记而没登记」从静默升级为 error。

        同时校验注册表的 key 必须是 `RELATION_TYPES` 成员（防 typo 成幽灵键）。
        """
        for rt in RELATION_TARGET_NAMESPACES:
            if rt not in RELATION_TYPES:
                self.errors.append(
                    f"constants.RELATION_TARGET_NAMESPACES: 键 '{rt}' 不在 "
                    "RELATION_TYPES 中（幽灵键：该关系类型不存在或已改名）")

    # ---------- 25 号：诊断别名常量 ↔ 边 一致性 ----------

    def _object_heading_kind(self, path: Path) -> str:
        """对象文件首个一级标题的类别（`# Process: iatrack (增量解析进程)` → `process`）。

        丙-8：「是不是进程对象」由**文件自己声明**——进程对象用 `# Process:` 标题，
        其它族各用自己的标题（`# Object:` / `# Product:` / `# Dimensions:` /
        `# Scenario:` / `# Topology:`）。该约定成为 `_check_process_registry` 的判据，
        故一并做反向校验（见下）。取**第一个** `#` 开头的行；无冒号则视为未声明。
        """
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return ""
        for line in text.splitlines():
            if not line.startswith("#"):
                continue
            head = line[1:]
            return head.split(":", 1)[0].strip().lower() if ":" in head else ""
        return ""

    def _check_process_registry(self):
        """PROCESS_IDS 注册集 ↔ `objects/<id>.bkn` 一致性（丙-8：改**内容判据**，不扩硬编码名单）。

        两个方向：
        - 常量成员必须有对象文件，且该文件以 `# Process:` 标题声明（否则「进程对象」的
          识别依据就断了——本检查的另一半正靠它）→ error；
        - 声明为 `# Process:` 的对象不在 PROCESS_IDS → info（提示补常量）。

        为什么用标题而不用排除法（原实现）：排除法维护一张「非进程对象」硬编码名单
        （11 个名字 ＋ `scenario-*` 前缀），每新增一个对象族就得扩一次名单，且机制类
        （`objects/fault_mechanism.bkn` 等 5 个）被**误报**。改成「文件自己声明是不是
        进程」后，非进程对象族**无需登记**即不误报——名单随之删除（丙-8 根因）。
        仅对真实 BKN 根运行（fixture 目录无 SKILL.md/objects，跳过以免误报）。
        """
        if not self._real_bkn_root():
            return
        try:
            from plugin.constants import PROCESS_IDS
        except Exception:
            return
        registered = set(PROCESS_IDS)
        objects_dir = self.root / "objects"
        for pid in sorted(registered):
            f = objects_dir / f"{pid}.bkn"
            if not f.exists():
                self.errors.append(
                    f"constants.PROCESS_IDS: 进程 '{pid}' 缺少对象文件 objects/{pid}.bkn"
                    "（常量集与本体不一致）")
            elif self._object_heading_kind(f) != "process":
                self.errors.append(
                    f"objects/{pid}.bkn: PROCESS_IDS 成员必须以 `# Process:` 标题声明"
                    "（进程对象的识别依据，见 lint `_check_process_registry`）")
        for f in sorted(objects_dir.glob("*.bkn")):
            if f.stem in registered:
                continue
            if self._object_heading_kind(f) == "process":
                self.infos.append(
                    f"objects/{f.stem}.bkn: 声明为进程对象（`# Process:`）但不在 "
                    "PROCESS_IDS 注册集（若确为进程请补 plugin/constants.py 常量）")

    def _check_no_error_nodes(self, f, rel, content):
        """内容文件里不得出现 `error:` 节点（防回潮；模板与文档不在此 walk 内）。

        为什么：错误码空间无上界（用户裁定 Q27）——码只作入口，**不进本体**；
        含义规则在 Tool 层 `plugin/error_semantics.yaml`，由 `diagnose_error` 运行时解析。
        见 02 号 §0（本体原则）与 doc/optimize/32 号。
        """
        for lineno, line in enumerate(content.split("\n"), 1):
            if "`error:" in line or "error:*" in line:
                self.errors.append(
                    f"{rel}:{lineno}: 出现 `error:` 节点——错误码不进本体（Q27）；"
                    "含义规则见 plugin/error_semantics.yaml（或改指向 symptom:/dimension:/process:）")

    def _check_no_bare_error_codes(self, f, rel, content):
        """D5（C-20261012-12）：内容文件不得出现**裸错误码**（防回潮）。

        为什么：错误码空间随外部世界线性增长（用户裁定 Q27）——码只作入口，**不进本体**；
        含义规则在 Tool 层 `plugin/error_semantics.yaml`（按消息文本命中，不按码查表）。
        与 `_check_no_error_nodes` 的分工：那条拦 `error:` **节点**形式，本条拦**裸码**（`-4071` / `(-4031)` 等）。
        **注释不豁免**（2026-10-12 裁定）：判据单一，不开后门。
        """
        for lineno, line in enumerate(content.split("\n"), 1):
            for m in re.finditer(r"(?<![0-9A-Za-z])-[0-9]{3,5}(?![0-9])", line):
                self.errors.append(
                    f"{rel}:{lineno}: 出现裸错误码 {m.group(0)}——码不进本体（Q27）；"
                    "含义规则见 plugin/error_semantics.yaml，或改指 symptom:/dimension: 引用")

    def _check_no_code_symbols(self, f, rel, content):
        """65 号（61 号批 P-2D-1）：内容文件不得出现**码的符号名**（`IAERR_*` / `ALARM_*`）。

        为什么单列一条：`_check_no_bare_error_codes` 拦的是**数字形态**（`-4071`），
        而官方码表同时有**符号名**（`IAERR_RULE_NOT_FOUND` / `ALARM_CPU_TOOMUCH`，共 164 / 176 条）。
        `plugin/error_codes.yaml` 以 `define` 为键，若被写进 `.bkn` 同样是**按码枚举**（Q27 的精神）。

        **只拦这两个无歧义前缀**：通用的 `E*` 前缀（`ECONN_ERR` / `EVERSION` 等）会误伤普通标识符。
        """
        for lineno, line in enumerate(content.split(chr(10)), 1):
            for m in re.finditer(r"(?<![0-9A-Za-z_])(IAERR|ALARM)_[A-Z0-9_]+", line):
                self.errors.append(
                    f"{rel}:{lineno}: 出现码的符号名 {m.group(0)}——码不进本体（Q27）；"
                    "含义在 Tool 层侧车 plugin/error_codes.yaml（按官方含义判类），"
                    "或改指 symptom:/dimension:/process: 引用")
    def _check_alias_constants(self):
        """25 号：别名常量只做「口语 → 规范 ID」归一，**规范 ID 空间由边承载**。

        校验（防常量漂移成隐形清单）：
          ① 错误码别名与症状别名的值必须格式合法（错误码族 / symptom ID snake_case）；
          ② 别名指向的 ID 必须能在**边**（`suspected_in` / `has_class`）中找到；
          ③ 维度别名必须指向 `dimension:*` 注册集成员。
        边 = 权威；常量里出现边上没有的 ID → error（该补边，或在别名层修正拼写）。

        仅对**真实 BKN 根**运行（含 SKILL.md 与 objects/）——lint 测试的临时 fixture 目录
        不会带全量本体，跳过以免误报。
        """
        if not (self.root / "SKILL.md").exists() or not (self.root / "objects").is_dir():
            return
        try:
            from plugin.constants import (
                ERROR_ALIASES, SYMPTOM_ALIASES, DIMENSION_ALIASES, VALID_SECTION_TYPES,
            )
        except Exception:
            return
        traverser = self._get_traverser()
        # ① 格式
        for alias, code in ERROR_ALIASES.items():
            if not re.match(r"^(-[0-9]+|[A-Z][A-Z0-9]*-[0-9]+)$", code):
                self.errors.append(
                    f"constants.ERROR_ALIASES: '{alias}' → '{code}' 不是合法错误码（-数字 / 前缀-数字）")
        for alias, sid in SYMPTOM_ALIASES.items():
            if not re.match(r"^[a-z][a-z0-9_]*$", sid):
                self.errors.append(
                    f"constants.SYMPTOM_ALIASES: '{alias}' → '{sid}' 不是合法症状 ID（snake_case）")
        # ③ 维度别名 → dimension 注册集
        registered_dims: set[str] = set()
        dim_file = self.root / "objects" / "dimensions.bkn"
        if dim_file.exists():
            for m in re.finditer(r"`dimension:([a-z0-9_]+)`", dim_file.read_text(encoding="utf-8")):
                registered_dims.add(m.group(1))
        for alias, dim in DIMENSION_ALIASES.items():
            if dim not in registered_dims:
                self.errors.append(
                    f"constants.DIMENSION_ALIASES: '{alias}' → '{dim}' 不在 objects/dimensions.bkn 注册集"
                    f"（{sorted(registered_dims)}）")
        # ② 别名 → 边（**只对症状**；错误码按 Q27 已退出本体，不再要求有边）
        # 错误码的别名只做「现场口语 → 规范码」的**归一**；它的语义由含义链在运行时解析
        # （`plugin/error_semantics.yaml` 的有界规则 + Qdrant 模式库），不查边。
        # 见 doc/build/demo_product-bkn/02-bkn_design_philosophy.md §0 与 doc/optimize/32 号。
        for alias, sid in SYMPTOM_ALIASES.items():
            node = f"symptom:{sid}"
            if not (traverser.get_targets(node, "suspected_in")
                    or traverser.get_targets(node, "has_class")):
                self.errors.append(
                    f"constants.SYMPTOM_ALIASES: '{alias}' → '{sid}' 在边中不存在"
                    "（规范 ID 空间由 suspected_in/has_class 边承载——请先在 "
                    "bkn/relations/process_topology.bkn 补边，或修正别名）")

    # ---------- 23 号：本体层载荷约束（表格只允许实例登记） ----------

    def _check_no_explanatory_tables(self, f: Path, rel: str, content: str):
        """23 号：定义段内表格必须为**实例登记**——描述性/对照性表格属延展层，须下延 Skill。

        合法表格判据（二者其一）：
          ① 行首列全部为带命名空间 ID（如 `error:-4073` / `store:xxx` / `dimension:xxx`）；
          ② 段内声明 `> 行 = <注册集名> 实例`（注册集以命名空间前缀标识，行内其余列 ⊆ 已声明字段）。
        不满足 → error（提示下延 Skill references；本体层只留 KV + 实例登记）。
        """
        for heading, stype, body in self._iter_sections(content):
            if stype not in ("entity", "class", "action", "risk", "symptom"):
                continue
            table = self._first_table(body)
            if not table:
                continue
            # ① 段内声明 `> 行 = ... 实例`
            if re.search(r"^>[ \t]*行[ \t]*=[^\n]*实例", body, re.M):
                continue
            # ② 行首列全部为命名空间 ID
            header, rows = table[0], [r for r in table[1:] if any(c.strip() for c in r)]
            if not rows:
                continue
            first_col = [(r[0] or "").strip() for r in rows]
            if all(NAMESPACE_ID_PATTERN.match(c) for c in first_col if c):
                continue
            self.errors.append(
                f"{rel}: {stype} 段「{heading}」含非实例登记表格"
                f"（行首列 '{first_col[0][:24]}' 无命名空间 ID）——"
                "23 号：本体层表格只允许实例登记（行首带 `ns:id`）；"
                "说明性/对照性表格请下延 Skill references")

    def _check_bkn_file_refs(self, f: Path, rel: str, content: str):
        """23 号：指向 `*.bkn` 的引用必须指向**存在**的文件（防删除后留死指针）。

        只报 info：历史叙述行（含「已删/下延/取代/迁入/待核」等标记）为有意留存，跳过。
        裸文件名（无路径）按 bkn/ 下任意同名文件命中即算存在。
        """
        _HISTORICAL = ("已删", "删除", "下延", "取代", "迁入", "迁出", "迁移", "并入",
                       "下沉", "清理", "历史", "待核", "已废", "退场")
        basenames = {p.name for p in self.root.rglob("*.bkn")}
        for lineno, line in enumerate(content.split("\n"), 1):
            if not line.strip() or any(m in line for m in _HISTORICAL):
                continue
            for m in re.finditer(r"[A-Za-z0-9_./-]*[A-Za-z0-9_-]+\.bkn", line):
                token = m.group(0).lstrip("./")
                if token.startswith(("{", "<")):
                    continue
                if "/" not in token:
                    if token in basenames:
                        continue
                else:
                    cands = [self.root / token, self.root.parent / token,
                             self.root / token.split("/", 1)[-1]]
                    if any(c.exists() for c in cands):
                        continue
                self.infos.append(
                    f"{rel}:{lineno}: 引用 '{token}' 不存在（疑似陈旧指针）")

    def _check_skill_file_refs(self, f: Path, rel: str, content: str):
        """落点重映射（2026-09-24）：指向 `skill:<id>/<path>` 的引用必须存在（防死指针）。

        只报 info：历史叙述行（含「已删/迁出/并入/原 … 」等标记）为有意留存，跳过。
        路径解析：`skill:demo_product-xxx/references/yyy.md` → `<repo>/skill/demo_product-xxx/references/yyy.md`。
        """
        _HISTORICAL = ("已删", "删除", "迁出", "迁入", "迁移", "并入", "下沉", "历史",
                       "待核", "已废", "退场", "~~")
        project_root = self.root.parent
        for lineno, line in enumerate(content.split("\n"), 1):
            if not line.strip() or any(m in line for m in _HISTORICAL):
                continue
            for m in re.finditer(r"skill:[a-z0-9_-]+/[A-Za-z0-9_./-]+\.md", line):
                token = m.group(0)
                sid, path = token.split("/", 1)
                target = project_root / "skill" / sid.split(":", 1)[-1] / path
                if target.exists():
                    continue
                self.infos.append(
                    f"{rel}:{lineno}: 引用 '{token}' 不存在（疑似死指针）")

    @staticmethod
    def _first_table(body: str):
        """取段内第一个 markdown 表格 → [header, *rows]，无表返回 None。

        只取**连续**的表行块（表头 + 分隔行 + 数据行），遇到空行/非表行即停——
        段内多张表时只解析第一张（不跨表拼接）。
        """
        raw = body.split("\n")
        start = None
        for i, l in enumerate(raw):
            if l.strip().startswith("|"):
                start = i
                break
        if start is None:
            return None
        lines = []
        for l in raw[start:]:
            if not l.strip().startswith("|"):
                break
            lines.append(l.strip())
        sep_idx = None
        for i, l in enumerate(lines):
            if set(l) <= set("|-: "):
                sep_idx = i
                break
        if sep_idx is None:
            return None
        header = [c.strip() for c in lines[0].strip("|").split("|")]
        rows = []
        for l in lines[sep_idx + 1:]:
            cells = [c.strip() for c in l.strip("|").split("|")]
            if any(cells):
                rows.append(cells)
        return [header] + rows

    def _check_form_semantics(self, f: Path, rel: str, content: str):
        """P2 形态一致性：`risk` 段正文须有风险语义标记（防「就近塞」错标）。

        判据见 17 号 §3.3 G2；23 号后 matrix/index 已废止，本检查只保留 risk 分支。
        """
        for heading, stype, body in self._iter_sections(content):
            if rel.endswith("prerequisites.bkn"):
                continue  # 批 2-1 维度段（risk_type 标题即语义），P2 豁免
            if stype == "risk":
                has_risk_marker = ("**风险级别**" in body or "**risk_type**" in body
                                   or "**诊断类**" in body or "**约束ID**" in body
                                   or self._first_table(body) is not None)
                if not has_risk_marker:
                    self.warnings.append(
                        f"{rel}: risk 段「{heading}」无风险级别/risk_type/表格标记，"
                        "疑似错标（按内容改标：约束表 / 原则 / 下延 Skill）")

    def _check_relation_sections_outside_dir(self, f: Path, rel: str, content: str):
        """6(泛化): 非 relations/ 目录下的 `## Relation:` 段不会入图，须显式声明。

        泛化自原 `_check_root_topology_relations`（原实现只认根级 topology.bkn）。
        豁免: 文件内已声明「不入图」（含「不入」与「关系图」两词）。
        """
        if rel.startswith("relations/") or "## Relation:" not in content:
            return
        if "不入" in content and "关系图" in content:
            return
        for heading, _stype, _body in self._iter_sections(content):
            if heading.startswith("Relation:"):
                self.warnings.append(
                    f"{rel}: Relation 段「{heading}」不在 relations/ 目录，不会入图"
                    "（如需入图请移入 relations/；否则请显式声明「不入图」）")

    # 24 号（目录收拢）：原 `_check_domain_section_type` 域白名单已删除——
    # `symptom` / `class` 段类型随目录收拢一并退役（零使用者），段类型白名单收敛为 4 种，
    # 不再需要「诊断入口专属类型」的域归属校验；诊断内容由边承载（`suspected_in` / `has_class`）。


    def _check_edge_semantics_consumers(self):
        """C-20261015-04（74 号批 S-4・R-A）：`edge_semantics.yaml` 声明的每个键都必须**有消费者**。

        为什么：反向注入实证（`plugin/tests/test_edge_semantics_injection.py`）只在**有人跑 pytest**
        时才能把「声明了但没人读」的键查出来；lint 是**门禁①**，缺前置拦截 ⇒ 「纸上公理」
        （R-1）会先落盘，再在下一次发布前被人发现。本项把它变成**门禁级 error**。

        口径：
          · 可声明面 ＝ `edge_semantics.yaml` 的顶层键（`schema` / `measured_at` 是元信息，不算）
            ＋ `walk_policy` 的四个字段；
          · 「有消费者」判据 ＝ 键名出现在 `plugin/**/*.py` 的**非整行注释**代码里
            （**排除 tests**——测试里的 tripwire 是检测器，不是消费者）；
          · 声明了却零引用 ⇒ 按 11 号规则 17「**接线或删键**」，不留无消费者的声明。
        """
        try:
            from plugin.relations import RelationTraverser
            sem = RelationTraverser.edge_semantics()
        except Exception:
            return
        if not sem:
            return  # 侧车缺失／不可解析：由别处报错，本项不重复发力
        declared = [k for k in sem if k not in ("schema", "measured_at")]
        declared += [f"walk_policy.{k}" for k in (sem.get("walk_policy") or {})]
        chunks = []
        for p in sorted(PLUGIN_ROOT.rglob("*.py")):
            if "tests" in p.parts:
                continue
            try:
                for line in p.read_text(encoding="utf-8").splitlines():
                    if line.strip().startswith("#"):
                        continue
                    chunks.append(line)
            except Exception:
                continue
        code = "\n".join(chunks)
        for key in declared:
            name = key.split(".", 1)[1] if key.startswith("walk_policy.") else key
            if name not in code:
                self.errors.append(
                    f"edge_semantics.{key}：声明的键**没有任何消费者**（plugin/**/*.py 非注释代码零引用）"
                    "——属「纸上公理」（R-1）。按 11 号规则 17：**接线或删键**，"
                    "不留无消费者的声明（判据与接线步骤见 skill/bkn/references/inference-wiring.md）")


def main():
    ap = argparse.ArgumentParser(description="BKN 质量检查")
    ap.add_argument("--error-only", action="store_true", help="只输出 error")
    ap.add_argument("--ignore", action="append", default=[], help="忽略含指定子串的条目（可重复）")
    ap.add_argument("--bkn-root", default=str(PROJECT_ROOT / "bkn"))
    ap.add_argument("--list-meta-info", action="store_true",
                    help="只列出「零冗余」机检的命中（含豁免键），用于生成 KNOWN_META_INFO")
    ap.add_argument("--list-dead-refs", action="store_true",
                    help="只列出「死指路」机检的命中（提到已退场 .bkn 文件名且非历史语境；info 级）")
    args = ap.parse_args()

    linter = Linter(Path(args.bkn_root))

    if args.list_meta_info:
        hits = linter.scan_meta_info()
        exempted = [h for h in hits if h["key"] in KNOWN_META_INFO]
        print(f"# 零冗余机检命中 {len(hits)} 处（已豁免 {len(exempted)}，未豁免 {len(hits) - len(exempted)}）")
        print("# 把下面各行粘入 lint_bkn.py 的 KNOWN_META_INFO（清一处删一条）：")
        print("KNOWN_META_INFO: dict = {")
        for h in hits:
            if h["key"] in KNOWN_META_INFO:
                continue
            print(f'    {h["key"]!r}: "待清理（{h["label"]}）",')
        print("}")
        return 0

    if args.list_dead_refs:
        hits = linter.scan_dead_refs()
        print(f"# 死指路机检命中 {len(hits)} 处（info 级；注册表见 lint_bkn.RETIRED_BKN_FILES）")
        for h in hits:
            print(f"  {h['rel']}:{h['line']}  {h['name']}  ← {h['text']}")
        return 0

    linter.run()

    def filtered(items):
        return [i for i in items if not any(ig in i for ig in args.ignore)]

    errors = filtered(linter.errors)
    warnings = filtered(linter.warnings)
    infos = filtered(linter.infos)

    print("BKN Quality Check Report")
    print("=" * 40)
    if errors:
        print(f"\nErrors ({len(errors)}):")
        for e in errors:
            print(f"  {e}")
    if not args.error_only:
        if warnings:
            print(f"\nWarnings ({len(warnings)}):")
            for w in warnings:
                print(f"  {w}")
        if infos:
            print(f"\nInfos ({len(infos)}):")
            for i in infos:
                print(f"  {i}")
    print(f"\nSummary: errors={len(errors)} warnings={len(warnings)} infos={len(infos)}")
    return 1 if errors else 0



#: 可生成的码形态（L1 负责，禁止进别名表）
_ALIAS_CODE_FORMS = (
    re.compile(r"^-?[0-9]{3,6}$"),
    re.compile(r"^错误[ ]*-?[0-9]{3,6}$"),
    re.compile(r"^(?:error|err)[ ]*-?[0-9]{3,6}$", re.IGNORECASE),
    re.compile(r"^[A-Za-z]{2,6}-?[0-9]{2,6}$"),
)


def _validate_alias_entries(entries, canonical: set) -> list:
    """校验 aliases.yaml 条目 → 错误列表（空=通过）。

    三条机检：canonical 必须已登记 / 别名键不得是可生成变体 / 必须带 provenance。
    纯函数，便于单测（别名机制 v2 的 lint 部分）。
    """
    errs = []
    for i, e in enumerate(entries or []):
        e = e or {}
        alias = str(e.get("alias") or "").strip()
        canon = str(e.get("canonical") or "").strip()
        if not alias or not canon:
            errs.append(f"aliases.yaml[{i}]: 缺 alias/canonical")
            continue
        if not e.get("provenance"):
            errs.append(f"aliases.yaml[{i}] '{alias}': 缺 provenance（来源/日期/证据）")
        if canonical and canon not in canonical:
            errs.append(f"aliases.yaml[{i}] '{alias}': canonical '{canon}' 未登记（幽灵别名）")
        if any(p.match(alias) for p in _ALIAS_CODE_FORMS):
            errs.append(f"aliases.yaml[{i}] '{alias}': 可生成变体不得入表（由 L1 生成）")
    return errs

if __name__ == "__main__":
    sys.exit(main())

