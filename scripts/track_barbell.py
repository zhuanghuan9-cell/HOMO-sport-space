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
    source: str = "hough_circle"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


MAX_GAP_FRAMES = 4
MIN_RAW_COVERAGE = .92


def action_samples(source: dict, fps: float) -> tuple[list[dict], set[int], dict]:
    """Return ~30fps samples for the detailed/last repetition.

    Existing paths provide *timing only*: their x/y values are intentionally
    discarded.  Every original phase frame is included even in a 60fps source
    so a required start/bottom/touch/lockout frame cannot be skipped.
    """
    repetitions = source.get("repetitions") or []
    if not repetitions:
        return [], set(), {}
    old = [point for point in (repetitions[-1].get("bar_path") or [])
           if isinstance(point, dict) and isinstance(point.get("frame"), int)]
    if len(old) < 2:
        return [], set(), {}
    start, end = min(point["frame"] for point in old), max(point["frame"] for point in old)
    phase_by_frame = {int(point["frame"]): str(point.get("phase") or "sample") for point in old}
    step = max(1, round(fps / 30.0))
    frames = set(range(start, end + 1, step)) | set(phase_by_frame)
    samples = [{"frame": frame, "time": round(frame / fps, 6), "phase": phase_by_frame.get(frame, "sample")}
               for frame in sorted(frames)]
    return samples, set(phase_by_frame), {"start_frame": start, "end_frame": end, "sample_step_frames": step}


def detect_candidates(frame: np.ndarray) -> list[Candidate]:
    # Hough on a full phone frame is needlessly expensive.  Search at a fixed
    # working size and map only the detected geometry back to source pixels.
    height0, width0 = frame.shape[:2]
    scale = min(1.0, 480.0 / max(width0, height0))
    if scale < 1.0:
        frame = cv2.resize(frame, (round(width0 * scale), round(height0 * scale)), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (7, 7), 1.5)
    height, width = gray.shape
    edges = cv2.Canny(gray, 70, 160)
    circles = cv2.HoughCircles(gray, cv2.HOUGH_GRADIENT, dp=1.2, minDist=max(40, min(width, height) // 10),
                               param1=100, param2=30, minRadius=max(20, min(width, height) // 28),
                               maxRadius=max(35, min(width, height) // 2))
    candidates = []
    for x, y, radius in circles[0] if circles is not None else []:
        source_x, source_y, source_radius = float(x / scale), float(y / scale), float(radius / scale)
        # Strong circular edge evidence in a narrow annulus: plate rim/hub,
        # not red branding or a blob on an athlete's clothing.
        mask = np.zeros_like(gray)
        cv2.circle(mask, (round(x), round(y)), max(1, round(radius)), 255, 3)
        edge_ratio = float((edges[mask > 0] > 0).mean()) if np.any(mask > 0) else 0.0
        if edge_ratio >= .08:
            candidates.append(Candidate(source_x, source_y, source_radius, edge_ratio, "hough_circle"))
    # A plate filmed from a slightly oblique angle is an ellipse, not a true
    # circle.  Recover its geometric centre from a fitted rim contour instead
    # of losing the whole path when Hough's circular assumption is too strict.
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    min_axis, max_axis = max(20, min(width, height) // 28), max(35, min(width, height) // 2)
    for contour in contours:
        if len(contour) < 20:
            continue
        (x, y), (axis_a, axis_b), _ = cv2.fitEllipse(contour)
        minor, major = sorted((axis_a, axis_b))
        if not (min_axis <= minor / 2 <= max_axis and major / 2 <= max_axis and minor / major >= .45):
            continue
        mask = np.zeros_like(gray)
        cv2.ellipse(mask, ((round(x), round(y)), (round(axis_a), round(axis_b)), 0), 255, 2)
        edge_ratio = float((edges[mask > 0] > 0).mean()) if np.any(mask > 0) else 0.0
        if edge_ratio >= .10:
            candidate = Candidate(float(x / scale), float(y / scale), float((minor / 2) / scale), edge_ratio, "ellipse_rim")
            if not any(math.hypot(candidate.x - old.x, candidate.y - old.y) < max(12, candidate.radius * .25) for old in candidates):
                candidates.append(candidate)
    return candidates


def best_track(candidates_by_frame: list[list[Candidate]]) -> list[Candidate | None]:
    """Find one plate through a full action span without inventing points.

    A candidate may bridge at most four missing samples.  The bridge is only a
    *selection* rule: the absent frames remain ``None`` raw observations and
    can later be rendered as a clearly visual-only smoothing segment.
    """
    if not candidates_by_frame or not candidates_by_frame[0] or not candidates_by_frame[-1]:
        return [None] * len(candidates_by_frame)
    costs: list[list[float]] = [[math.inf] * len(row) for row in candidates_by_frame]
    parents: list[list[tuple[int, int] | None]] = [[None] * len(row) for row in candidates_by_frame]
    for j, candidate in enumerate(candidates_by_frame[0]):
        costs[0][j] = -candidate.score
    for index in range(1, len(candidates_by_frame)):
        for j, candidate in enumerate(candidates_by_frame[index]):
            best_value, best_parent = math.inf, None
            for previous_index in range(max(0, index - MAX_GAP_FRAMES - 1), index):
                delta_frames = index - previous_index
                # A bridge is permitted only across genuinely detector-empty
                # frames.  Never skip an available observation just because a
                # longer jump has a lower mathematical cost.
                if delta_frames > 1 and any(candidates_by_frame[middle] for middle in range(previous_index + 1, index)):
                    continue
                for i, old in enumerate(candidates_by_frame[previous_index]):
                    if math.isinf(costs[previous_index][i]):
                        continue
                    distance = math.hypot(candidate.x - old.x, candidate.y - old.y)
                    radius_change = abs(candidate.radius - old.radius) / max(old.radius, 1)
                    if distance > max(80 * delta_frames, old.radius * 1.5 * delta_frames) or radius_change > .35:
                        continue
                    gap_penalty = (delta_frames - 1) * .55
                    value = costs[previous_index][i] + distance / max(old.radius * delta_frames, 1) + radius_change * 8 + gap_penalty - candidate.score
                    if value < best_value:
                        best_value, best_parent = value, (previous_index, i)
            if best_parent is not None:
                costs[index][j], parents[index][j] = best_value, best_parent

    def reconstruct(final_index: int) -> list[Candidate | None]:
        result: list[Candidate | None] = [None] * len(candidates_by_frame)
        index = len(candidates_by_frame) - 1
        while True:
            result[index] = candidates_by_frame[index][final_index]
            parent = parents[index][final_index]
            if parent is None:
                return result if index == 0 else [None] * len(candidates_by_frame)
            index, final_index = parent

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


def template_tracks(frames: list[np.ndarray | None], candidates_by_frame: list[list[Candidate]]) -> list[list[Candidate | None]]:
    """Track candidate-seeded plate templates through rim-detector dropouts.

    CSRT is not a manual correction or a coordinate guess: each result comes
    from the next source frame's visual template match.  It is used only after
    circle/ellipse continuity has failed, and it still must pass every normal
    geometry, movement, coverage and critical-phase gate below.
    """
    if not frames or frames[0] is None or not hasattr(cv2, "TrackerCSRT_create"):
        return []
    seeds = sorted(
        (candidate for candidate in candidates_by_frame[0] if 35 <= candidate.radius <= 180),
        key=lambda candidate: candidate.score,
        reverse=True,
    )[:8]
    results = []
    height, width = frames[0].shape[:2]
    for seed in seeds:
        side = min(seed.radius * 2.4, width, height)
        x = min(max(seed.x - side / 2, 0), width - side)
        y = min(max(seed.y - side / 2, 0), height - side)
        tracker = cv2.TrackerCSRT_create()
        initialized = tracker.init(frames[0], (round(x), round(y), round(side), round(side)))
        if initialized is False:
            continue
        sequence: list[Candidate | None] = [Candidate(seed.x, seed.y, seed.radius, seed.score, "csrt_plate_template")]
        for frame in frames[1:]:
            if frame is None:
                sequence.append(None)
                continue
            ok, box = tracker.update(frame)
            if not ok:
                sequence.append(None)
                continue
            bx, by, bw, bh = box
            sequence.append(Candidate(float(bx + bw / 2), float(by + bh / 2), float(min(bw, bh) / 2), seed.score, "csrt_plate_template"))
        results.append(sequence)
    return results


def best_template_track(frames: list[np.ndarray | None], candidates_by_frame: list[list[Candidate]], samples: list[dict], required_frames: set[int]) -> list[Candidate | None]:
    choices = []
    for track in template_tracks(frames, candidates_by_frame):
        if validate_track(track, samples, required_frames):
            continue
        # Re-anchor the visual tracker whenever circle/ellipse evidence is
        # available at a required phase.  A template that drifts onto a torso
        # or rack will fail this independently detected geometry agreement.
        checks = 0
        matches = 0
        for index, sample in enumerate(samples):
            if sample["frame"] not in required_frames or track[index] is None or not candidates_by_frame[index]:
                continue
            checks += 1
            nearest = min(math.hypot(candidate.x - track[index].x, candidate.y - track[index].y) for candidate in candidates_by_frame[index])
            if nearest <= max(45, track[index].radius * .6):
                matches += 1
        if checks < 3 or matches / checks < .75:
            continue
        values = [point for point in track if point]
        vertical_range = max(point.y for point in values) - min(point.y for point in values)
        # Prefer the continuously tracked candidate that exhibits the expected
        # non-static lift movement.  Validation has already rejected jumps.
        choices.append((-vertical_range, track))
    return min(choices, key=lambda item: item[0])[1] if choices else [None] * len(samples)


def _longest_gap(points: list[Candidate | None]) -> int:
    longest = current = 0
    for point in points:
        current = current + 1 if point is None else 0
        longest = max(longest, current)
    return longest


def validate_track(points: list[Candidate | None], samples: list[dict], required_frames: set[int]) -> list[str]:
    reasons = []
    if len(points) != len(samples):
        return ["杠铃追踪采样长度不完整"]
    required = {sample["frame"] for sample, point in zip(samples, points) if sample["frame"] in required_frames and point is not None}
    if required != required_frames:
        reasons.append("至少一个关键阶段未检测到可信圆形杠片轴心")
    coverage = sum(point is not None for point in points) / max(1, len(points))
    if coverage < MIN_RAW_COVERAGE:
        reasons.append("真实杠片轴心覆盖不足，无法形成可信完整轨迹")
    if _longest_gap(points) > MAX_GAP_FRAMES:
        reasons.append("连续缺失超过短遮挡容限")
    values = [point for point in points if point]
    if len(values) < 2:
        return reasons + ["可信杠片轴心点不足"]
    radii = [point.radius for point in values]
    median_radius = float(np.median(radii))
    if median_radius < 20 or max(abs(radius - median_radius) / median_radius for radius in radii) > .35:
        reasons.append("候选圆形尺寸不稳定，无法确认是同一杠片")
    indexed = [(index, point) for index, point in enumerate(points) if point]
    displacements = [(b_index - a_index, math.hypot(b.x - a.x, b.y - a.y)) for (a_index, a), (b_index, b) in zip(indexed, indexed[1:])]
    if displacements and any(distance > max(80 * delta, median_radius * 1.5 * delta) for delta, distance in displacements):
        reasons.append("相邻关键阶段出现不连续跳变")
    if float(np.mean([point.score for point in values])) < .09:
        reasons.append("圆形边缘证据不足，可能不是杠片轴心")
    # A static circle is more likely background equipment than the working bar.
    if max((point.y for point in values), default=0) - min((point.y for point in values), default=0) < max(12, median_radius * .20):
        reasons.append("候选圆形在完整动作中几乎不移动，可能是背景器械")
    return reasons


def display_points(raw: list[Candidate | None], samples: list[dict]) -> list[dict]:
    """Create visual-only smoothing, retaining every raw/inferred distinction."""
    output: list[dict] = []
    raw_indices = [index for index, point in enumerate(raw) if point]
    for index, (sample, point) in enumerate(zip(samples, raw)):
        record = {"frame": sample["frame"], "time": sample["time"], "phase": sample["phase"]}
        if point:
            neighbours = [raw[other] for other in range(max(0, index - 2), min(len(raw), index + 3)) if raw[other] is not None]
            # Gentle weighted smoothing is presentation-only.  Raw x/y remains
            # separately available for all metrics and report conclusions.
            x = sum(item.x for item in neighbours) / len(neighbours)
            y = sum(item.y for item in neighbours) / len(neighbours)
            record.update({"x": round(x, 2), "y": round(y, 2), "display_source": "smoothed_raw"})
        else:
            before = max((other for other in raw_indices if other < index), default=None)
            after = min((other for other in raw_indices if other > index), default=None)
            if before is None or after is None or after - before - 1 > MAX_GAP_FRAMES:
                continue
            ratio = (index - before) / (after - before)
            a, b = raw[before], raw[after]
            record.update({"x": round(a.x + (b.x - a.x) * ratio, 2), "y": round(a.y + (b.y - a.y) * ratio, 2), "display_source": "smoothed_gap"})
        output.append(record)
    return output


def extracted_frame(frames_dir: Path, frame: int) -> np.ndarray | None:
    """Read the exact already-extracted source frame, never a seek estimate."""
    matches = sorted(frames_dir.glob(f"frame_{frame:04d}_*"))
    if not matches:
        return None
    return cv2.imread(str(matches[0]), cv2.IMREAD_COLOR)


def main() -> int:
    parser = argparse.ArgumentParser(description="Strict automatic near-plate hub tracker")
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--phase-tracking", required=True, type=Path, help="Tracking JSON used only for frame/time phases")
    parser.add_argument("--frames-dir", type=Path, help="Optional exact Swift-extracted frames; preferred over codec seeking")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    source = json.loads(args.phase_tracking.read_text(encoding="utf-8"))
    capture = cv2.VideoCapture(str(args.video))
    fps = float(capture.get(cv2.CAP_PROP_FPS)) or 30.0
    width, height = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)), int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    samples, required_frames, action_span = action_samples(source, fps)
    candidates_for_frame = {}
    frames_for_frame = {}
    if args.frames_dir:
        if not args.frames_dir.is_dir():
            parser.error(f"frames directory not found: {args.frames_dir}")
        for sample in samples:
            frame = extracted_frame(args.frames_dir, sample["frame"])
            frames_for_frame[sample["frame"]] = frame
            candidates_for_frame[sample["frame"]] = detect_candidates(frame) if frame is not None else []
    else:
        # Decode the action span once in chronological order; seeking
        # separately for every 30fps sample is much slower and codec-dependent.
        wanted = {sample["frame"] for sample in samples}
        capture.set(cv2.CAP_PROP_POS_FRAMES, samples[0]["frame"] if samples else 0)
        frame_number = samples[0]["frame"] if samples else 0
        end_frame = samples[-1]["frame"] if samples else -1
        while frame_number <= end_frame:
            ok, frame = capture.read()
            if not ok:
                break
            if frame_number in wanted:
                frames_for_frame[frame_number] = frame
                candidates_for_frame[frame_number] = detect_candidates(frame)
            frame_number += 1
    candidates_by_frame = [candidates_for_frame.get(sample["frame"], []) for sample in samples]
    source_frames = [frames_for_frame.get(sample["frame"]) for sample in samples]
    capture.release()
    track = best_track(candidates_by_frame)
    reasons = validate_track(track, samples, required_frames)
    method = "circle_ellipse_continuity"
    if reasons:
        template = best_template_track(source_frames, candidates_by_frame, samples, required_frames)
        template_reasons = validate_track(template, samples, required_frames)
        if not template_reasons:
            track, reasons, method = template, [], "circle_ellipse_seeded_csrt_continuity"
    status = "available" if not reasons else "unavailable"
    points = []
    for sample, point in zip(samples, track):
        if point is None:
            continue
        points.append({"frame": sample["frame"], "time": sample["time"], "phase": sample["phase"], "x": round(point.x, 2), "y": round(point.y, 2), "radius": round(point.radius, 2), "confidence": round(point.score, 4), "source": point.source})
    payload = {
        "schema_version": 1,
        "source_video": {"sha256": sha256(args.video), "filename": args.video.name, "image_size": [width, height], "fps": fps},
        "bar_tracking": {"status": status, "anchor": "near_plate_hub", "method": method, "sample_rate_fps": round(fps / action_span.get("sample_step_frames", 1), 2) if action_span else 0, "action_span": action_span, "raw_points": points if status == "available" else [], "display_points": display_points(track, samples) if status == "available" else [], "rejection_reasons": reasons, "phase_count": len(required_frames)},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"status={status} points={len(points) if status == 'available' else 0}")
    for reason in reasons:
        print(f"rejected: {reason}")
    return 0 if status == "available" else 2


if __name__ == "__main__":
    raise SystemExit(main())
