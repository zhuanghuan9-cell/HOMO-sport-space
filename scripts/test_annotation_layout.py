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

    def test_anatomy_index_labels_do_not_overlap_each_other(self):
        asset = renderer._anatomy_base(renderer.anatomy_asset_for("deadlift"))
        occupancy, _ = renderer._anatomy_occupancy(asset, renderer.ANATOMY_BOX)
        labels = renderer._place_anatomy_labels([
            {"number": "①", "name": "背阔肌｜机位一", "target": (636, 405), "colors": (renderer.base.ARCADE_PINK,)},
            {"number": "②", "name": "竖脊肌群｜机位一", "target": (670, 426), "colors": (renderer.base.ARCADE_PINK,)},
        ], occupancy, renderer.ANATOMY_BOX)
        first, second = (item["label_box"] for item in labels)
        self.assertFalse(
            max(first[0], second[0]) < min(first[2], second[2])
            and max(first[1], second[1]) < min(first[3], second[3]),
        )


if __name__ == "__main__":
    unittest.main()
