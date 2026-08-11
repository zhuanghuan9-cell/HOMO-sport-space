#!/usr/bin/env python3
"""Rule-first tests for ordinary-filming-friendly squat scoring."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).parent
spec = importlib.util.spec_from_file_location("squat_scoring", ROOT / "squat_scoring.py")
scoring = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scoring)


def point(frame, x, y, phase="sample"):
    return {"frame": frame, "time": frame / 30, "x": x, "y": y, "phase": phase}


def pose_frame(frame, hip_y, knee_y, ankle_y, shoulder_y, knee_angle=170):
    # The score module calculates the real angle from these points; this chain
    # is intentionally simple but keeps hip-knee distance stable.
    return {"frame": frame, "time": frame / 30, "joints": {
        "left_shoulder": {"x": 150, "y": shoulder_y, "confidence": .95, "available": True},
        "left_hip": {"x": 150, "y": hip_y, "confidence": .95, "available": True},
        "left_knee": {"x": 150, "y": knee_y, "confidence": .95, "available": True},
        "left_ankle": {"x": 150, "y": ankle_y, "confidence": .95, "available": True},
    }}


def side_data(path_x=(200, 201, 202, 201, 200)):
    raw = [
        point(0, path_x[0], 100, "setup"), point(15, path_x[1], 130, "descent"),
        point(30, path_x[2], 160, "bottom"), point(45, path_x[3], 130, "ascent"),
        point(60, path_x[4], 100, "lockout"),
    ]
    return {
        "exercise": "squat", "view": "side", "plate_diameter_px": 100,
        "reference": {"midfoot_x": 200}, "repetitions": [{"rep": 1, "bar_path": raw}],
        "bar_tracking": {"status": "available", "raw_points": raw, "display_points": raw},
    }


def rear_data(delta=1):
    return {"exercise": "squat", "view": "rear", "plate_diameter_px": 100,
        "repetitions": [{"rep": 1, "bar_path": [point(0, 200, 100), point(60, 200, 100)]}],
        "render": {"rear_bar_level_evidence": {
            "reference": {"frame": 30, "time": 1, "label": "触底：两端高度接近", "screen_left": {"x": 60, "y": 160}, "screen_right": {"x": 340, "y": 160 + delta}},
            "ascent": {"frame": 45, "time": 1.5, "label": "推起：两端同步上升", "screen_left": {"x": 60, "y": 130}, "screen_right": {"x": 340, "y": 130 + delta}},
        }}}


def side_pose():
    return {"frames": [
        pose_frame(0, 200, 280, 360, 120), pose_frame(15, 230, 282, 360, 145),
        pose_frame(30, 250, 285, 360, 165), pose_frame(45, 230, 282, 360, 145),
        pose_frame(60, 200, 280, 360, 120),
    ]}


class SquatScoringTests(unittest.TestCase):
    def test_ordinary_complete_dual_view_receives_total_and_grade(self):
        result = scoring.score_squat(side_data(), rear_data(), side_pose(), None)
        self.assertTrue(result["scorable"])
        self.assertIsInstance(result["total"], int)
        self.assertEqual({item["id"] for item in result["items"]}, {"SQ-01", "SQ-02", "SQ-03", "SQ-04", "SQ-05", "SQ-06"})

    def test_missing_pose_uses_neutral_baseline_not_rejection(self):
        result = scoring.score_squat(side_data(), rear_data(), None, None)
        self.assertTrue(result["scorable"])
        self.assertEqual({item["id"] for item in result["items"] if item["source"] == "中性基准"}, {"SQ-02", "SQ-03", "SQ-04", "SQ-06"})

    def test_clear_bar_trend_is_core_and_never_allows_s_or_ss(self):
        result = scoring.score_squat(side_data((200, 215, 218, 215, 200)), rear_data(), side_pose(), None)
        path = next(item for item in result["items"] if item["id"] == "SQ-01")
        self.assertEqual(path["status"], "明显待改善")
        self.assertNotIn(result["grade"], {"SS", "S"})

    def test_missing_rear_evidence_refuses_total(self):
        rear = rear_data(); rear["render"] = {}
        result = scoring.score_squat(side_data(), rear, side_pose(), None)
        self.assertFalse(result["scorable"])
        self.assertIn("后方左右杠铃端点", result["unavailable_reason"])

    def test_pause_variant_is_not_scored_as_a_regular_squat(self):
        side = side_data(); side["render"] = {"squat_variation": "pause"}
        result = scoring.score_squat(side, rear_data(), side_pose(), None)
        self.assertFalse(result["scorable"])
        self.assertIn("暂停", result["unavailable_reason"])


if __name__ == "__main__":
    unittest.main()
