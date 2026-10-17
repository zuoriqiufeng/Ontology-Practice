#!/usr/bin/env python3
"""verify_db_coverage.py — 业务数据库注册覆盖验证（可重复执行）

固化于 2026-09-10：验证「业务支持数据库清单」在 BKN 体系中的注册完整性，
覆盖 constants 注册点、别名归一、check_compatibility 本体判定与值委托指针、lint、全量回归。
（23 号方案：版本表/对象兼容等值数据已下延 Skill，脚本校验本体判定 + 指针完整性。）

用法:
  cd <repo>
  python3 plugin/scripts/verify_db_coverage.py            # 全量验证
  python3 plugin/scripts/verify_db_coverage.py --fast     # 跳过全量 pytest

新增数据库时: 在下方 BIZ_DBS 清单加一行, 再跑本脚本即可确认全链路注册到位。
退出码: 0 = 全部通过; 1 = 有失败项
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ── 业务实际支持数据库清单 (2026-09-10 核实, 大小写不敏感去重后 18 库) ──
BIZ_DBS = [
    "PostgreSQL", "GoldenDB", "TDSQL", "磐维DB", "Datahub", "DWS",
    "PolarDB-X", "PolarDB-pg", "Oracle", "MySQL", "Doris", "Kafka",
    "MogDB", "VastBase", "OceanBase@MySQL", "ClickHouse",
    "Tdsql for pg", "AnalyticDB",
]

# 业务写法变体 → 规范名 的关键别名断言（防止别名表被误删）
KEY_ALIAS_CASES = [
    ("panwei", "磐维DB"),
    ("oceanbase@mysql", "OceanBase"),
    ("tdsql for pg", "TDSQL"),
    ("adb", "AnalyticDB"),
]

# 需 check_compatibility 给出本体判定 + 下延指针的库（大数据/数据平台豁免）
SOURCE_VERSION_CHECKED = [
    "MogDB", "PolarDB-X", "PolarDB-pg", "ClickHouse", "DWS", "AnalyticDB",
]

fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        fails.append(name)


def main() -> int:
    ap = argparse.ArgumentParser(description="业务数据库注册覆盖验证")
    ap.add_argument("--fast", action="store_true", help="跳过全量 pytest 回归")
    args = ap.parse_args()

    from plugin.constants import KNOWN_DBS, DB_ALIASES, is_db_match
    from plugin.resolver import BKNResolver

    # 1. 业务清单全部归一化
    unresolved = [
        e for e in BIZ_DBS
        if not any(is_db_match(e, k) or is_db_match(k, e) for k in KNOWN_DBS)
        and not any(is_db_match(e, v) for v in DB_ALIASES.values())
    ]
    check(f"业务清单 {len(BIZ_DBS)} 库全部归一到 KNOWN_DBS", not unresolved, f"未解析: {unresolved}")

    # 2. 关键别名断言
    for alias, canonical in KEY_ALIAS_CASES:
        check(f"别名 {alias}→{canonical}", is_db_match(alias, canonical))
    check("别名值全部可归一（lint 同判据）",
          all(any(is_db_match(v, k) for k in KNOWN_DBS) for v in DB_ALIASES.values()))

    # 3. check_compatibility：本体判定（注册集）+ 值委托指针（23 号方案）
    r = BKNResolver()
    for db in SOURCE_VERSION_CHECKED:
        res = r.check_compatibility(db, "MySQL")
        check(f"check_compatibility({db}) supported", res["supported"])
        check(f"check_compatibility({db}) 带下延指针",
              bool(res.get("delegated_to")) and all(
                  d.get("id", "").startswith("skill:") for d in res.get("delegated_to", [])))

    # 3b. DELEGATIONS 全表指针可加载性（2026-09-24 落点重映射后新增）：
    #     每个值委托指针必须指向**真实存在的文件**（skill:<id>/<path>），防死指针。
    from plugin.resolver import DELEGATIONS
    for key, d in sorted(DELEGATIONS.items()):
        sid, rel_path = d.get("id", ""), d.get("path", "")
        f = PROJECT_ROOT / "skill" / sid.split(":", 1)[-1] / rel_path
        check(f"DELEGATIONS[{key}] 指针文件存在", bool(sid and rel_path) and f.exists(),
              f"{sid}/{rel_path}")

    # 4. lint db-coverage
    out = subprocess.run(
        [sys.executable, "plugin/scripts/lint_bkn.py"],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True,
    ).stdout
    summary = out.split("Summary:")[-1].strip()
    check("lint db-coverage errors=0", summary.startswith("errors=0"), summary)

    # 5. 全量回归
    if not args.fast:
        r1 = subprocess.run(
            [sys.executable, "-m", "pytest", "plugin/tests/", "-q"],
            cwd=str(PROJECT_ROOT), capture_output=True, text=True,
        )
        tail = r1.stdout.strip().splitlines()[-1] if r1.stdout.strip() else r1.stderr[-300:]
        check("全量 pytest plugin/tests/", r1.returncode == 0, tail)

    print("\n=== RESULT:", "ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}", "===")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
