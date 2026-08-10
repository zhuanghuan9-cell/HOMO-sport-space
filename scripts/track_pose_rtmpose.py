#!/usr/bin/env python3
"""Create an internal, confidence-gated RTMPose track for one source video.

This is deliberately independent from the card renderer.  It is a measurement
input: it never scores a lift or fills in an occluded joint.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

try:
    import cv2
    import numpy as np
except ImportError as exc:  # pragma: no cover - machine setup guard
    raise SystemExit("RTMPose tracking needs opencv-python and numpy: python3 -m pip install opencv-python numpy") from exc

JOINT_INDEX = {
    "left_shoulder": 5, "right_shoulder": 6,
    "left_elbow": 7, "right_elbow": 8,
    "left_wrist": 9, "right_wrist": 10,
    "left_hip": 11, "right_hip": 12,
    "left_knee": 13, "right_knee": 14,
    "left_ankle": 15, "right_ankle": 16,
}
POSE_JOINTS = tuple(JOINT_INDEX)
MODEL_URLS = {
    "detector": "https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/onnx_sdk/yolox_tiny_8xb8-300e_humanart-6f3252f9.zip",
    "pose": "https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/onnx_sdk/rtmpose-s_simcc-body7_pt-body7_420e-256x192-acd4a1ef_20230504.zip",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_key_times(tracking_path: Path | None) -> list[float]:
    """Read existing, independently verified phase times without mutating it."""
    if tracking_path is None:
        return []
    data = json.loads(tracking_path.read_text(encoding="utf-8"))
    values: set[float] = set()
    for repetition in data.get("repetitions", []):
        for point in repetition.get("bar_path", []):
            if isinstance(point, dict) and point.get("phase") in {"start", "touch", "lockout", "bottom", "lift_off", "liftoff", "prepull", "ascent", "press"}:
                if isinstance(point.get("time"), (int, float)):
                    values.add(float(point["time"]))
        for points in (repetition.get("landmarks") or {}).values():
            for point in points or []:
                if isinstance(point, dict) and point.get("phase") in {"start", "touch", "lockout", "bottom", "lift_off", "ascent", "press"} and isinstance(point.get("time"), (int, float)):
                    values.add(float(point["time"]))
    for item in ((data.get("render") or {}).get("rear_bar_level_evidence") or {}).values():
        if isinstance(item, dict) and isinstance(item.get("time"), (int, float)):
            values.add(float(item["time"]))
    return sorted(values)


def sample_frames(total: int, source_fps: float, base_fps: float, key_fps: float, key_times: list[float], window: float) -> dict[int, int]:
    """Map source-frame number to the effective sampling rate (base or dense)."""
    base_step = max(1, round(source_fps / base_fps))
    dense_step = max(1, round(source_fps / key_fps))
    samples = {frame: int(base_fps) for frame in range(0, total, base_step)}
    for time in key_times:
        start = max(0, int(round((time - window) * source_fps)))
        end = min(total - 1, int(round((time + window) * source_fps)))
        for frame in range(start, end + 1, dense_step):
            samples[frame] = int(key_fps)
    return dict(sorted(samples.items()))


def choose_subject(keypoints: np.ndarray, scores: np.ndarray) -> tuple[np.ndarray, np.ndarray] | tuple[None, None]:
    """Use the highest-confidence detected person, not an invented composite."""
    if keypoints is None or len(keypoints) == 0:
        return None, None
    scores = np.asarray(scores)
    means = scores.mean(axis=1) if scores.ndim > 1 else scores
    index = int(np.argmax(means))
    return np.asarray(keypoints[index]), np.asarray(scores[index])


def joints_for(points: np.ndarray | None, scores: np.ndarray | None, threshold: float) -> dict:
    result = {}
    for name, index in JOINT_INDEX.items():
        confidence = float(scores[index]) if scores is not None and len(scores) > index else 0.0
        usable = bool(points is not None and len(points) > index and confidence >= threshold)
        result[name] = {
            "x": round(float(points[index][0]), 3) if usable else None,
            "y": round(float(points[index][1]), 3) if usable else None,
            "confidence": round(confidence, 4),
            "available": usable,
        }
    return result


def model_record(path: str) -> dict:
    value = Path(path)
    return {"path": str(value), "sha256": sha256(value), "bytes": value.stat().st_size}


def main() -> int:
    parser = argparse.ArgumentParser(description="Internal RTMPose tracking; no technique score is produced.")
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--exercise", required=True, choices=("deadlift", "squat", "bench_press"))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--tracking", type=Path, help="Existing bar tracking JSON used only to densify phase windows")
    parser.add_argument("--base-fps", type=float, default=15.0)
    parser.add_argument("--key-fps", type=float, default=30.0)
    parser.add_argument("--key-window", type=float, default=0.20)
    parser.add_argument("--confidence", type=float, default=0.60)
    args = parser.parse_args()
    if not args.video.is_file():
        raise SystemExit(f"Video not found: {args.video}")
    if args.base_fps <= 0 or args.key_fps < args.base_fps or not 0 < args.confidence <= 1:
        raise SystemExit("Require positive base fps, key fps >= base fps, and confidence in (0, 1].")
    try:
        from rtmlib import Body
        import rtmlib
    except ImportError as exc:  # pragma: no cover - machine setup guard
        raise SystemExit("RTMPose requires rtmlib and onnxruntime: python3 -m pip install rtmlib onnxruntime") from exc

    capture = cv2.VideoCapture(str(args.video))
    fps = float(capture.get(cv2.CAP_PROP_FPS)) or 30.0
    total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    width, height = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)), int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if total <= 0 or width <= 0 or height <= 0:
        raise SystemExit("Could not read video metadata.")
    key_times = source_key_times(args.tracking)
    frames_to_process = sample_frames(total, fps, args.base_fps, args.key_fps, key_times, args.key_window)
    # RTMlib downloads OpenMMLab's official compact Body checkpoints on first use.
    # This COCO-17 model exposes exactly the joints used by the lift protocol.
    estimator = Body(mode="lightweight", backend="onnxruntime", device="cpu")
    output_frames = []
    for frame_index, rate in frames_to_process.items():
        capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = capture.read()
        if not ok:
            continue
        points, scores = estimator(frame)
        person_points, person_scores = choose_subject(points, scores)
        output_frames.append({
            "frame": frame_index,
            "time": round(frame_index / fps, 5),
            "sample_rate": rate,
            "person_detected": person_points is not None,
            "joints": joints_for(person_points, person_scores, args.confidence),
        })
    capture.release()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "backend": "RTMPose Body via rtmlib",
        "exercise": args.exercise,
        "source_video": {"path": str(args.video.resolve()), "sha256": sha256(args.video), "fps": fps, "frame_count": total, "image_size": [width, height]},
        "model": {"rtmlib_version": getattr(rtmlib, "__version__", "unknown"), "mode": "lightweight", "backend": "onnxruntime", "device": "cpu", "official_urls": MODEL_URLS, "cached_models": [model_record(estimator.det_model.onnx_model), model_record(estimator.pose_model.onnx_model)]},
        "sampling": {"base_fps": args.base_fps, "key_fps": args.key_fps, "key_window_seconds": args.key_window, "key_times": key_times},
        "confidence_gate": {"minimum": args.confidence, "maximum_missing_seconds": 0.20, "interpolation_for_conclusions": False},
        "frames": output_frames,
    }
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(output_frames)} pose samples to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
