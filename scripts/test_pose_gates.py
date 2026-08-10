#!/usr/bin/env python3
"""Fast, model-free checks for strict pose-evidence gates."""
from __future__ import annotations

import unittest

from track_pose_rtmpose import sample_frames
from validate_pose_tracking import assess


def pose_frame(time, available=True, confidence=0.95):
    joints = {}
    for name in ("left_shoulder", "right_shoulder", "left_elbow", "right_elbow", "left_wrist", "right_wrist", "left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle"):
        joints[name] = {"available": available, "confidence": confidence}
    return {"time": time, "joints": joints}


class PoseGateTests(unittest.TestCase):
    def bench_tracking(self):
        return {"exercise": "bench_press", "repetitions": [{"bar_path": [{"time": 1.0, "phase": "touch"}, {"time": 1.2, "phase": "press"}]}]}

    def pose(self, frames):
        return {"exercise": "bench_press", "confidence_gate": {"minimum": 0.60, "maximum_missing_seconds": 0.20}, "frames": frames}

    def test_trusted_side_pose_passes(self):
        result = assess(self.pose([pose_frame(1.0), pose_frame(1.2)]), self.bench_tracking(), "side")
        self.assertEqual(result["status"], "available")

    def test_low_confidence_rejected(self):
        result = assess(self.pose([pose_frame(1.0, confidence=0.59), pose_frame(1.2)]), self.bench_tracking(), "side")
        self.assertEqual(result["status"], "unavailable")

    def test_long_occlusion_rejected(self):
        result = assess(self.pose([pose_frame(1.0), pose_frame(1.2, available=False), pose_frame(1.5)]), self.bench_tracking(), "side")
        self.assertEqual(result["status"], "unavailable")

    def test_rear_view_has_no_pose_judgement(self):
        tracking = {"exercise": "squat", "repetitions": [{"bar_path": [{"time": 1.0, "phase": "bottom"}]}]}
        self.assertEqual(assess(self.pose([pose_frame(1.0)]), tracking, "rear")["status"], "unavailable")

    def test_dense_phase_sampling(self):
        samples = sample_frames(120, 30, 15, 30, [2.0], .20)
        self.assertEqual(samples[60], 30)
        self.assertEqual(samples[54], 30)
        self.assertEqual(samples[66], 30)


if __name__ == "__main__":
    unittest.main()
