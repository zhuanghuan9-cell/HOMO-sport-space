#!/usr/bin/env python3
"""Rule-first tests for camera-normalized squat phase detection."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).parent
spec = importlib.util.spec_from_file_location("squat_phase_detection", ROOT / "squat_phase_detection.py")
phases = importlib.util.module_from_spec(spec)
spec.loader.exec_module(phases)


def sample(frame, hip_y, knee_angle, bar_y, ankle_x=200):
    return {
        "frame": frame, "time": frame / 30,
        "hip_y": hip_y, "knee_angle": knee_angle, "bar_y": bar_y,
        "hip_knee_distance": 100, "ankle_x": ankle_x,
    }


def normal_rep(pause_frames=0):
    values = []
    # 0.5s setup, a controlled descent, bottom, then ascent and lockout.
    values += [sample(frame, 200, 170, 120) for frame in range(16)]
    values += [sample(16 + index, 205 + index * 5, 166 - index * 5, 125 + index * 5) for index in range(8)]
    bottom_frame = 24
    values += [sample(bottom_frame + index, 245, 126, 165) for index in range(pause_frames + 1)]
    ascent_start = bottom_frame + pause_frames + 1
    values += [sample(ascent_start + index, 240 - index * 5, 130 + index * 6, 160 - index * 5) for index in range(8)]
    values += [sample(ascent_start + 8 + index, 200, 170, 120) for index in range(16)]
    return values


class SquatPhaseDetectionTests(unittest.TestCase):
    def test_normal_rep_has_ordered_setup_descent_bottom_ascent_lockout(self):
        result = phases.detect_squat_phases(normal_rep())
        self.assertTrue(result["available"])
        self.assertEqual(result["phases"], ["setup", "descent", "bottom", "ascent", "lockout"])

    def test_pause_bottom_is_marked_but_not_called_a_reversal_error(self):
        result = phases.detect_squat_phases(normal_rep(pause_frames=13))
        self.assertTrue(result["available"])
        self.assertTrue(result["pause_bottom"])
        self.assertIn("pause_bottom", result["phases"])

    def test_forward_lean_without_hip_drop_is_not_a_squat(self):
        samples = [sample(frame, 200, 170 - frame * .1, 120) for frame in range(35)]
        result = phases.detect_squat_phases(samples)
        self.assertFalse(result["available"])
        self.assertIn("髋部未出现持续下移", result["reason"])

    def test_walking_is_rejected_before_a_rep_is_cut(self):
        samples = normal_rep()
        for item in samples:
            item["ankle_x"] = 200 + item["frame"] * 4
        result = phases.detect_squat_phases(samples)
        self.assertFalse(result["available"])
        self.assertIn("脚踝横向移动", result["reason"])

    def test_incomplete_ascent_does_not_claim_lockout(self):
        samples = normal_rep()[:-15]
        result = phases.detect_squat_phases(samples)
        self.assertTrue(result["available"])
        self.assertNotIn("lockout", result["phases"])


if __name__ == "__main__":
    unittest.main()
