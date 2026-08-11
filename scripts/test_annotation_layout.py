#!/usr/bin/env python3
"""Fast geometry tests for the no-text-over-subject annotation gate."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

from PIL import Image, ImageDraw

ROOT = Path(__file__).parent
spec = importlib.util.spec_from_file_location("renderer", ROOT / "render_cards_v3.py")
renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)


class AnnotationLayoutTests(unittest.TestCase):
    def setUp(self):
        self.photo = (0, 0, 400, 400)
        self.mask = Image.new("L", (400, 400), 0)
        # Central athlete and a horizontal bar.  Corners remain safe.
        draw = ImageDraw.Draw(self.mask)
        draw.rounded_rectangle((130, 105, 270, 370), radius=30, fill=255)
        draw.rectangle((45, 190, 355, 214), fill=255)

    def test_label_box_has_zero_subject_or_bar_overlap(self):
        box, font_size, text = renderer._safe_label_box(
            self.mask, self.photo, (200, 200), "下降时杠铃轻微屏幕前移", 1,
        )
        self.assertGreaterEqual(font_size, 20)
        self.assertTrue(text)
        self.assertIsNone(self.mask.crop(box).getbbox())

    def test_rejects_when_entire_content_is_occupied(self):
        mask = Image.new("L", (400, 400), 255)
        with self.assertRaisesRegex(ValueError, "safe background"):
            renderer._safe_label_box(mask, self.photo, (200, 200), "测试", 1)

    def test_label_stays_inside_actual_video_box(self):
        box, _, _ = renderer._safe_label_box(self.mask, self.photo, (200, 200), "两端同步上升", -1)
        self.assertTrue(renderer._content_contains(box, self.photo, 16))


if __name__ == "__main__":
    unittest.main()
