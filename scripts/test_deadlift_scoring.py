#!/usr/bin/env python3
"""Rule-first tests for conventional-deadlift AI scoring."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).parent
spec = importlib.util.spec_from_file_location("deadlift_scoring", ROOT / "deadlift_scoring.py")
scoring = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scoring)


def point(frame, x, y, phase="sample"):
    return {"frame": frame, "time": frame / 30, "x": x, "y": y, "phase": phase}


def pose_frame(frame, joints):
    return {"frame": frame, "time": frame / 30, "joints": {
        name: {"x": x, "y": y, "confidence": 0.95, "available": True}
        for name, (x, y) in joints.items()
    }}


def side_data(path_x=(100, 102, 103, 104), variation="conventional"):
    points = [point(i, x, 300 - i * 20, "lockout" if i == 3 else "sample") for i, x in enumerate(path_x)]
    points[0]["phase"] = "lift_off"
    return {
        "exercise": "deadlift", "view": "side", "plate_diameter_px": 100,
        "render": {"deadlift_variation": variation, "deadlift_execution": "reset_single"},
        "repetitions": [{"rep": 1, "bar_path": points}],
        "bar_tracking": {"status": "available", "raw_points": points, "display_points": points},
    }


def rear_data(delta=1):
    return {
        "exercise": "deadlift", "view": "rear", "plate_diameter_px": 100,
        "repetitions": [{"rep": 1, "bar_path": [point(0, 100, 300), point(3, 100, 220)]}],
        "render": {"rear_bar_level_evidence": {
            "reference": {"frame": 0, "time": 0, "label": "两端高度接近", "screen_left": {"x": 50, "y": 300}, "screen_right": {"x": 350, "y": 300 + delta}},
            "ascent": {"frame": 3, "time": .1, "label": "两端同步上升", "screen_left": {"x": 50, "y": 220}, "screen_right": {"x": 350, "y": 220 + delta}},
        }},
    }


def side_pose():
    common = {
        "left_shoulder": (150, 140), "left_hip": (150, 220),
        "left_knee": (150, 285), "left_ankle": (150, 350),
    }
    # Stable trunk during the first 10% of upward travel, then a clear lockout.
    return {"frames": [
        pose_frame(0, common),
        pose_frame(1, {**common, "left_shoulder": (151, 139), "left_hip": (151, 219)}),
        pose_frame(3, {"left_shoulder": (150, 100), "left_hip": (150, 190), "left_knee": (150, 280), "left_ankle": (150, 350)}),
    ]}


def rear_pose():
    return {"frames": [pose_frame(0, {
        "left_shoulder": (100, 150), "right_shoulder": (300, 150),
        "left_hip": (120, 210), "right_hip": (280, 210),
        "left_knee": (125, 285), "right_knee": (275, 285),
        "left_ankle": (125, 350), "right_ankle": (275, 350),
    })]}


class DeadliftScoringTests(unittest.TestCase):
    def test_stable_dual_view_receives_total_and_ss(self):
        result = scoring.score_deadlift(side_data(), rear_data(), side_pose(), rear_pose())
        self.assertTrue(result["scorable"])
        self.assertEqual(result["total"], 100)
        self.assertEqual(result["grade"], "SS")
        self.assertEqual({item["id"] for item in result["items"]}, {"DL-01", "DL-02", "DL-03", "DL-04", "DL-05", "DL-06"})

    def test_clear_core_bar_drift_caps_grade_at_a(self):
        result = scoring.score_deadlift(side_data((100, 114, 116, 118)), rear_data(), side_pose(), rear_pose())
        self.assertTrue(result["scorable"])
        self.assertEqual(result["items"][0]["status"], "明显待改善")
        self.assertEqual(result["grade"], "A")

    def test_missing_side_pose_refuses_total_score(self):
        result = scoring.score_deadlift(side_data(), rear_data(), None, rear_pose())
        self.assertFalse(result["scorable"])
        self.assertIsNone(result["total"])
        self.assertIsNone(result["grade"])
        self.assertIn("侧面姿态", result["unavailable_reason"])

    def test_non_conventional_variation_refuses_total_score(self):
        result = scoring.score_deadlift(side_data(variation="pause"), rear_data(), side_pose(), rear_pose())
        self.assertFalse(result["scorable"])
        self.assertIn("常规单次", result["unavailable_reason"])

    def test_unknown_variation_refuses_total_score(self):
        side = side_data()
        side["render"].pop("deadlift_variation")
        result = scoring.score_deadlift(side, rear_data(), side_pose(), rear_pose())
        self.assertFalse(result["scorable"])
        self.assertIsNone(result["total"])

    def test_missing_rear_level_evidence_refuses_total_score(self):
        rear = rear_data()
        rear["render"] = {}
        result = scoring.score_deadlift(side_data(), rear, side_pose(), rear_pose())
        self.assertFalse(result["scorable"])
        self.assertIn("后方左右杠铃端点", result["unavailable_reason"])

    def test_non_reset_execution_refuses_total_score(self):
        side = side_data()
        side["render"]["deadlift_execution"] = "touch_and_go"
        result = scoring.score_deadlift(side, rear_data(), side_pose(), rear_pose())
        self.assertFalse(result["scorable"])
        self.assertIn("落地重置", result["unavailable_reason"])

    def test_score_items_include_traceability_not_public_subscores(self):
        result = scoring.score_deadlift(side_data(), rear_data(), side_pose(), rear_pose())
        item = result["items"][0]
        self.assertIn("evidence_frames", item)
        self.assertIn("metrics", item)
        self.assertIn("limitation", item)
        self.assertNotIn("subscore", item)


if __name__ == "__main__":
    unittest.main()
