#!/usr/bin/env python3
"""Deterministic regression tests for conservative automatic view labels."""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("create_frame_manifest.py")
SPEC = importlib.util.spec_from_file_location("create_frame_manifest", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(module)


def signal(shoulder: float, face: float) -> dict:
    return {"pose_sample_count": 6, "median_shoulder_to_torso_ratio": shoulder, "face_ratio": face}


class CameraViewDetectionTests(unittest.TestCase):
    def test_side_and_oblique(self):
        self.assertEqual(module.classify("squat", signal(.20, 0))[0], "side")
        self.assertEqual(module.classify("squat", signal(.50, .30))[0], "oblique_side")

    def test_front_and_rear(self):
        self.assertEqual(module.classify("deadlift", signal(.80, .90))[0], "front")
        self.assertEqual(module.classify("deadlift", signal(.80, 0))[0], "rear")

    def test_bench_end_views(self):
        self.assertEqual(module.classify("bench_press", signal(.80, .90))[0], "head_end")
        self.assertEqual(module.classify("bench_press", signal(.80, 0))[0], "foot_end")

    def test_ambiguous_signal_is_not_guessed(self):
        view, confidence, _ = module.classify("squat", signal(.80, .35))
        self.assertEqual(view, "unknown")
        self.assertEqual(confidence, 0.0)


if __name__ == "__main__":
    unittest.main()
