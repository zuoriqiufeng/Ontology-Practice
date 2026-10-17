"""示例本体的冒烟测试：lint 必须干净，解析器必须能加载。"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _lint(root: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "plugin.scripts.lint_bkn", "--error-only", "--bkn-root", root],
        cwd=str(ROOT), capture_output=True, text=True,
    )


def test_skeleton_lints_clean():
    r = _lint("bkn")
    assert r.returncode == 0, (r.stdout or "") + (r.stderr or "")


def test_example_ontology_lints_clean():
    r = _lint("examples/example-product/bkn")
    assert r.returncode == 0, (r.stdout or "") + (r.stderr or "")


def test_example_ontology_loads():
    from plugin.resolver import BKNResolver

    res = BKNResolver(bkn_root=str(ROOT / "examples" / "example-product" / "bkn"))
    keys = list(res.cache)
    assert any("worknode" in k for k in keys), keys[:5]

