#!/usr/bin/env python3
"""Strict, automatic near-plate hub tracking for side/oblique barbell video.

It intentionally returns ``unavailable`` rather than filling a missing point.
The output is a companion JSON; it never overwrites human/card tracking data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass(frozen=True)
class Candidate:
    x: float
    y: float
    radius: float
    score: float


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def phase_points(source: dict) -> list[dict]:
    """Use only phase timing from pre-existing tracking, never its old x/y."""
    seen: dict[int, dict] = {}
    for repetition in source.get("repetitions", []):
        for point in repetition.get("bar_path", []):
            if isinstance(point, dict) and isinstance(point.get("frame"), int) and isinstance(point.get("time"), (int, float)):
                seen.setdefault(point["frame"], {"frame": point["frame"], "time": float(point["time"]), "phase": point.get("phase", "sample")})
    return [seen[key] for key in sorted(seen)]


def detect_candidates(frame: np.ndarray) -> list[Candidate]:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (7, 7), 1.5)
    height, width = gray.shape
    circles = cv2.HoughCircles(gray, cv2.HOUGH_GRADIENT, dp=1.2, minDist=max(40, min(width, height) // 10),
                               param1=100, param2=30, minRadius=max(20, min(width, height) // 28),
                               maxRadius=max(35, min(width, height) // 4))
    if circles is None:
        return []
    candidates = []
    for x, y, radius in circles[0]:
        x, y, radius = float(x), float(y), float(radius)
        # Strong circular edge evidence in a narrow annulus: plate rim/hub,
        # not red branding or a blob on an athlete's clothing.
        mask = np.zeros_like(gray)
        cv2.circle(mask, (round(x), round(y)), max(1, round(radius)), 255, 3)
        edges = cv2.Canny(gray, 70, 160)
        edge_ratio = float((edges[mask > 0] > 0).mean()) if np.any(mask > 0) else 0.0
        if edge_ratio >= .16:
            candidates.append(Candidate(x, y, radius, edge_ratio))
    return candidates


def best_track(candidates_by_frame: list[list[Candidate]]) -> list[Candidate | None]:
    """Dynamic-programming path: one similarly sized moving circular object."""
    if not candidates_by_frame or any(not row for row in candidates_by_frame):
        return [None] * len(candidates_by_frame)
    costs = [[-candidate.score for candidate in row] for row in candidates_by_frame]
    parents: list[list[int | None]] = [[None] * len(row) for row in candidates_by_frame]
    for index in range(1, len(candidates_by_frame)):
        previous, current = candidates_by_frame[index - 1], candidates_by_frame[index]
        for j, candidate in enumerate(current):
            best_value, best_parent = math.inf, None
            for i, old in enumerate(previous):
                distance = math.hypot(candidate.x - old.x, candidate.y - old.y)
                radius_change = abs(candidate.radius - old.radius) / max(old.radius, 1)
                # A background plate can be circular, but it cannot form a
                # plausible motion-continuous path through every phase.
                if distance > max(160, old.radius * 4.0) or radius_change > .35:
                    continue
                value = costs[index - 1][i] + distance / max(old.radius, 1) + radius_change * 8 - candidate.score
                if value < best_value:
                    best_value, best_parent = value, i
            if best_parent is not None:
                costs[index][j], parents[index][j] = best_value, best_parent
    def reconstruct(final_index: int) -> list[Candidate | None]:
        result: list[Candidate | None] = [None] * len(candidates_by_frame)
        for index in range(len(candidates_by_frame) - 1, -1, -1):
            result[index] = candidates_by_frame[index][final_index]
            parent = parents[index][final_index]
            if index and parent is None:
                return [None] * len(candidates_by_frame)
            final_index = parent if parent is not None else final_index
        return result

    # A stationary circle is often a rack wheel or a background plate.  Choose
    # the most continuous *moving* candidate path, then let validation reject
    # it if its movement or geometry is still not credible.  This only breaks
    # ties between already-continuous physical candidates; it never invents a
    # point or permits a jump.
    choices = []
    for final in range(len(costs[-1])):
        if math.isinf(costs[-1][final]):
            continue
        result = reconstruct(final)
        if any(point is None for point in result):
            continue
        values = [point for point in result if point]
        radius = max(float(np.median([point.radius for point in values])), 1.0)
        vertical_range = max(point.y for point in values) - min(point.y for point in values)
        # Cap the reward so an implausibly mobile object cannot win merely by
        # moving more; the continuity cost above remains the primary signal.
        score = costs[-1][final] - min(vertical_range / radius, 4.0) * 3.0
        choices.append((score, result))
    if not choices:
        return [None] * len(candidates_by_frame)
    return min(choices, key=lambda item: item[0])[1]


def validate_track(points: list[Candidate | None], phases: list[dict]) -> list[str]:
    reasons = []
    if len(points) != len(phases) or any(point is None for point in points):
        return ["至少一个关键阶段未检测到可信圆形杠片轴心"]
    values = [point for point in points if point]
    radii = [point.radius for point in values]
    median_radius = float(np.median(radii))
    if median_radius < 20 or max(abs(radius - median_radius) / median_radius for radius in radii) > .35:
        reasons.append("候选圆形尺寸不稳定，无法确认是同一杠片")
    displacements = [math.hypot(b.x - a.x, b.y - a.y) for a, b in zip(values, values[1:])]
    if displacements and max(displacements) > max(160, median_radius * 4):
        reasons.append("相邻关键阶段出现不连续跳变")
    if float(np.mean([point.score for point in values])) < .18:
        reasons.append("圆形边缘证据不足，可能不是杠片轴心")
    # A static circle is more likely background equipment than the working bar.
    if max((point.y for point in values), default=0) - min((point.y for point in values), default=0) < max(12, median_radius * .20):
        reasons.append("候选圆形在完整动作中几乎不移动，可能是背景器械")
    return reasons


def main() -> int:
    parser = argparse.ArgumentParser(description="Strict automatic near-plate hub tracker")
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--phase-tracking", required=True, type=Path, help="Tracking JSON used only for frame/time phases")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    source = json.loads(args.phase_tracking.read_text(encoding="utf-8"))
    phases = phase_points(source)
    capture = cv2.VideoCapture(str(args.video))
    fps = float(capture.get(cv2.CAP_PROP_FPS)) or 30.0
    width, height = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)), int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    candidates_by_frame = []
    for phase in phases:
        capture.set(cv2.CAP_PROP_POS_FRAMES, phase["frame"])
        ok, frame = capture.read()
        candidates_by_frame.append(detect_candidates(frame) if ok else [])
    capture.release()
    track = best_track(candidates_by_frame)
    reasons = validate_track(track, phases)
    status = "available" if not reasons else "unavailable"
    points = []
    for phase, point in zip(phases, track):
        if point is None:
            continue
        points.append({"frame": phase["frame"], "time": phase["time"], "phase": phase["phase"], "x": round(point.x, 2), "y": round(point.y, 2), "radius": round(point.radius, 2), "confidence": round(point.score, 4), "source": "hough_circle_continuity"})
    payload = {
        "schema_version": 1,
        "source_video": {"sha256": sha256(args.video), "filename": args.video.name, "image_size": [width, height], "fps": fps},
        "bar_tracking": {"status": status, "anchor": "near_plate_hub", "method": "hough_circle_continuity", "points": points if status == "available" else [], "rejection_reasons": reasons, "phase_count": len(phases)},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"status={status} points={len(points) if status == 'available' else 0}")
    for reason in reasons:
        print(f"rejected: {reason}")
    return 0 if status == "available" else 2


if __name__ == "__main__":
    raise SystemExit(main())
