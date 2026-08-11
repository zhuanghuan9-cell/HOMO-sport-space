#!/usr/bin/env python3
"""Ensure the reusable Skill documents the Page-4 score HUD contract."""
from pathlib import Path
import unittest


SKILL = Path(__file__).parents[1] / "SKILL.md"


class ScoreSkillContractTests(unittest.TestCase):
    def test_deadlift_score_hud_requires_two_equal_centered_columns(self):
        document = SKILL.read_text(encoding="utf-8")
        self.assertIn("双列结算布局", document)
        self.assertIn("总分列与评级列等宽", document)
        self.assertIn("总分组合（数字＋分）", document)
        self.assertIn("Page 4", document)


if __name__ == "__main__":
    unittest.main()
