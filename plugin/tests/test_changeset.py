"""changeset 对账（27 号批 V-4；不变量 I15）。

守四件事：

1. 版本锚行必须**恰好含一个**版本号（`- **版本**：bkn-YYYYMMDD-N`，后可跟一句说明）；
2. 锚行唯一、且不得**晚于**当前版本（版本倒挂）；
3. 「当前版本必须有锚行」**只在 `--strict` 强制**——门禁形态不能要求它：
   `pending_apply` 落盘时会自动升版，若门禁要求锚行，任何改 `.bkn` 的候选都会
   "升版 → 无锚行 → 门禁红 → 回滚"（与 I14 的死锁同类，见 27 号 §3）；
4. `changeset_ref` 指向的候选必须存在且 `status=applied`。
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import changeset as cs  # noqa: E402


def _write_version(root: Path, version_id: str, ref: str = "") -> None:
    (root / "bkn-version.json").write_text(json.dumps({
        "version_id": version_id, "version_hash": "x", "changeset_ref": ref,
    }, ensure_ascii=False), encoding="utf-8")


class TestAnchorRules(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.log = self.root / "changelog.md"
        self._patches = [
            mock.patch.object(cs, "REPO_ROOT", self.root),
            mock.patch.object(cs, "CHANGELOG", self.log),
            mock.patch.object(cs, "PENDING_DIR", self.root / "pending"),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmp.cleanup()

    def _changelog(self, *lines: str) -> None:
        self.log.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_happy_path_allows_trailing_note(self):
        _write_version(self.root, "bkn-20261010-2")
        self._changelog("## 2026-10-10 — 某事", "- **版本**：bkn-20261010-2（含两次落盘）")
        self.assertEqual(cs.cmd_check(strict=True), 0)

    def test_anchor_with_two_versions_rejected(self):
        _write_version(self.root, "bkn-20261010-2")
        self._changelog("## 条目", "- **版本**：bkn-20261010-2，另见 bkn-20261010-1")
        self.assertEqual(cs.cmd_check(strict=False), 1)

    def test_duplicate_anchor_rejected(self):
        _write_version(self.root, "bkn-20261010-2")
        self._changelog("## 甲", "- **版本**：bkn-20261010-1", "## 乙", "- **版本**：bkn-20261010-1")
        self.assertEqual(cs.cmd_check(strict=False), 1)

    def test_anchor_ahead_of_current_rejected(self):
        _write_version(self.root, "bkn-20261010-1")
        self._changelog("## 条目", "- **版本**：bkn-20261010-2")
        self.assertEqual(cs.cmd_check(strict=False), 1)

    def test_previous_version_without_anchor_passes_gate_form(self):
        """门禁形态只查"已有锚行"，不要求当前版本有锚行（apply 升版后的合法中间态）。"""
        _write_version(self.root, "bkn-20261010-2")
        self._changelog("## 上一版", "- **版本**：bkn-20261010-1")
        self.assertEqual(cs.cmd_check(strict=False), 0)
        self.assertEqual(cs.cmd_check(strict=True), 1)

    def test_changeset_ref_candidate_status_checked_only_in_strict(self):
        """候选 `status` 只在 strict 检查：apply 的复验门跑在 status 改写**之前**，
        门禁形态若要求 `applied`，任何候选都会"落盘 → 门禁红 → 回滚"。"""
        cand = self.root / "pending" / "C-20261010-90"
        cand.mkdir(parents=True)
        _write_version(self.root, "bkn-20261010-1", ref="候选人 C-20261010-90")
        self._changelog("## 条目", "- **版本**：bkn-20261010-1")
        (cand / "candidate.json").write_text('{"status": "pending"}', encoding="utf-8")
        self.assertEqual(cs.cmd_check(strict=False), 0)     # 门禁形态：只看存在
        self.assertEqual(cs.cmd_check(strict=True), 1)      # 发布收尾：要求 applied
        (cand / "candidate.json").write_text('{"status": "applied"}', encoding="utf-8")
        self.assertEqual(cs.cmd_check(strict=False), 0)
        self.assertEqual(cs.cmd_check(strict=True), 0)

    def test_changeset_ref_missing_candidate_rejected(self):
        _write_version(self.root, "bkn-20261010-1", ref="候选人 C-20261010-99")
        self._changelog("## 条目", "- **版本**：bkn-20261010-1")
        self.assertEqual(cs.cmd_check(strict=False), 1)


class TestRealRepo(unittest.TestCase):
    def test_gate_form_passes_on_repo(self):
        """真仓库烟测：**门禁形态**必须过。

        刻意不断言 `--strict`——测试套件本身跑在 `pending_apply` 的复验门里，
        而 apply 刚升版时锚行必然还没写（那是发布收尾的事）：断言 strict 会让
        每个改 `.bkn` 的候选在复验时失败并回滚。
        """
        self.assertEqual(cs.cmd_check(strict=False), 0)
