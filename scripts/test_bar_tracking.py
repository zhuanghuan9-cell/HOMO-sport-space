#!/usr/bin/env python3
"""Regression checks for strict bar-hub tracking and report rejection."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


tracker = load("track_barbell")
composer = load("compose_bar_tracking")


def candidate(x, y, radius=52, score=.42):
    return tracker.Candidate(x, y, radius, score)


def source():
    return {
        "exercise": "squat", "image_size": [720, 1280], "plate_diameter_px": 280,
        "source_video": {"sha256": "a" * 64},
        "repetitions": [{"bar_path": [
            {"frame": 10, "time": .33, "x": 300, "y": 400, "phase": "start"},
            {"frame": 20, "time": .67, "x": 300, "y": 480, "phase": "bottom"},
            {"frame": 30, "time": 1.0, "x": 300, "y": 400, "phase": "lockout"},
        ]}],
        "findings": {"report_status": "actionable_issue", "evidence": [{
            "id": "view_one.bar_forward_drift", "title": "下降时杠铃轻微屏幕前移",
            "view": "view_one", "page": 1, "training_target": "下降控制",
        }], "improve": [{"title": "屏幕前移", "detail": "二维趋势"}], "primary": {
            "title": "下降时杠铃轻微屏幕前移", "detail": "二维趋势", "muscle_targets": [{"name": "股四头肌群", "role": "控制"}],
        }},
        "plan": {"technical": {"name": "常规深蹲（每次站稳重置）", "dose": "3组×3次", "cue": "压稳", "source_ids": ["view_one.bar_forward_drift"], "target_label": "针对：下降控制"}},
    }


def test_candidate_continuity():
    rows = [
        [candidate(100, 200), candidate(500, 100)],
        [candidate(102, 270), candidate(500, 100)],
        [candidate(100, 210), candidate(500, 100)],
    ]
    result = tracker.best_track(rows)
    assert all(point is not None for point in result)
    assert max(point.y for point in result) - min(point.y for point in result) >= 60
    samples = [{"frame": frame} for frame in (10, 20, 30)]
    assert not tracker.validate_track(result, samples, {10, 20, 30})


def test_squat_requires_only_semantic_reanchors_not_every_legacy_sample():
    data = source()
    data["repetitions"][0]["bar_path"] = [
        {"frame": frame, "time": frame / 30, "x": 300, "y": 400, "phase": phase}
        for frame, phase in ((10, "start"), (12, "descent"), (14, "descent"), (20, "bottom"),
                             (22, "ascent"), (24, "ascent"), (30, "lockout"))
    ]
    _, required, _ = tracker.action_samples(data, 30)
    assert required == {10, 20, 22, 30}


def test_semantic_reanchors_accept_nearby_real_frame_not_every_legacy_tick():
    samples = [{"frame": frame} for frame in (10, 12, 20, 22, 30, 38)]
    points = [None, candidate(100, 210), candidate(100, 260), None, candidate(100, 230), candidate(100, 200)]
    # Frame 12 is a real nearby start re-anchor for semantic frame 10; the
    # absent legacy tick at 22 must not invalidate an otherwise verified rep.
    assert tracker.semantic_reanchors_present(points, samples, {10, 20, 22, 30})
    rows = [[candidate(100, 210)] if point else [] for point in points]
    assert 12 in tracker.semantic_reanchor_frames(points, samples, {10, 20, 22, 30}, rows)


def test_working_plate_association_rejects_static_plate_far_from_lifter():
    rows = [
        [candidate(210, 200), candidate(680, 650)],
        [candidate(210, 260), candidate(680, 650)],
        [candidate(210, 210), candidate(680, 650)],
    ]
    anchors = [tracker.PoseAnchor(190, 220, 120), tracker.PoseAnchor(190, 280, 120), tracker.PoseAnchor(190, 230, 120)]
    filtered, audit = tracker.associate_working_candidates(rows, anchors)
    assert all(len(row) == 1 for row in filtered)
    assert [row[0].x for row in filtered] == [210, 210, 210]
    assert all(item["candidate_count"] == 1 for item in audit)


def test_reject_static_background():
    points = [candidate(500, 100), candidate(500, 101), candidate(500, 100)]
    reasons = tracker.validate_track(points, [{"frame": frame} for frame in (10, 20, 30)], {10, 20, 30})
    assert any("背景器械" in reason for reason in reasons)


def test_reject_size_jump_and_missing():
    samples = [{"frame": frame} for frame in (10, 20, 30)]
    assert any("尺寸不稳定" in reason for reason in tracker.validate_track(
        [candidate(100, 200, 50), candidate(102, 270, 90), candidate(100, 210, 50)], samples, {10, 20, 30}))
    assert tracker.validate_track([candidate(1, 1), None], samples[:2], {10, 20})


def test_short_gap_is_visual_only_and_not_raw_evidence():
    raw = [candidate(100 + index, 200 + index * 2) for index in range(100)]
    for index in range(40, 44):
        raw[index] = None
    samples = [{"frame": 10 + index, "time": index / 30, "phase": "sample"} for index in range(100)]
    display = tracker.display_points(raw, samples)
    assert len(display) == 100
    gap = next(item for item in display if item["frame"] == 51)
    assert gap["display_source"] == "smoothed_gap"
    # The display can bridge it, but the missing observation remains absent
    # from raw evidence.  The full action still clears the strict coverage
    # gate because the gap is short and no critical phase is missing.
    assert not tracker.validate_track(raw, samples, {10, 60, 109})


def test_unavailable_removes_path_conclusions_and_training():
    data = source()
    bar = {"source_video": {"sha256": "a" * 64}, "bar_tracking": {
        "status": "unavailable", "points": [], "rejection_reasons": ["候选跳变"],
    }}
    result = composer.compose(data, bar)
    assert result["findings"]["report_status"] == "stable"
    assert result["findings"]["primary"]["no_muscle_direction"] is True
    assert "evidence" not in result["findings"]
    assert not result["plan"]
    assert result["render"]["analysis_mode"] == "bar_path_unavailable"


def test_available_replaces_old_points_and_refuses_hash_mismatch():
    data = source()
    bar = {"source_video": {"sha256": "a" * 64}, "bar_tracking": {"status": "available", "raw_points": [
        {"frame": 10, "time": .33, "phase": "start", "x": 410, "y": 220},
        {"frame": 20, "time": .67, "phase": "bottom", "x": 412, "y": 350},
        {"frame": 30, "time": 1, "phase": "lockout", "x": 410, "y": 220},
    ]}}
    result = composer.compose(data, bar)
    assert result["repetitions"][-1]["bar_path"][0]["x"] == 410
    try:
        composer.compose(data, {"source_video": {"sha256": "b" * 64}, "bar_tracking": bar["bar_tracking"]})
    except ValueError:
        pass
    else:
        raise AssertionError("source hash mismatch must be rejected")


if __name__ == "__main__":
    for name, value in sorted(globals().items()):
        if name.startswith("test_"):
            value()
            print(f"ok {name}")
