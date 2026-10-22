#!/usr/bin/env bash
# gate.sh — 单一门禁入口（22 号批 1-3）
#
# 顺序执行四道门，任一道失败即非零退出码（可被 CI 复用，见 22 号批 1-4/Q3）：
#   ① 结构门禁   lint_bkn.py --error-only        errors 必须为 0
#   ② 回归门禁   pytest plugin/tests -q          全绿（内含方向层 §7 五项阈值断言）
#   ③ 结构量门禁 graph_metrics --compare         只增不减（16 号 §5 不变量 2）
#      + ③b 版本身份 bkn_version --check        I14：内容 = 版本清单
#      + ③c 版本↔记录 changeset --check         I15（非严格形态；--strict 留发布收尾）
#   ④ 基线门禁   measure_confidence --compare    置信度/输出体积不劣化
#   ⑤ 回放门禁   m5_case_replay --check           **不许更差**（floor＝scripts/m5_replay_floor.json；
#                                                   2026-10-13 用户裁定「1 B」接线）
#   ⑥ 坑台账     check_pitfalls.py                 doc/optimize/00-pitfalls.md 格式合法
#                                                   （2026-10-22 用户要求「踩过的坑要记录」）
#
# 用法:
#   bash scripts/gate.sh              # 全跑（约 1-2 分钟，含 measurement）
#   bash scripts/gate.sh --fast       # 跳过 ④（省 1-2 分钟；用于快速迭代）
#   bash scripts/gate.sh --lint-only  # 只跑 ①（提交前最快一档）
#
# 依据: doc/optimize/22-bkn-lifecycle-gate.md §3 批 1 / §4 验收命令与通过标准
# 约束: 本脚本只读，不改任何文件（measure_confidence 自带临时 LOG_DIR，不污染生产日志）

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || exit 2

FAST=0
LINT_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --fast) FAST=1 ;;
    --lint-only) LINT_ONLY=1 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "未知参数: $arg" >&2; exit 2 ;;
  esac
done

PY="${PYTHON:-python3}"
FAILED=0
declare -a RESULTS

hr() { printf '%s\n' "------------------------------------------------------------"; }

# ---- ⓪ 待审区提醒（28 号批 R-1 挂载点；脚本不存在则跳过）--------------
if [ -f "$REPO_ROOT/scripts/pending_status.py" ]; then
  hr
  echo "⓪ 待审区（28 号）"
  if ! "$PY" scripts/pending_status.py; then
    # 提醒不是门禁：账本结构异常会由 R-1 自身报错，但此处不阻断
    echo "  ⚠ pending_status 返回非零（提醒项，不阻断门禁）"
  fi
fi

# ---- ⓪b 外面↔待审区对账（sync_audit，2026-10-12 接线；提醒项不阻断）----
# 不变量（28 号 §1 铁律 3）：候选触及的每个文件 == 最后一次落盘它的候选 payload。
# 漂移多为候选系统之外的直改——提示后按待审区流程补候选，不在此阻断。
if [ -f "$REPO_ROOT/scripts/sync_audit.py" ]; then
  hr
  echo "⓪b 待审区对账（sync_audit）"
  if ! "$PY" scripts/sync_audit.py; then
    echo "  ⚠ 检测到漂移（提醒项，不阻断门禁）——逐条见 scripts/sync_audit.py --verbose"
  fi
fi

# ---- ⓪c 轮次记录校验（26 号 I10/I11/I12；2026-10-12 接线；提醒项不阻断）----
# 每次发布都应有完整的轮次记录（候选目录 attribution.md，Q17 载体）。
if [ -f "$REPO_ROOT/scripts/round_check.py" ]; then
  hr
  echo "⓪c 轮次记录（round_check，26 号 I10/I11/I12）"
  if ! "$PY" scripts/round_check.py; then
    echo "  ⚠ 轮次记录有结构问题（提醒项，不阻断门禁）"
  fi
fi

# ---- ① 结构门禁 ------------------------------------------------------
hr
echo "① 结构门禁：lint_bkn.py --error-only"
if "$PY" plugin/scripts/lint_bkn.py --error-only; then
  RESULTS+=("✅ ① lint errors=0")
else
  RESULTS+=("❌ ① lint 有 error")
  FAILED=1
fi

if [ "$LINT_ONLY" = "1" ]; then
  hr
  printf '%s\n' "${RESULTS[@]}"
  echo "（--lint-only：已停止）"
  exit $FAILED
fi

# ---- ② 回归门禁（pytest 全量；内含方向层 §7 阈值断言）------------------
hr
echo "② 回归门禁：pytest plugin/tests -q"
if "$PY" -m pytest plugin/tests -q; then
  RESULTS+=("✅ ② pytest 全绿")
else
  RESULTS+=("❌ ② pytest 有失败")
  FAILED=1
fi

# ---- ③ 结构量门禁（只增不减）+ 版本身份（I14）-------------------------
hr
echo "③ 结构与身份门禁：graph_metrics + bkn_version"
if [ -f "plugin/baselines/graph.v3.json" ]; then
  if "$PY" plugin/scripts/graph_metrics.py --compare plugin/baselines/graph.v3.json --fail-on-regression; then
    RESULTS+=("✅ ③a 结构量只增不减")
  else
    RESULTS+=("❌ ③a 结构量减少")
    FAILED=1
  fi
else
  echo "  ⚠ 缺少 plugin/baselines/graph.json，跳过（先跑：$PY plugin/scripts/graph_metrics.py --out plugin/baselines/graph.json）"
  RESULTS+=("⚠ ③a 跳过（无基线）")
fi

if [ -f "bkn-version.json" ]; then
  if "$PY" scripts/bkn_version.py --check; then
    RESULTS+=("✅ ③b 版本身份与内容一致（I14）")
  else
    RESULTS+=("❌ ③b 本体已改但版本未升级——跑 scripts/bkn_version.py --write")
    FAILED=1
  fi
else
  echo "  ⚠ 缺少 bkn-version.json，跳过（先跑：$PY scripts/bkn_version.py --write）"
  RESULTS+=("⚠ ③b 跳过（无版本文件）")
fi

if [ -f "scripts/changeset.py" ]; then
  # I15 的门禁形态：只查「已有锚行合法/唯一/不倒挂」+ changeset_ref 可解——**不要求当前版本有锚行**。
  # 原因：pending_apply 落盘时自动升版，若这里要求锚行，任何改 .bkn 的候选都会
  # "升版 → 无锚行 → 门禁红 → 回滚"（与 I14 的死锁同类，见 27 号 §3）。
  # "当前版本必须有锚行" 只在发布收尾跑：python3 scripts/changeset.py --check --strict
  if "$PY" scripts/changeset.py --check; then
    RESULTS+=("✅ ③c 版本↔记录对账（I15）")
  else
    RESULTS+=("❌ ③c changeset 对账失败——见上；发布收尾须 --check --strict")
    FAILED=1
  fi
fi

# ---- ④ 基线门禁（置信度/输出体积不劣化）-------------------------------
if [ "$FAST" = "1" ]; then
  hr
  echo "④ 基线门禁：--fast 跳过"
  RESULTS+=("⚠ ④ 跳过（--fast）")
else
  hr
  echo "④ 基线门禁：measure_confidence --compare（约 1-2 分钟）"
  # 门禁现用 v7（C-20261013-14 另立：50 例 / 13 Tool）；v6 由 C-20261012-13 另立、v5 由 C-20261012-12 另立（均 48 例），v4 由 22 号批 4-3（扩 12 Tool／48 例）另立；v3 保留为批 4 前的对照，v2 为 C-04 前，v1 为 C-20261010-01 前
  BASELINE="plugin/baselines/measure_confidence.v7.json"
  [ -f "$BASELINE" ] || BASELINE="plugin/baselines/measure_confidence.v3.json"
  [ -f "$BASELINE" ] || BASELINE="plugin/baselines/measure_confidence.v2.json"
  [ -f "$BASELINE" ] || BASELINE="plugin/baselines/measure_confidence.json"
  if [ -f "$BASELINE" ]; then
    echo "  基线：$BASELINE"
    if "$PY" plugin/scripts/measure_confidence.py \
        --out /tmp/gate_measure_after.json --label gate-after \
        --compare "$BASELINE" --fail-on-regression; then
      RESULTS+=("✅ ④ 置信度/体积无劣化（含逐用例对比）")
    else
      RESULTS+=("❌ ④ 检测到劣化（含逐用例下降 >10%）")
      FAILED=1
    fi
  else
    echo "  ⚠ 缺少 plugin/baselines/measure_confidence*.json，跳过"
    RESULTS+=("⚠ ④ 跳过（无基线）")
  fi
fi

# ---- ⑤ 回放门禁（29 号 M-5；2026-10-13 裁定「1 B」接线）------------------
# 判据＝**不许更差**（不做目标阈值）：跑 4 案例回放，逐指标对照 floor。
# 口径与两处已知偏差（routing 的 Q27 契约变更、honest_unknown 定义过期）见 43 号 §19。
hr
echo "⑤ 回放门禁：m5_case_replay --check（不许更差）"
if "$PY" scripts/m5_case_replay.py --check; then
  RESULTS+=("✅ ⑤ 回放 floor 无退步")
else
  RESULTS+=("❌ ⑤ 回放 floor 出现退步（见上）")
  FAILED=1
fi

# ---- ⑥ 踩坑台账格式（2026-10-22）------------------------------------------
# 目的：坑不记就会再踩。只校验格式（编号唯一递增、七列非空），内容靠评审。
hr
echo "⑥ 踩坑台账：check_pitfalls.py"
if [ ! -f "$REPO_ROOT/scripts/check_pitfalls.py" ]; then
  echo "  跳过（无台账脚本）"
  RESULTS+=("✅ ⑥ 坑台账跳过（无脚本）")
elif "$PY" scripts/check_pitfalls.py; then
  RESULTS+=("✅ ⑥ 坑台账格式合法")
else
  RESULTS+=("❌ ⑥ 坑台账格式不合法（见上）")
  FAILED=1
fi

# ---- 汇总 ------------------------------------------------------------
hr
echo "门禁汇总"
for r in "${RESULTS[@]}"; do
  echo "  $r"
done
hr
if [ "$FAILED" = "0" ]; then
  echo "✅ 全部门禁通过"
else
  echo "❌ 门禁未通过（见上）"
fi
exit $FAILED
