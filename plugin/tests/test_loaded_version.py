"""批 V-1 × U-2：服务自证与一致性检查测试（27 号 §2.3 / I16）。

覆盖：register() 写自证（字段/hash 与算法一致）、BKN 根不可用时的优雅降级、
check_loaded_version 的三态退出码（0 一致 / 1 不一致 / 2 无记录或降级）。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCRIPTS = ROOT / "scripts"          # 版本算法单点（bkn_version.py）
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
PLUGIN_SCRIPTS = ROOT / "plugin" / "scripts"   # check_loaded_version.py
if str(PLUGIN_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(PLUGIN_SCRIPTS))

import bkn_version as bv  # noqa: E402
from plugin import config, loaded_version  # noqa: E402
import check_loaded_version as clv  # noqa: E402


def _make_bkn_root(base: Path) -> Path:
    root = base / "bkn"
    (root / "objects").mkdir(parents=True)
    (root / "objects" / "a.bkn").write_text("x\n", encoding="utf-8")
    (root / "SKILL.md").write_text("y\n", encoding="utf-8")
    return root


class TestLoadedVersion(unittest.TestCase):

    def test_register_writes_attestation(self):
        """register() → logs/.loaded_version.json：trigger/process/hash 与算法一致。"""
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            root = _make_bkn_root(tmpdir)
            lv = tmpdir / ".loaded_version.json"
            with mock.patch.object(loaded_version, "LOADED_VERSION_FILE", lv), \
                 mock.patch.object(config, "BKN_ROOT", str(root)):
                rec = loaded_version.attest_loaded_version("register")
            self.assertIsNotNone(rec)
            saved = json.loads(lv.read_text(encoding="utf-8"))
            self.assertEqual(saved["trigger"], "register")
            self.assertEqual(saved["process"], os.getpid())
            expect = bv.version_hash(bv.manifest_for(root, "bkn"))
            self.assertEqual(saved["version_hash"], expect)
            self.assertIsNone(saved.get("hash_error"))
            self.assertEqual(saved["bkn_root"], str(root))

    def test_root_missing_degrades_gracefully(self):
        """BKN 根不可用 → 仍写记录但带 hash_error（检查脚本据此报 2，而不是假一致）。"""
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            lv = tmpdir / ".loaded_version.json"
            with mock.patch.object(loaded_version, "LOADED_VERSION_FILE", lv), \
                 mock.patch.object(config, "BKN_ROOT", str(tmpdir / "nope")):
                rec = loaded_version.attest_loaded_version("register")
            self.assertIsNotNone(rec)
            self.assertIn("hash_error", rec)
            self.assertIsNone(rec["version_hash"])

    def test_register_hook_invokes_attestation(self):
        """真实 register() 路径：注册 Tool 后落自证（FakeApi 驱动）。"""
        class FakeApi:
            def __init__(self):
                self.tools = []

            def register_tool(self, **kw):
                self.tools.append(kw["name"])

            def register_hook(self, name, fn):
                pass

        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            root = _make_bkn_root(tmpdir)
            lv = tmpdir / ".loaded_version.json"
            api = FakeApi()
            with mock.patch.object(loaded_version, "LOADED_VERSION_FILE", lv), \
                 mock.patch.object(config, "BKN_ROOT", str(root)):
                import plugin
                plugin.register(api)
            self.assertEqual(len(api.tools), 15)  # 本轮新增 bkn_ask/check_plan
            self.assertTrue(lv.is_file(), "register() 应写服务自证")
            self.assertEqual(json.loads(lv.read_text(encoding="utf-8"))["trigger"], "register")

    def test_check_exit_codes(self):
        """三态 + 内容漂移：一致 0 / 磁盘已改未加载 1 / 无记录 2 / 自证降级 2。

        三方比对（A 进程加载 / B 磁盘现状重算 / C 版本记录）：
        `check(loaded, version_file, bkn_root)` 里 B 由临时 BKN 根重算。
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            root = _make_bkn_root(tmpdir)
            good_hash = bv.version_hash(bv.manifest_for(root, "bkn"))
            vf = tmpdir / "bkn-version.json"
            vf.write_text(json.dumps({"version_id": "bkn-x-1", "version_hash": good_hash,
                                      "released_at": "2026-10-12T00:00:00+00:00"}),
                          encoding="utf-8")
            loaded = tmpdir / "lv.json"
            # 无记录 → 2
            self.assertEqual(clv.check(loaded, vf, root), 2)
            # 一致（A == B == C）→ 0
            loaded.write_text(json.dumps({"process": 1, "loaded_at": "x", "trigger": "register",
                                          "version_hash": good_hash, "version_id": "bkn-x-1"}),
                              encoding="utf-8")
            self.assertEqual(clv.check(loaded, vf, root), 0)
            # 磁盘已改、进程未加载（A != B；B == C，即已升版后的新常态）→ 1
            (root / "objects" / "a.bkn").write_text("changed\n", encoding="utf-8")
            new_hash = bv.version_hash(bv.manifest_for(root, "bkn"))
            vf.write_text(json.dumps({"version_id": "bkn-x-2", "version_hash": new_hash,
                                      "released_at": "2026-10-12T01:00:00+00:00"}),
                          encoding="utf-8")
            self.assertEqual(clv.check(loaded, vf, root), 1)
            # 磁盘内容改了但**未升版**（A == C != B）→ 1（旧实现会漏报，本测试钉住）
            vf.write_text(json.dumps({"version_id": "bkn-x-1", "version_hash": good_hash,
                                      "released_at": "2026-10-12T00:00:00+00:00"}),
                          encoding="utf-8")
            self.assertEqual(clv.check(loaded, vf, root), 1)
            # 自证降级（hash_error）→ 2
            loaded.write_text(json.dumps({"process": 1, "loaded_at": "x", "trigger": "register",
                                          "version_hash": None, "hash_error": "FileNotFoundError: x"}),
                              encoding="utf-8")
            self.assertEqual(clv.check(loaded, vf, root), 2)


if __name__ == "__main__":
    unittest.main()
