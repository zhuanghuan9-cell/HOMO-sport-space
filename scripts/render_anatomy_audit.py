#!/usr/bin/env python3
"""Export enlarged Page 3 crops for anatomy-index review before delivery."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


FONT_PATH = "/System/Library/Fonts/Hiragino Sans GB.ttc"


def safe_name(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", value).strip("-") or "index"


def main() -> int:
    parser = argparse.ArgumentParser(description="Create local anatomy-index audit crops from a rendered Page 3 card.")
    parser.add_argument("--card", type=Path, required=True)
    parser.add_argument("--tracking", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    card = Image.open(args.card).convert("RGB")
    if card.size != (1080, 1440):
        parser.error("--card must be a 1080×1440 Page 3 PNG")
    data = json.loads(args.tracking.read_text(encoding="utf-8"))
    indices = ((data.get("render") or {}).get("anatomy_indices"))
    if not isinstance(indices, list) or not indices:
        parser.error("tracking JSON needs reviewed render.anatomy_indices")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    font = ImageFont.truetype(FONT_PATH, 24)
    for item in indices:
        number, muscle, view = (str(item.get(key, "")) for key in ("number", "muscle", "view"))
        target = item.get("target")
        if not (isinstance(target, list) and len(target) == 2):
            parser.error("every anatomy index needs target [x, y]")
        x, y = (int(target[0]), int(target[1]))
        crop = card.crop((max(0, x - 140), max(0, y - 110), min(1080, x + 140), min(1440, y + 110))).resize((560, 440), Image.Resampling.NEAREST)
        image = Image.new("RGB", (560, 500), "#081329")
        image.paste(crop, (0, 60))
        draw = ImageDraw.Draw(image)
        draw.text((20, 16), f"{number} {muscle}｜{view}", font=font, fill="#F4F7FF")
        image.save(args.output_dir / f"{number}-{safe_name(muscle)}.png", "PNG", optimize=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
