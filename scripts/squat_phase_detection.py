#!/usr/bin/env python3
"""Camera-normalized phase detection for ordinary barbell squats.

The detector deliberately separates *finding a motion cycle* from evaluating
its quality.  It never uses fixed centimetres/pixels: all vertical movement is
normalised by the setup hip-to-knee distance supplied with each sample.
"""
from __future__ import annotations

from statistics import median


def _delta(a, b, key):
    return float(b[key]) - float(a[key])


def _duration(samples, start, end):
    return float(samples[end]["time"]) - float(samples[start]["time"])


def _run(samples, start, predicate, minimum=3):
    index = start
    while index < len(samples) and predicate(index):
        index += 1
    return index - start


def _phase_record(name, samples, start, end, confidence=0.9):
    return {
        "phase": name,
        "start_frame": int(samples[start]["frame"]), "end_frame": int(samples[end]["frame"]),
        "start_time": round(float(samples[start]["time"]), 4),
        "end_time": round(float(samples[end]["time"]), 4),
        "confidence": confidence,
        "signals": ["hip_y", "knee_angle", "bar_y"],
    }


def detect_squat_phases(samples, *, setup_seconds=0.5, pause_seconds=0.4):
    """Return one representative squat cycle from ordered normalised samples.

    Required per sample: frame, time, hip_y, knee_angle, bar_y,
    hip_knee_distance, ankle_x.  Y grows downward in image coordinates.
    """
    required = {"frame", "time", "hip_y", "knee_angle", "bar_y", "hip_knee_distance", "ankle_x"}
    if len(samples) < 8 or any(not required.issubset(sample) for sample in samples):
        return {"available": False, "reason": "姿态关键点不足，无法识别深蹲阶段。", "phases": []}
    samples = sorted(samples, key=lambda item: item["time"])
    scale = median(max(float(item["hip_knee_distance"]), 1.0) for item in samples[:min(15, len(samples))])
    # A large ankle translation relative to the visible thigh is a walk/step
    # or camera movement, not a squat repetition.
    ankle_span = max(float(item["ankle_x"]) for item in samples) - min(float(item["ankle_x"]) for item in samples)
    if ankle_span > scale * .35:
        return {"available": False, "reason": "脚踝横向移动明显，可能是走步或机位变化。", "phases": []}

    hip_step = max(scale * .008, 0.5)
    bar_step = max(scale * .006, 0.5)
    knee_step = 1.0
    setup_start = 0
    setup_end = 0
    for index in range(1, len(samples)):
        if (abs(_delta(samples[index - 1], samples[index], "hip_y")) <= hip_step and
                abs(_delta(samples[index - 1], samples[index], "bar_y")) <= bar_step and
                abs(_delta(samples[index - 1], samples[index], "knee_angle")) <= knee_step):
            setup_end = index
            if _duration(samples, setup_start, setup_end) >= setup_seconds:
                break
        else:
            setup_start = index
            setup_end = index
    has_setup = _duration(samples, setup_start, setup_end) >= setup_seconds
    search_from = setup_end if has_setup else 1

    def descending(index):
        previous, current = samples[index - 1], samples[index]
        return _delta(previous, current, "hip_y") >= hip_step and _delta(previous, current, "knee_angle") <= -knee_step

    descent_start = None
    for index in range(max(1, search_from), len(samples) - 2):
        if _run(samples, index, descending, 3) >= 3:
            descent_start = index - 1
            break
    if descent_start is None:
        return {"available": False, "reason": "髋部未出现持续下移与膝角同步减小，未识别为深蹲。", "phases": []}

    def ascending(index):
        previous, current = samples[index - 1], samples[index]
        return _delta(previous, current, "hip_y") <= -hip_step and _delta(previous, current, "knee_angle") >= knee_step

    ascent_start = None
    for index in range(descent_start + 3, len(samples) - 2):
        if _run(samples, index, ascending, 3) >= 3:
            ascent_start = index - 1
            break
    if ascent_start is None:
        return {"available": False, "reason": "识别到下蹲，但未找到持续上升阶段。", "phases": []}
    bottom_index = max(range(descent_start, ascent_start + 1), key=lambda index: float(samples[index]["hip_y"]))

    bottom_start = bottom_index
    while bottom_start > descent_start and abs(float(samples[bottom_start]["hip_y"]) - float(samples[bottom_index]["hip_y"])) <= hip_step:
        bottom_start -= 1
    bottom_end = bottom_index
    while bottom_end < ascent_start and abs(float(samples[bottom_end]["hip_y"]) - float(samples[bottom_index]["hip_y"])) <= hip_step:
        bottom_end += 1
    pause = _duration(samples, bottom_start, bottom_end) >= pause_seconds

    start_hip = float(samples[descent_start]["hip_y"])
    start_knee = float(samples[descent_start]["knee_angle"])
    lockout_start = None
    for index in range(ascent_start + 2, len(samples)):
        close_to_setup = (abs(float(samples[index]["hip_y"]) - start_hip) <= scale * .10 and
                          float(samples[index]["knee_angle"]) >= start_knee - 8)
        if close_to_setup:
            stable_end = index
            while stable_end + 1 < len(samples):
                previous, current = samples[stable_end], samples[stable_end + 1]
                if abs(_delta(previous, current, "hip_y")) > hip_step or abs(_delta(previous, current, "bar_y")) > bar_step:
                    break
                stable_end += 1
            if _duration(samples, index, stable_end) >= setup_seconds:
                lockout_start = index
                lockout_end = stable_end
                break

    phases = []
    records = []
    if has_setup:
        phases.append("setup"); records.append(_phase_record("setup", samples, setup_start, setup_end))
    phases.append("descent"); records.append(_phase_record("descent", samples, descent_start, max(descent_start, bottom_start)))
    phases.append("bottom"); records.append(_phase_record("bottom", samples, bottom_start, bottom_end))
    if pause:
        phases.append("pause_bottom"); records.append(_phase_record("pause_bottom", samples, bottom_start, bottom_end))
    phases.append("ascent"); records.append(_phase_record("ascent", samples, min(ascent_start, bottom_end), lockout_start or len(samples) - 1))
    if lockout_start is not None:
        phases.append("lockout"); records.append(_phase_record("lockout", samples, lockout_start, lockout_end))
    return {
        "available": True, "reason": None, "phases": phases, "phase_records": records,
        "pause_bottom": pause, "scale_px": round(scale, 3),
        "representative_frames": {
            "setup": int(samples[setup_end]["frame"]) if has_setup else None,
            "descent": int(samples[descent_start]["frame"]), "bottom": int(samples[bottom_index]["frame"]),
            "ascent": int(samples[ascent_start]["frame"]), "lockout": int(samples[lockout_start]["frame"]) if lockout_start is not None else None,
        },
    }
