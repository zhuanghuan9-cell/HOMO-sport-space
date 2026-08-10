#!/usr/bin/env python3
"""Regression checks for the no-forced-prescription stable-report path."""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


validator = load("validate_tracking")
renderer = load("render_cards_v3")


def stable_tracking() -> dict:
    return {
        "exercise": "bench_press", "view": "side", "image_size": [720, 1280], "plate_diameter_px": 180,
        "render": {"analysis_mode": "bar_path_only"},
        "repetitions": [{"rep": 1, "bar_path": [
            {"frame": 1, "time": .03, "x": 300, "y": 400, "phase": "start"},
            {"frame": 2, "time": .07, "x": 301, "y": 440, "phase": "descent"},
            {"frame": 3, "time": .10, "x": 302, "y": 480, "phase": "descent"},
            {"frame": 4, "time": .13, "x": 303, "y": 500, "phase": "touch"},
            {"frame": 5, "time": .17, "x": 302, "y": 460, "phase": "press"},
            {"frame": 6, "time": .20, "x": 300, "y": 400, "phase": "lockout"},
        ]}],
        "findings": {
            "report_status": "stable",
            "evidence": [{"id": "stable.control", "title": "下放与回程可控", "view": "view_one", "page": 1}],
            "primary": {"title": "动作稳定", "detail": "未见明确待改善项。", "no_muscle_direction": True},
            "improve": [], "good": [{"title": "做得好", "detail": "控制稳定。"}], "unavailable": [],
        },
    }


class StableReportTests(unittest.TestCase):
    def test_stable_tracking_needs_no_training_target_or_plan(self):
        self.assertEqual(validator.validate(stable_tracking()), [])

    def test_stable_tracking_rejects_forced_drill_and_muscle_target(self):
        data = stable_tracking()
        data["findings"]["primary"]["muscle_targets"] = [{"name": "胸大肌", "role": "不应被写入"}]
        data["plan"] = {"technical": {"name": "常规卧推（每次触胸停稳）", "dose": "3组×4次", "cue": "触胸停稳"}}
        errors = validator.validate(data)
        self.assertTrue(any("stable report" in item for item in errors))

    def test_actionable_tracking_still_requires_evidence_target_and_linked_plan(self):
        data = stable_tracking()
        data["findings"]["report_status"] = "actionable_issue"
        errors = validator.validate(data)
        self.assertTrue(any("training_target" in item for item in errors))

    def test_stable_reports_render_the_positive_closing_card(self):
        image = renderer._training_page(stable_tracking())
        self.assertEqual(image.size, (1080, 1440))

    def test_mixed_report_keeps_primary_linked_prescription(self):
        primary = stable_tracking()
        primary["findings"]["report_status"] = "actionable_issue"
        primary["findings"]["evidence"][0]["training_target"] = "触胸稳定"
        primary["findings"]["primary"]["title"] = "触胸需要停稳"
        primary["findings"]["primary"]["detail"] = "触胸阶段需要更稳定。"
        primary["plan"] = {
            key: {"name": name, "dose": "3组×4次", "cue": "触胸停稳", "source_ids": ["stable.control"], "target_label": "针对：触胸稳定"}
            for key, name in {
                "technical": "常规卧推（每次触胸停稳）",
                "correction": "暂停卧推（触胸停1秒）",
                "assistance": "双手哑铃农夫走",
            }.items()
        }
        secondary = stable_tracking()
        secondary["view"] = "foot_end"
        secondary["findings"]["evidence"][0]["id"] = "stable.level"
        self.assertFalse(renderer._report_is_stable(primary, secondary))
        renderer.validate_training_links(primary, secondary)
        self.assertEqual(renderer._training_items(primary, secondary)[2][1]["source_ids"], ["stable.control"])


if __name__ == "__main__":
    unittest.main()
