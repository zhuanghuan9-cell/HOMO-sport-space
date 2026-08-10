#!/usr/bin/env python3
"""Compare RTMPose samples with independently reviewed 2D landmark references.

The reference file deliberately contains only reviewed key frames.  Passing this
benchmark is a prerequisite for wiring pose evidence into report conclusions.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def nearest(frames: list[dict], source_frame: int, source_fps: float) -> dict | None:
    return min(frames, key=lambda item: abs(int(item.get("frame", -10**9)) - source_frame), default=None)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pose", required=True, type=Path)
    parser.add_argument("--reference", required=True, type=Path, help="JSON with reviewed [{frame, joint, x, y}] points")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    pose = json.loads(args.pose.read_text(encoding="utf-8"))
    reference = json.loads(args.reference.read_text(encoding="utf-8"))
    frames = pose.get("frames") or []
    errors = []
    unavailable = []
    for point in reference.get("points", []):
        frame = nearest(frames, int(point["frame"]), float((pose.get("source_video") or {}).get("fps", 30)))
        joint = (frame or {}).get("joints", {}).get(point["joint"], {})
        if not frame or not joint.get("available"):
            unavailable.append(point)
            continue
        errors.append(math.hypot(float(joint["x"]) - float(point["x"]), float(joint["y"]) - float(point["y"])))
    errors.sort()
    median = errors[len(errors) // 2] if errors else None
    p90 = errors[min(len(errors) - 1, math.ceil(len(errors) * .90) - 1)] if errors else None
    availability = (len(errors) / len(reference.get("points") or [])) if reference.get("points") else 0.0
    result = {
        "reference_points": len(reference.get("points") or []),
        "available_points": len(errors),
        "availability": availability,
        "median_error_px": median,
        "p90_error_px": p90,
        "thresholds": {"median_error_px": 24, "p90_error_px": 40, "availability": .90},
        "passed": bool(median is not None and median <= 24 and p90 is not None and p90 <= 40 and availability >= .90),
        "unavailable": unavailable,
    }
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
