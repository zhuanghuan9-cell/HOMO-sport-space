#!/usr/bin/env python3
"""Validate RTMPose evidence before it may inform a lift conclusion."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

JOINT_CHAINS_BY_VIEW = {
    # A sagittal camera normally sees one side more reliably.  Requiring both
    # sides would turn normal self-occlusion into a fabricated failed reading.
    ("deadlift", "side"): (("left_shoulder", "left_hip"), ("right_shoulder", "right_hip")),
    ("deadlift", "oblique_side"): (("left_shoulder", "left_hip"), ("right_shoulder", "right_hip")),
    ("squat", "side"): (("left_hip", "left_knee", "left_ankle"), ("right_hip", "right_knee", "right_ankle")),
    ("squat", "oblique_side"): (("left_hip", "left_knee", "left_ankle"), ("right_hip", "right_knee", "right_ankle")),
    ("bench_press", "side"): (("left_shoulder", "left_elbow", "left_wrist"), ("right_shoulder", "right_elbow", "right_wrist")),
    ("bench_press", "oblique_side"): (("left_shoulder", "left_elbow", "left_wrist"), ("right_shoulder", "right_elbow", "right_wrist")),
}


def critical_times(tracking: dict) -> list[float]:
    values = []
    for repetition in tracking.get("repetitions", []):
        for point in repetition.get("bar_path", []):
            if isinstance(point, dict) and isinstance(point.get("time"), (float, int)) and point.get("phase") in {"start", "touch", "lockout", "bottom", "lift_off", "liftoff", "prepull", "ascent", "press"}:
                values.append(float(point["time"]))
    return sorted(set(values))


def nearest_frame(frames: list[dict], time: float, tolerance: float = 1 / 30 + 0.001) -> dict | None:
    candidates = [frame for frame in frames if isinstance(frame.get("time"), (float, int))]
    if not candidates:
        return None
    result = min(candidates, key=lambda item: abs(float(item["time"]) - time))
    return result if abs(float(result["time"]) - time) <= tolerance else None


def max_missing_gap(frames: list[dict], joint: str) -> float:
    ordered = sorted(frames, key=lambda item: item.get("time", -1))
    start = None
    maximum = 0.0
    for frame in ordered:
        available = bool(((frame.get("joints") or {}).get(joint) or {}).get("available"))
        time = float(frame.get("time", 0.0))
        if not available and start is None:
            start = time
        elif available and start is not None:
            maximum = max(maximum, time - start)
            start = None
    if start is not None and ordered:
        maximum = max(maximum, float(ordered[-1].get("time", 0.0)) - start)
    return maximum


def assess(pose: dict, tracking: dict, view: str) -> dict:
    exercise = tracking.get("exercise") or pose.get("exercise")
    chains = JOINT_CHAINS_BY_VIEW.get((exercise, view))
    if not chains:
        return {"status": "unavailable", "reason": "当前机位不使用姿态点作动作判断", "required_joints": []}
    minimum = float((pose.get("confidence_gate") or {}).get("minimum", 0.60))
    gap_limit = float((pose.get("confidence_gate") or {}).get("maximum_missing_seconds", 0.20))
    frames = pose.get("frames") or []
    times = critical_times(tracking)
    if not times:
        return {"status": "unavailable", "reason": "未提供可验证的关键阶段", "required_joints": [joint for chain in chains for joint in chain]}
    # Do not punish an athlete for leaving a frame before/after the analysed
    # repetition.  The 0.20-second missing rule applies to critical windows.
    critical_frames = [frame for frame in frames if any(abs(float(frame.get("time", -99)) - time) <= .20 for time in times)]
    chain_results = []
    for required in chains:
        failures, available = [], 0
        for time in times:
            frame = nearest_frame(frames, time)
            if frame is None:
                failures.append({"time": time, "reason": "关键阶段没有30帧/秒姿态样本"})
                continue
            missing = [joint for joint in required if not bool(((frame.get("joints") or {}).get(joint) or {}).get("available")) or float((((frame.get("joints") or {}).get(joint) or {}).get("confidence", 0.0))) < minimum]
            if missing:
                failures.append({"time": time, "reason": "关键关节置信度不足", "joints": missing})
            else:
                available += 1
        gaps = {joint: max_missing_gap(critical_frames, joint) for joint in required}
        chain_results.append((required, available / len(times), gaps, failures))
    required, rate, gaps, failures = max(chain_results, key=lambda item: item[1])
    long_gaps = {joint: gap for joint, gap in gaps.items() if gap > gap_limit}
    if long_gaps:
        return {"status": "unavailable", "reason": "关键关节连续缺失超过0.20秒", "required_joints": list(required), "critical_availability": rate, "gaps": long_gaps, "failures": failures}
    if rate < 0.90:
        return {"status": "unavailable", "reason": "关键阶段可用率低于90%", "required_joints": list(required), "critical_availability": rate, "failures": failures}
    return {"status": "available", "reason": "姿态数据可作为内部时序辅助证据，不单独判定动作对错", "required_joints": list(required), "critical_availability": rate, "failures": []}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pose", required=True, type=Path)
    parser.add_argument("--tracking", required=True, type=Path)
    parser.add_argument("--view", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = assess(json.loads(args.pose.read_text(encoding="utf-8")), json.loads(args.tracking.read_text(encoding="utf-8")), args.view)
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if result["status"] == "available" else 2


if __name__ == "__main__":
    raise SystemExit(main())
