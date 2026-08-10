#!/usr/bin/env python3
"""Regression checks for source-bound dual-camera ordering."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("render_cards_v3", ROOT / "render_cards_v3.py")
renderer = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(renderer)


def tracking(sha: str, view: str) -> dict:
    return {"exercise": "squat", "view": view, "source_video": {
        "sha256": sha, "detected_view": view, "classification_confidence": 0.90,
    }}


def manifest(directory: Path, sha: str, view: str, confidence: float = 0.90) -> None:
    directory.mkdir()
    (directory / "frame-manifest.json").write_text(json.dumps({
        "source_video": {"sha256": sha}, "detected_view": view,
        "classification_confidence": confidence,
    }), encoding="utf-8")


class CameraBindingTests(unittest.TestCase):
    def test_swapped_frame_arguments_are_rebound_by_hash_and_view_order(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); rear = root / "rear"; side = root / "side"
            manifest(rear, "a" * 64, "rear"); manifest(side, "b" * 64, "side")
            first, first_frames, second, second_frames = renderer.bind_camera_inputs(
                tracking("b" * 64, "side"), rear, tracking("a" * 64, "rear"), side
            )
            self.assertEqual(first["view"], "side")
            self.assertEqual(first_frames, side)
            self.assertEqual(second["view"], "rear")
            self.assertEqual(second_frames, rear)

    def test_hash_mismatch_fails_before_rendering(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); rear = root / "rear"; side = root / "side"
            manifest(rear, "a" * 64, "rear"); manifest(side, "c" * 64, "side")
            with self.assertRaisesRegex(ValueError, "hash"):
                renderer.bind_camera_inputs(tracking("b" * 64, "side"), side, tracking("a" * 64, "rear"), rear)

    def test_uncertain_manifest_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); rear = root / "rear"; side = root / "side"
            manifest(rear, "a" * 64, "rear", 0.84); manifest(side, "b" * 64, "side")
            with self.assertRaisesRegex(ValueError, "uncertain"):
                renderer.bind_camera_inputs(tracking("b" * 64, "side"), side, tracking("a" * 64, "rear"), rear)


if __name__ == "__main__":
    unittest.main()
