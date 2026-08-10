#!/usr/bin/env python3
"""Create a source-bound frame manifest and conservatively classify camera view."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

VIEWS = {"side", "oblique_side", "front", "rear", "foot_end", "head_end", "unknown"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def metadata(video: Path) -> dict:
    script = Path(__file__).with_name("inspect_video_view.swift")
    run = subprocess.run(["swift", str(script), str(video)], text=True, capture_output=True)
    if run.returncode:
        raise RuntimeError(run.stderr.strip() or "camera inspection failed")
    return json.loads(run.stdout)


def classify(exercise: str, signal: dict) -> tuple[str, float, str]:
    """Return only a high-confidence label. Unknown is always safer than a guess."""
    poses = int(signal.get("pose_sample_count") or 0)
    face = float(signal.get("face_ratio") or 0)
    shoulder = signal.get("median_shoulder_to_torso_ratio")
    if poses < 4 or not isinstance(shoulder, (int, float)):
        return "unknown", 0.0, "人体或关键关节可见帧不足"
    shoulder = float(shoulder)
    # A narrow shoulder silhouette is a robust sagittal signal.  The split
    # between exact side and oblique is deliberately conservative.
    if shoulder <= 0.34:
        return "side", 0.86, "肩宽相对躯干窄，符合侧向轮廓"
    if shoulder <= 0.62:
        return "oblique_side", 0.85, "肩宽相对躯干中等，符合斜侧轮廓"
    # For a broad silhouette, face visibility distinguishes front from rear.
    if exercise == "bench_press":
        if face >= 0.70:
            return "head_end", 0.85, "头端画面持续检测到面部"
        if face <= 0.10:
            return "foot_end", 0.85, "脚端画面未持续检测到面部"
    if face >= 0.70:
        return "front", 0.85, "正向画面持续检测到面部"
    if face <= 0.10:
        return "rear", 0.85, "背向画面未持续检测到面部"
    return "unknown", 0.0, "宽体轮廓但面部可见性不足，不能可靠区分前后机位"


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a source-bound frame manifest and auto-detect the camera view.")
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--frames-dir", type=Path, required=True)
    parser.add_argument("--exercise", choices=("deadlift", "squat", "bench_press"), required=True)
    parser.add_argument("--output", type=Path, help="defaults to <frames-dir>/frame-manifest.json")
    args = parser.parse_args()
    if not args.video.is_file():
        parser.error(f"source video not found: {args.video}")
    if not args.frames_dir.is_dir():
        parser.error(f"frames directory not found: {args.frames_dir}")
    frames = sorted(args.frames_dir.glob("frame_*.*"))
    if not frames:
        parser.error("frames directory has no extracted frames")
    signal = metadata(args.video)
    view, confidence, reason = classify(args.exercise, signal)
    manifest = {
        "schema_version": 1,
        "source_video": {"filename": args.video.name, "sha256": sha256(args.video)},
        "exercise": args.exercise,
        "frame_count": len(frames),
        "detected_view": view,
        "classification_confidence": confidence,
        "classification_reason": reason,
        "classification_signal": signal,
        "evidence_frames": [frame.name for frame in frames[::max(1, len(frames) // 9)][:9]],
    }
    output = args.output or args.frames_dir / "frame-manifest.json"
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"manifest={output} view={view} confidence={confidence:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
