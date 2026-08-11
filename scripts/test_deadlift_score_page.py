#!/usr/bin/env python3
"""Regression checks for the Page-4-only deadlift settlement card."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).parent
spec = importlib.util.spec_from_file_location("render_cards_v3", ROOT / "render_cards_v3.py")
renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)


PRIMARY = {
    "exercise": "deadlift",
    "findings": {"report_status": "actionable_issue", "evidence": []},
}


class DeadliftScorePageTests(unittest.TestCase):
    def test_scored_settlement_uses_only_allowed_grade_and_full_canvas(self):
        score = {
            "scorable": True, "total": 82, "grade": "A",
            "items": [
                {"id": "DL-01", "title": "杠铃轨迹", "status": "明显待改善", "detail": "出现明显二维横向漂移。"},
                {"id": "DL-02", "title": "脊柱稳定", "status": "稳定", "detail": "稳定。"},
            ],
        }
        image = renderer._deadlift_score_page(PRIMARY, None, score)
        self.assertEqual(image.size, (1080, 1440))
        self.assertIn(score["grade"], {"SS", "S", "A", "B", "C", "D"})

    def test_unscorable_page_does_not_need_or_create_drills(self):
        called = []
        original = renderer._score_training_card
        renderer._score_training_card = lambda *args: called.append(args)
        try:
            image = renderer._deadlift_score_page(
                PRIMARY, None, {"scorable": False, "unavailable_reason": "侧面姿态关键点不足，无法完成评分。"},
            )
        finally:
            renderer._score_training_card = original
        self.assertEqual(image.size, (1080, 1440))
        self.assertEqual(called, [])


if __name__ == "__main__":
    unittest.main()
