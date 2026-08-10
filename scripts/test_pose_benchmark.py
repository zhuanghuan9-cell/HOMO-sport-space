#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("benchmark_pose_tracking.py")


class PoseBenchmarkTests(unittest.TestCase):
    def run_case(self, x=110, available=True):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pose = {"source_video": {"fps": 30}, "frames": [{"frame": 30, "joints": {"left_hip": {"x": x if available else None, "y": 100 if available else None, "available": available}}}]}
            reference = {"points": [{"frame": 30, "joint": "left_hip", "x": 100, "y": 100}]}
            (root / "pose.json").write_text(json.dumps(pose))
            (root / "ref.json").write_text(json.dumps(reference))
            completed = subprocess.run([sys.executable, str(SCRIPT), "--pose", str(root / "pose.json"), "--reference", str(root / "ref.json")], text=True, capture_output=True)
            return completed.returncode, json.loads(completed.stdout)

    def test_near_reference_passes(self):
        code, result = self.run_case()
        self.assertEqual(code, 0)
        self.assertTrue(result["passed"])

    def test_missing_reference_point_fails(self):
        code, result = self.run_case(available=False)
        self.assertEqual(code, 2)
        self.assertFalse(result["passed"])


if __name__ == "__main__":
    unittest.main()
