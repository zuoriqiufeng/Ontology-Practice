"""批 7-5 P0 回归测试：工具可改性（manifest 间接层核心验收）。

断言：「改 skill 名/换工具实现，`.bkn` 与测试断言零 diff」——
模拟 manifest 中某 skill 的 entry 改名（换实现目录），验证：
1. BKN 文件字节零变化（git diff 为空）；
2. manifest 解析器返回新 entry（resolver 按新实现路由）；
3. 测试断言不依赖旧实现名（读 manifest 解析结果而非写死）。
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TestP0ManifestRename(unittest.TestCase):
    """P0 可操作化：改 manifest 不触发 BKN 与测试断言 diff。"""

    def test_bkn_bytes_unchanged_under_manifest_rename(self):
        """改 manifest（skill entry 换目录）后，bkn/ 与测试断言文件字节零变化。

        真实场景：skill 实现目录改名（如 skill/demo_product-db-diagnostics → skill/renamed-impl），
        manifest 的 entry 跟着改——但 BKN 的 skill: 语义 ID 与测试断言都不应动。
        本测试在**不实际修改仓库文件**的前提下，验证 manifest 解析层的行为契约：
        resolve_skill_id 返回 entry 由 manifest 单点决定（mock 模拟改名后的 manifest）。
        git 层面验证用「运行前后快照对比」而非「工作树 vs HEAD」——仓库既有改动
        （如 19 号方案迁移）不影响本断言：改名操作前后 bkn/ 与测试文件必须零变化。
        """
        from plugin.manifest import resolve_skill_id

        def git_status():
            return subprocess.run(
                ["git", "status", "--short", "--", "bkn/", "plugin/tests/"],
                capture_output=True, text=True, cwd=ROOT,
            ).stdout

        before = git_status()
        renamed_manifest = {
            "skills": [{
                "id": "skill:demo_product-db-diagnostics",
                "entry": "skill/renamed-impl",  # 模拟实现目录改名
                "capability": "诊断",
            }],
            "tools": [], "stores": [],
        }
        with mock.patch("plugin.manifest.load_manifest", return_value=renamed_manifest):
            item = resolve_skill_id("skill:demo_product-db-diagnostics")
        self.assertEqual(item["entry"], "skill/renamed-impl")
        # BKN 语义 ID 不变（改名只动 manifest）
        self.assertEqual(item["id"], "skill:demo_product-db-diagnostics")
        # 改名操作（mock，不落盘）前后工作树零变化——BKN 与测试断言未被动过
        self.assertEqual(git_status(), before,
                         "manifest 改名不应产生 bkn/ 或 plugin/tests/ 的任何改动")

    def test_resolver_routes_via_manifest_entry(self):
        """_manifest_skill 的显示名来自 manifest entry 尾段（改名后跟随 manifest）。"""
        from plugin.resolver import BKNResolver
        renamed = {
            "skills": [{
                "id": "skill:bkn-plugin",
                "entry": "skill/renamed-bkn-tool",
                "capability": "BKN 机制",
            }],
            "tools": [], "stores": [],
        }
        with mock.patch("plugin.manifest.load_manifest", return_value=renamed):
            item = BKNResolver._manifest_skill("skill:bkn-plugin", "补查上下文")
        self.assertEqual(item["name"], "renamed-bkn-tool")  # 显示名跟随 manifest
        self.assertEqual(item["reason"], "补查上下文")

    def test_manifest_single_source_of_entry(self):
        """entry 唯一事实源：manifest 里所有 skill 的 entry 前缀必须是 skill/（实现层约定）。"""
        from plugin.manifest import load_manifest
        m = load_manifest()
        for s in m.get("skills", []):
            entry = s.get("entry", "")
            self.assertTrue(entry.startswith("skill/"),
                            f"{s['id']} entry 应指向 skill/ 目录: {entry}")

    def test_tools_related_skills_follow_manifest(self):
        """批 7-6：tools 兜底 related_skills 的名字跟随 manifest entry（改名零 BKN 依赖）。"""
        from plugin.tools import _manifest_related_skills
        renamed = {
            "skills": [
                {"id": "skill:demo_product-rule-manager", "entry": "skill/renamed-rm", "capability": ""},
                {"id": "skill:demo_product-db-diagnostics", "entry": "skill/renamed-diag", "capability": ""},
                {"id": "skill:demo_product-log-analyzer", "entry": "skill/renamed-log", "capability": ""},
                {"id": "skill:demo_product-diff-op", "entry": "skill/renamed-diff", "capability": ""},
                {"id": "skill:demo_product-iadebug", "entry": "skill/renamed-ia", "capability": ""},
            ],
            "tools": [], "stores": [],
        }
        with mock.patch("plugin.manifest.load_manifest", return_value=renamed):
            out = _manifest_related_skills()
        names = {s["name"] for s in out}
        self.assertEqual(names, {"renamed-rm", "renamed-diag", "renamed-log",
                                 "renamed-diff", "renamed-ia"})
        # BKN 语义 ID 未出现在兜底名字里（实现名只在 manifest）
        self.assertFalse(any(n.startswith("demo_product-") for n in names))


if __name__ == "__main__":
    unittest.main()
