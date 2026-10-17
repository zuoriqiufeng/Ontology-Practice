"""sync_audit 的对账不变量测试（2026-10-12）。

不变量：外面只能被 pending_apply 改 → 候选触及的每个文件 == 最后一次落盘它的候选的 payload；
被 removals 删除的文件必须不存在。检出「绕过候选的直接改动」。
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import sync_audit as sa  # noqa: E402


def _cand(pending: Path, cid: str, files: dict, removals: list | None = None) -> None:
    d = pending / cid / "payload"
    for rel, content in files.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    (pending / cid / "candidate.json").write_text(
        json.dumps({"id": cid, "removals": removals or []}), encoding="utf-8")


def _append_apply(pending: Path, cid: str, at: str, version: str) -> None:
    with (pending / "ledger.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"id": cid, "at": at, "decision": "apply", "by": "t",
                            "reason": "t", "version_id": version}) + "\n")


class TestSyncAudit(unittest.TestCase):

    def _scene(self, tmp: str):
        """两条候选先后落盘：C-A 写 x.bkn=v1；C-B 写 x.bkn=v2 且删 y.bkn。"""
        root = Path(tmp) / "repo"
        pending = Path(tmp) / "pending"
        root.mkdir()
        pending.mkdir()
        _cand(pending, "C-A", {"bkn/x.bkn": "v1\n"})
        _append_apply(pending, "C-A", "2026-01-01T00:00:00+00:00", "bkn-20990101-1")
        _cand(pending, "C-B", {"bkn/x.bkn": "v2\n"},
              removals=[{"path": "bkn/y.bkn", "sha256": "0" * 64}])
        _append_apply(pending, "C-B", "2026-01-02T00:00:00+00:00", "bkn-20990102-1")
        (root / "bkn").mkdir()
        (root / "bkn" / "x.bkn").write_text("v2\n", encoding="utf-8")  # C-B 落盘后的状态
        return root, pending

    def test_clean_is_consistent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, pending = self._scene(tmp)
            d = sa.audit(root, pending)
            self.assertEqual(d["problems"], [], d["problems"])
            self.assertEqual(d["covered"], 2)  # x.bkn（payload）+ y.bkn（removal）
            states = {r[0]: r[3] for r in d["rows"]}
            self.assertEqual(states.get("bkn/x.bkn"), "ok")
            self.assertEqual(states.get("bkn/y.bkn"), "removed")

    def test_direct_edit_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, pending = self._scene(tmp)
            (root / "bkn" / "x.bkn").write_text("hacked\n", encoding="utf-8")
            d = sa.audit(root, pending)
            self.assertTrue(any("x.bkn" in p and "C-B" in p for p in d["problems"]), d["problems"])

    def test_removed_file_resurrected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, pending = self._scene(tmp)
            (root / "bkn" / "y.bkn").write_text("back\n", encoding="utf-8")
            d = sa.audit(root, pending)
            self.assertTrue(any("y.bkn" in p and "删除" in p for p in d["problems"]), d["problems"])

    def test_later_payload_supersedes_removal(self):
        """后落盘者重新建了被删文件 → 以「最后落盘者」为准（不再判漂移）。"""
        with tempfile.TemporaryDirectory() as tmp:
            root, pending = self._scene(tmp)
            (root / "bkn" / "y.bkn").write_text("recreated\n", encoding="utf-8")
            _cand(pending, "C-C", {"bkn/y.bkn": "recreated\n"})
            _append_apply(pending, "C-C", "2026-01-03T00:00:00+00:00", "bkn-20990103-1")
            d = sa.audit(root, pending)
            self.assertEqual(d["problems"], [], d["problems"])


if __name__ == "__main__":
    unittest.main()
