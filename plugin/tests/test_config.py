"""Tests for plugin config defaults + 无 pyyaml 时的加载纪律（2026-10-12 事故回归）。

事故：Hermes runtime 更新后缺 pyyaml → 内置 fallback 解析器把行内注释当值
（`timeout: 5  # 请求超时(秒)`）→ `int()` 在 import 顶层抛 ValueError → `register()` 从未执行
（12 Tool + RiskGuard hook 全部未注册）。本文件钉住两手加固：
  ① fallback 解析器对**真实 config.yaml** 与 pyyaml 逐键等价；
  ② 标量转换失败只回退默认 + 记 CONFIG_ERRORS，不炸 import；
  ③ 端到端：屏蔽 yaml 后子进程仍能导入插件并注册 13 个 Tool。
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import plugin.config as cfg
from plugin.config import SEARCH_DECOMPOSE_DEDUP

CONFIG_YAML = ROOT / "plugin" / "config.yaml"


class TestSearchConfig(unittest.TestCase):

    def test_decompose_dedup_is_fraction(self):
        """去重阈值必须是小数比例，不能是整数 85。"""
        self.assertIsInstance(SEARCH_DECOMPOSE_DEDUP, float)
        self.assertGreater(SEARCH_DECOMPOSE_DEDUP, 0.0)
        self.assertLess(SEARCH_DECOMPOSE_DEDUP, 1.0)


class TestFallbackParser(unittest.TestCase):
    """受限解析器必须与 pyyaml 对真实文件等价（不然就会出现事故里的静默错值）。"""

    def test_fallback_parser_matches_pyyaml_on_real_config(self):
        import yaml
        text = CONFIG_YAML.read_text(encoding="utf-8")
        self.assertEqual(cfg._fallback_yaml_load(text), yaml.safe_load(text))

    def test_inline_comments_are_stripped(self):
        """事故根因行：行内注释不得进入值；引号内的 # 不受影响。"""
        parsed = cfg._fallback_yaml_load(
            "qdrant:\n"
            "  timeout: 5                         # 请求超时(秒)\n"
            "  collection: demo_product_collection    # 主检索集合\n"
            "  token: \"a#b\"                      # 引号内 # 保留\n"
        )
        self.assertEqual(parsed["qdrant"]["timeout"], 5)
        self.assertEqual(parsed["qdrant"]["collection"], "demo_product_collection")
        self.assertEqual(parsed["qdrant"]["token"], "a#b")

    def test_nested_maps_lists_and_flow_lists(self):
        parsed = cfg._fallback_yaml_load(
            "qdrant:\n"
            "  collections:      # 列表注释\n"
            "    - name: c1\n"
            "      description: 主集合\n"
            "    - name: c2\n"
            "      description: 辅集合\n"
            "tools:\n"
            "  enabled: []\n"
            "  blend: [\"a\", \"b\"]\n"
            "  bare:\n"
        )
        self.assertEqual([c["name"] for c in parsed["qdrant"]["collections"]], ["c1", "c2"])
        self.assertEqual(parsed["qdrant"]["collections"][0]["description"], "主集合")
        self.assertEqual(parsed["tools"]["enabled"], [])
        self.assertEqual(parsed["tools"]["blend"], ["a", "b"])
        self.assertIsNone(parsed["tools"]["bare"])   # 空值 → None（与 pyyaml 一致）

    def test_key_values_consumed_by_code_are_typed(self):
        """代码实际消费的键：类型必须正确（int 才能过 _as_int）。"""
        parsed = cfg._fallback_yaml_load(CONFIG_YAML.read_text(encoding="utf-8"))
        self.assertIsInstance(parsed["qdrant"]["timeout"], int)
        self.assertIsInstance(parsed["qdrant"]["port"], int)
        self.assertIsInstance(parsed["log_rotate"]["traj_max_bytes"], int)
        self.assertIsInstance(parsed["search"]["score_threshold"], float)
        self.assertTrue(parsed["risk_guard"]["enabled"])


class TestScalarSoftening(unittest.TestCase):

    def test_as_int_falls_back_with_report(self):
        """坏值 → 默认值 + CONFIG_ERRORS 记录（不抛）。"""
        before = len(cfg.CONFIG_ERRORS)
        self.assertEqual(cfg._as_int("5  # 注释", 5), 5)
        self.assertEqual(cfg._as_int(None, 7), 7)
        self.assertEqual(cfg._as_int("abc", 3), 3)
        self.assertGreater(len(cfg.CONFIG_ERRORS), before)
        self.assertEqual(cfg._as_int("42", 0), 42)
        self.assertEqual(cfg._as_float("0.5", 0.0), 0.5)
        self.assertEqual(cfg._as_float("x", 1.5), 1.5)


class TestImportWithoutPyyaml(unittest.TestCase):

    def test_plugin_registers_thirteen_tools_without_pyyaml(self):
        """端到端回归：屏蔽 yaml → 子进程导入插件 + register() 仍注册 13 Tool。

        （`sys.modules['yaml'] = None` 让 `import yaml` 抛 ImportError，与缺库等价。）
        """
        code = (
            "import sys\n"
            "sys.modules['yaml'] = None\n"
            f"sys.path.insert(0, {str(ROOT)!r})\n"
            "import plugin\n"
            "from plugin import config\n"
            "assert config.QDRANT_TIMEOUT == 5, config.QDRANT_TIMEOUT\n"
            "assert config.LOG_ROTATE_TRAJ_MAX_BYTES == 262144\n"
            "assert any('pyyaml 不可用' in e for e in config.CONFIG_ERRORS), config.CONFIG_ERRORS\n"
            "class A:\n"
            "    def __init__(self): self.tools = []\n"
            "    def register_tool(self, **kw): self.tools.append(kw['name'])\n"
            "    def register_hook(self, *a, **k): pass\n"
            "a = A()\n"
            "plugin.register(a)\n"
            "print('TOOLS', len(a.tools))\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ)
            env["LOG_DIR"] = tmp
            env.pop("DEMO-PRODUCT_BKN_ROOT", None)
            r = subprocess.run([sys.executable, "-c", code], capture_output=True,
                               text=True, env=env, cwd=str(ROOT), timeout=180)
        self.assertEqual(r.returncode, 0, (r.stdout[-500:], r.stderr[-1500:]))
        self.assertIn("TOOLS 13", r.stdout)


if __name__ == "__main__":
    unittest.main()
