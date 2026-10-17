"""pending_apply 的 payload 语义（27 号批 V-4 修掉的缺陷）。

`payload/.pre-apply/` 是落盘前的**原件备份**（本脚本自己写的），**不是候选内容**。
早期 `collect_payload` 没排除它，后果：落盘过（或回滚过）的候选再被 apply 时，
payload 文件数翻倍、算出的 hash 与账本对不上 → 被"正确地"拒绝，但报错会
误导成"审批哈希写错了"。这里把它钉住。
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import pending_apply as pa  # noqa: E402


def _make_candidate(tmp: Path, with_pre_apply: bool) -> Path:
    cand = tmp / "C-20261010-90"
    (cand / "payload" / "bkn" / "objects").mkdir(parents=True)
    (cand / "payload" / "bkn" / "objects" / "host.bkn").write_text("new\n", encoding="utf-8")
    if with_pre_apply:
        backup = cand / "payload" / ".pre-apply" / "bkn" / "objects"
        backup.mkdir(parents=True)
        (backup / "host.bkn").write_text("old\n", encoding="utf-8")
        # 版本文件也会被备份进 .pre-apply（V-4 新增），同样不算候选内容
        (cand / "payload" / ".pre-apply" / "bkn-version.json").write_text("{}", encoding="utf-8")
    return cand


class TestPayloadSemantics(unittest.TestCase):
    def test_collect_payload_excludes_pre_apply(self):
        with tempfile.TemporaryDirectory() as tmp:
            cand = _make_candidate(Path(tmp), with_pre_apply=True)
            copies, patches = pa.collect_payload(cand)
            rels = sorted(str(p.relative_to(cand / "payload")) for p in copies)
            self.assertEqual(rels, ["bkn/objects/host.bkn"])
            self.assertEqual(patches, [])

    def test_hash_unchanged_by_pre_apply_presence(self):
        """带不带 `.pre-apply/`，同一份候选内容必须算出同一个 hash。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            without = _make_candidate(root / "a", with_pre_apply=False)
            with_pre = _make_candidate(root / "b", with_pre_apply=True)
            h1 = pa._payload_hash(pa.collect_payload(without)[0], without / "payload")
            h2 = pa._payload_hash(pa.collect_payload(with_pre)[0], with_pre / "payload")
            self.assertEqual(h1, h2)

    def test_hash_is_cwd_independent(self):
        """哈希只取决于内容与**相对**结构——不因 cwd 变化（早期缺陷的守门）。"""
        with tempfile.TemporaryDirectory() as tmp:
            cand = _make_candidate(Path(tmp), with_pre_apply=True)
            copies, patches = pa.collect_payload(cand)
            old = os.getcwd()
            try:
                os.chdir("/tmp")
                h_tmp = pa._payload_hash(copies + patches, cand / "payload")
                os.chdir(str(ROOT))
                h_root = pa._payload_hash(copies + patches, cand / "payload")
            finally:
                os.chdir(old)
            self.assertEqual(h_tmp, h_root)

    def test_payload_file_hash_matches_ledger_convention(self):
        """记录的哈希口径 = (相对路径, 文件 sha256) 逐项喂入——与账本 `hash_method` 一致。"""
        with tempfile.TemporaryDirectory() as tmp:
            cand = _make_candidate(Path(tmp), with_pre_apply=False)
            copies, _ = pa.collect_payload(cand)
            got = pa._payload_hash(copies, cand / "payload")
            h = hashlib.sha256()
            for rel, digest in sorted(
                    (str(p.relative_to(cand / "payload")),
                     hashlib.sha256(p.read_bytes()).hexdigest()) for p in copies):
                h.update(rel.encode("utf-8"))
                h.update(digest.encode("utf-8"))
            self.assertEqual(got, h.hexdigest())


class TestAnchorPrefixSingleSource(unittest.TestCase):
    def test_anchor_prefix_comes_from_changeset(self):
        import changeset  # noqa: PLC0415

        self.assertEqual(pa._anchor_prefix(), changeset.ANCHOR_PREFIX)


class TestWhitelistSingleSource(unittest.TestCase):
    def test_status_and_apply_whitelists_match(self):
        """白名单权威在 `pending_apply`；`pending_status` 的副本必须与之相等（防漂移）。"""
        import pending_status as ps  # noqa: PLC0415

        self.assertEqual(ps.ALLOWED_PREFIXES, pa.ALLOWED_PREFIXES)


class TestRemovals(unittest.TestCase):
    """移动/删除的表达（2026-10-11：2-1 收敛的执行需要，机制缺口条随之关闭）。

    覆盖：哈希并入、旧行为兼容（空 removals）、结构拒绝、**端到端移动**、
    **门禁失败即回滚（被删文件必须还原）**、过期 sha 拒绝。
    """

    def _cand(self, tmp: Path, with_removals: bool = True, sha: str | None = None,
              path: str = "bkn/objects/old.bkn") -> tuple[Path, Path]:
        cand = tmp / "C-20261011-90"
        (cand / "payload" / "bkn" / "objects").mkdir(parents=True)
        (cand / "payload" / "bkn" / "objects" / "new.bkn").write_text("moved\n", encoding="utf-8")
        live = tmp / "bkn" / "objects" / "old.bkn"
        live.parent.mkdir(parents=True, exist_ok=True)
        live.write_text("old content\n", encoding="utf-8")
        candj = {"id": cand.name, "status": "pending", "landing": "x", "target_dimension": "content"}
        if with_removals:
            candj["removals"] = [{
                "path": path,
                "sha256": sha if sha is not None else hashlib.sha256(b"old content\n").hexdigest(),
            }]
        (cand / "candidate.json").write_text(json.dumps(candj, ensure_ascii=False), encoding="utf-8")
        return cand, live

    def _approve(self, cand: Path) -> None:
        copies, patches = pa.collect_payload(cand)
        candj = json.loads((cand / "candidate.json").read_text(encoding="utf-8"))
        h = pa._payload_hash(copies + patches, cand / "payload", pa.collect_removals(candj))
        (cand.parent / "ledger.jsonl").write_text(json.dumps({
            "id": cand.name, "at": "2026-10-11T00:00:00+00:00", "decision": "approve",
            "by": "测试", "reason": "drill", "payload_hash": h}) + "\n", encoding="utf-8")

    def _run(self, cand: Path, root: Path, extra: list | None = None) -> int:
        old_root = pa.REPO_ROOT
        pa.REPO_ROOT = root
        try:
            return pa.main([cand.name, "--pending-dir", str(cand.parent)] + (extra or []))
        finally:
            pa.REPO_ROOT = old_root

    def test_hash_differs_when_removals_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            cand, _ = self._cand(Path(tmp))
            copies, patches = pa.collect_payload(cand)
            h_no = pa._payload_hash(copies + patches, cand / "payload")
            h_yes = pa._payload_hash(copies + patches, cand / "payload",
                                     pa.collect_removals(json.loads((cand / "candidate.json").read_text(encoding="utf-8"))))
            self.assertNotEqual(h_no, h_yes)

    def test_hash_empty_removals_equals_legacy(self):
        with tempfile.TemporaryDirectory() as tmp:
            cand, _ = self._cand(Path(tmp), with_removals=False)
            copies, patches = pa.collect_payload(cand)
            self.assertEqual(pa._payload_hash(copies + patches, cand / "payload"),
                             pa._payload_hash(copies + patches, cand / "payload", []))

    def test_collect_removals_rejects_bad(self):
        with self.assertRaises(ValueError):
            pa.collect_removals({"removals": [{"sha256": "x"}]})
        with self.assertRaises(ValueError):
            pa.collect_removals({"removals": [{"path": "a"}, {"path": "a"}]})

    def test_apply_move_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cand, live = self._cand(root)
            self._approve(cand)
            rc = self._run(cand, root, ["--no-gate"])
            self.assertEqual(rc, 0)
            self.assertFalse(live.exists(), "旧位置应被删除")
            self.assertEqual((root / "bkn" / "objects" / "new.bkn").read_text(encoding="utf-8"), "moved\n")
            self.assertEqual(json.loads((cand / "candidate.json").read_text(encoding="utf-8"))["status"], "applied")

    def test_gate_failure_rolls_back_removal(self):
        """不给 --no-gate：临时根里没有 scripts/gate.sh → 复验必失败 → 回滚须还原被删文件。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cand, live = self._cand(root)
            self._approve(cand)
            rc = self._run(cand, root)
            self.assertEqual(rc, 1)
            self.assertTrue(live.exists(), "回滚必须还原被删的旧位置")
            self.assertEqual(live.read_text(encoding="utf-8"), "old content\n")
            self.assertFalse((root / "bkn" / "objects" / "new.bkn").exists(), "回滚必须清掉新建文件")
            self.assertEqual(json.loads((cand / "candidate.json").read_text(encoding="utf-8"))["status"], "pending")

    def test_apply_refuses_stale_sha(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cand, live = self._cand(root, sha="0" * 64)
            self._approve(cand)
            rc = self._run(cand, root, ["--no-gate"])
            self.assertEqual(rc, 1)
            self.assertTrue(live.exists())
            self.assertFalse((root / "bkn" / "objects" / "new.bkn").exists())

    def test_apply_refuses_out_of_whitelist_removal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cand, _ = self._cand(root, path="doc/optimize/old.bkn")
            self._approve(cand)
            rc = self._run(cand, root, ["--no-gate"])
            self.assertEqual(rc, 1)

    def test_apply_refuses_missing_sha(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cand, live = self._cand(root, sha="")
            self._approve(cand)
            rc = self._run(cand, root, ["--no-gate"])
            self.assertEqual(rc, 1)
            self.assertTrue(live.exists())
