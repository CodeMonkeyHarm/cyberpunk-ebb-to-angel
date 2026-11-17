import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from automation import regression

ROOT = Path(__file__).resolve().parent.parent
OLD = ROOT / "references" / "bodies" / "ANGEL" / "v1.1.0"
NEW = ROOT / "references" / "bodies" / "ANGEL" / "2.0.0"


@unittest.skipUnless((OLD / "manifest.json").is_file() and (NEW / "manifest.json").is_file(),
                     "缺少 v1.1.0 或 v2.0.0 产物")
class TestRegression(unittest.TestCase):
    def test_geometry_bytes_identical(self):
        r = regression.run(OLD, NEW)
        self.assertTrue(r["static_glb"]["geometry_identical"], r["static_glb"]["mismatches"])
        self.assertTrue(r["skinned_glb"]["geometry_identical"], r["skinned_glb"]["mismatches"])

    def test_skeleton_and_weights_identical(self):
        r = regression.run(OLD, NEW)
        self.assertTrue(r["skeleton"]["identical"])
        self.assertTrue(r["weights"]["identical"])
        self.assertTrue(r["verdict"]["pass"])


class TestCli(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, "automation/main.py", *args],
                              cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                              env={**os.environ, "PYTHONUTF8": "1"}, timeout=600)

    def test_help_survives_western_windows_encoding(self):
        result = subprocess.run(
            [sys.executable, "automation/main.py", "--help"], cwd=ROOT,
            capture_output=True, timeout=60,
            env={**os.environ, "PYTHONUTF8": "0", "PYTHONIOENCODING": "cp1252"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("工作站", result.stdout.decode("utf-8"))

    def test_ref_list(self):
        r = self.run_cli("ref", "list")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        ids = [x["body_id"] for x in data["profiles"]]
        self.assertIn("ANGEL", ids)
        self.assertIn("EBB", ids)

    def test_build_ebb_fails_cleanly(self):
        r = self.run_cli("ref", "build", "--body", "EBB")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("EBB", (r.stdout + r.stderr))

    def test_diff_pending_exit_code(self):
        # 用 --no-write 只读模式：此前的写法会经 CLI 把 EBB→ANGEL 差异场
        # 重新写进 references/bodies/ANGEL/2.0.0/，污染生产产物（Phase 2 已修）。
        r = self.run_cli("ref", "diff", "--source", "EBB", "--body", "ANGEL", "--no-write")
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        data = json.loads(r.stdout)
        self.assertEqual(data["status"], "PENDING")
        self.assertTrue(data.get("dry_run"))
        self.assertIsNone(data.get("json"))


if __name__ == "__main__":
    unittest.main()
