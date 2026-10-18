#!/usr/bin/env python3
"""sync_from_internal.py — 把内部工程仓的绿名单代码单向同步到本仓（默认 dry-run）。

规定见 MAINTAINING.md：只同步运行时（plugin/*.py、*.yaml、baselines、scripts/）、通用 skill（skill/bkn*）、
本体骨架（SCHEMA/SYNONYMS/SKILL/templates/prerequisites）；同步时按 REWRITES 去产品化；
结束跑四道闸（双根 lint、pytest、redact、内部引用扫描）。
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

DEST = Path(__file__).resolve().parents[1]
WHITELIST = [
    "plugin/*.py",
    "plugin/*.yaml",
    "plugin/baselines/*.json",
    "plugin/scripts",
    "scripts",
    "skill/bkn*",
]
EXCLUDE = {"plugin/skill_manifest.yaml", "plugin/config.yaml"}
#: OSS 侧手工改写过、不再接受同步覆盖的文件（改这里要同步在 MAINTAINING.md 记一行）
LOCAL_OVERRIDES = {"skill/bkn-intake/references/preprocessing.md"}
SKIP_PARTS = {"__pycache__", ".pytest_cache", ".git", "node_modules", "logs"}
SKIP_SUFFIX = {".pyc", ".pyo", ".log"}
REWRITES = [
    ("/hdd/demo/public/i2stream-bkn", "<repo>"),
    ("/hdd/demo/bkn-engineering", "<opbkn-repo>"),
    ("/hdd/demo/.shadow", "<tmp>"),
    ("/hdd/demo", "<data>"),
    ("/root/.hermes", "~/.hermes"),
    ("<local-path>", "<repo>"),
    ("i2Stream", "Demo Product"),
    ("I2STREAM", "DEMO-PRODUCT"),
    ("i2stream", "demo-product"),
    ("I2UP_API_HOST", "DEMO_CONSOLE_API_HOST"),
    ("I2Stream", "Demo Product"),
    ("i2UP", "Demo Console"),
    ("i2up", "demo-console"),
]
IP = re.compile(r"(?<![0-9])(?:10|192\.168|172\.(?:1[6-9]|2[0-9]|3[01]))\.([0-9]{1,3})\.([0-9]{1,3})")
BUG = re.compile(r"BUG-(?=[0-9]{4})")
CHANGELOG_PTR = re.compile(r"doc/build/demo[-_]product[-_]bkn/90-history/bkn-changelog[.]md")


def _iter(root: Path, rel: str):
    if "*" in rel:
        for hit in sorted(root.glob(rel)):
            yield from _iter(root, hit.relative_to(root).as_posix())
        return
    target = root / rel
    if target.is_symlink() or not target.exists():
        return
    if target.is_file():
        yield target
        return
    for f in sorted(target.rglob("*")):
        r = f.relative_to(root).as_posix()
        if f.is_symlink() or not f.is_file() or r in EXCLUDE:
            continue
        if any(part in SKIP_PARTS for part in f.parts) or f.suffix.lower() in SKIP_SUFFIX:
            continue
        yield f


def _rewrite(text: str, suffix: str = "") -> str:
    for a, b in REWRITES:
        text = text.replace(a, b)
    text = CHANGELOG_PTR.sub("CHANGELOG.md", text)
    if suffix == ".py":
        text = text.replace("demo-product", "demo_product")
    text = IP.sub(lambda m: "192.0.2." + m.group(2), text)
    return BUG.sub("CASE-", text)


def _collect(src: Path) -> dict:
    out = {}
    for rel in WHITELIST:
        for f in _iter(src, rel):
            r = f.relative_to(src).as_posix()
            if r.startswith("plugin/tests/") or r in EXCLUDE or r in LOCAL_OVERRIDES:
                continue
            out[r] = _rewrite(f.read_text(encoding="utf-8", errors="ignore"), f.suffix.lower())
    return out


def _verify() -> int:
    py = sys.executable
    steps = [
        ("lint 骨架", [py, "-m", "plugin.scripts.lint_bkn", "--error-only", "--bkn-root", "bkn"]),
        ("lint 示例", [py, "-m", "plugin.scripts.lint_bkn", "--error-only", "--bkn-root", "examples/example-product/bkn"]),
        ("pytest", [py, "-m", "pytest", "-q"]),
        ("redact", [py, "tools/redact.py", "--root", ".", "--report", "/tmp/redact-sync.md"]),
    ]
    rc = 0
    for name, cmd in steps:
        r = subprocess.run(cmd, cwd=str(DEST), capture_output=True, text=True)
        ok = r.returncode == 0
        print("  [%s] %s (rc=%d)" % (name, "OK" if ok else "FAIL", r.returncode))
        if not ok:
            rc = 1
            print(((r.stdout or "") + (r.stderr or ""))[-1200:])
    baseline = set()
    bl = DEST / "tools" / "internal-refs-baseline.txt"
    if bl.is_file():
        baseline = {l.strip() for l in bl.read_text(encoding="utf-8").splitlines() if l.strip()}
    bad = []
    for f in DEST.rglob("*"):
        if f.is_symlink() or not f.is_file() or any(p in SKIP_PARTS for p in f.parts):
            continue
        if f.suffix.lower() not in {".md", ".py", ".yaml", ".bkn", ".toml"}:
            continue
        t = f.read_text(encoding="utf-8", errors="ignore")
        if "doc/optimize/" in t or "/hdd/demo" in t or "doc/build/demo" in t:
            bad.append(f.relative_to(DEST).as_posix())
    new_bad = [b for b in bad if b not in baseline]
    print("  [内部引用] %s（已知债务 %d，新增 %d）" % ("OK" if not new_bad else "FAIL", len(bad) - len(new_bad), len(new_bad)))
    for b in new_bad[:30]:
        print("    ", b)
    return 1 if (rc or new_bad) else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--prune", action="store_true")
    ap.add_argument("--yes", action="store_true")
    a = ap.parse_args()
    src = Path(a.source).resolve()
    if not (src / "plugin").is_dir():
        print("源目录不像内部仓：%s" % src)
        return 2
    want = _collect(src)
    added, changed = [], []
    for r, text in sorted(want.items()):
        dst = DEST / r
        if not dst.is_file():
            added.append(r)
        elif dst.read_text(encoding="utf-8", errors="ignore") != text:
            changed.append(r)
        if a.apply:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(text, encoding="utf-8")
    pruned = []
    if a.prune:
        if not a.yes:
            print("拒绝删除：--prune 需同时给 --yes")
            return 2
        for rel in WHITELIST:
            for f in _iter(DEST, rel):
                r = f.relative_to(DEST).as_posix()
                if r.startswith("plugin/tests/") or r in want or r in LOCAL_OVERRIDES:
                    continue
                pruned.append(r)
                if a.apply:
                    f.unlink()
    print("新增 %d ｜ 改动 %d ｜ 删除 %d ｜ 同步集 %d ｜ 本地豁免 %d"
          % (len(added), len(changed), len(pruned), len(want), len(LOCAL_OVERRIDES)))
    for label, rows in (("新增", added), ("改动", changed), ("删除", pruned)):
        for r in rows[:40]:
            print("  [%s] %s" % (label, r))
    if not a.apply:
        print("\n(dry-run) 未写入；确认后加 --apply")
        return 0
    return _verify()


if __name__ == "__main__":
    raise SystemExit(main())
