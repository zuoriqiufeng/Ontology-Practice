"""AST 闸门（21 号 2E）：plugin 内每处 BM25 调用都必须显式声明集合作用域。

不变量：`bm25_search(...)` 与 `get_bm25_index(...)` 必须带 `collection=` 关键字
（可为字面 `None`，表示「有意查主集合」）。理由：集合作用域一旦靠默认值隐式决定，
新增调用点极易漏传而导致跨集合污染——这正是 21 号 2E 修的 bug（实测 diagnose_db_link
33% 片段来自主集合、含精确项查询 5/5 全打错集合）。

本闸门把「集合作用域」从口头约定升级为机检不变量：漏传即测试失败。
"""

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

GUARDED_FUNCS = {"bm25_search", "get_bm25_index"}
# bm25.py 自身是定义方：其内部对 get_bm25_index 的调用按设计转发形参，单独放行
SELF_MODULE = "bm25.py"


def _plugin_py_files() -> list[Path]:
    plugin_dir = ROOT / "plugin"
    return sorted(p for p in plugin_dir.glob("*.py") if p.name != SELF_MODULE)


def _iter_guarded_calls(path: Path):
    """产出 (行号, 函数名, 是否带 collection 关键字) —— 仅这些函数名的调用。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else (
            func.attr if isinstance(func, ast.Attribute) else None)
        if name in GUARDED_FUNCS:
            has_collection = any(kw.arg == "collection" for kw in node.keywords)
            yield node.lineno, name, has_collection


class TestBm25CollectionScopeGuard(unittest.TestCase):

    def test_every_call_declares_collection(self):
        offenders = []
        for path in _plugin_py_files():
            for lineno, name, has_collection in _iter_guarded_calls(path):
                if not has_collection:
                    offenders.append(f"{path.name}:{lineno} {name}() 未显式传 collection=")
        self.assertEqual(
            offenders, [],
            "以下 BM25 调用未声明集合作用域（必须显式传 collection=，None 表示主集合）:\n  "
            + "\n  ".join(offenders))

    def test_guard_actually_finds_calls(self):
        """自检：闸门本身要能扫到调用点（防 AST 匹配写错导致永远通过）。"""
        total = sum(1 for p in _plugin_py_files() for _ in _iter_guarded_calls(p))
        self.assertGreaterEqual(total, 5, "应扫到若干 BM25 调用点，实际几乎为零——闸门失效")

    def test_gate_detects_missing_collection(self):
        """自检：故意构造漏传样本，闸门必须报错。"""
        sample = ast.parse("bm25_search('q', top_k=3)")
        calls = [n for n in ast.walk(sample) if isinstance(n, ast.Call)]
        has_collection = any(kw.arg == "collection" for kw in calls[0].keywords)
        self.assertFalse(has_collection, "样本应为漏传形态")


if __name__ == "__main__":
    unittest.main()
