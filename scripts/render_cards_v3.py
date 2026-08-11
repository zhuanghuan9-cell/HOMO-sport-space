#!/usr/bin/env python3
"""Four-page, view-first arcade cards for powerlifting video reviews.

This renderer intentionally treats each camera as an independent source of
evidence.  A second camera enriches the report; it never changes a conclusion
drawn from the first one.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

from compose_bar_tracking import compose as compose_bar_tracking
from deadlift_scoring import score_deadlift

_BASE_SPEC = importlib.util.spec_from_file_location("powerlifting_render_base", Path(__file__).with_name("render_cards.py"))
base = importlib.util.module_from_spec(_BASE_SPEC)
_BASE_SPEC.loader.exec_module(base)


SIZE = base.SIZE
PAGE_NAMES = ("01-view-one.png", "02-view-two.png", "03-muscle-focus.png", "04-training-plan.png")
PAGE_TITLES = {
    1: "机位一｜这个角度看到的问题",
    2: "机位二｜另一个角度看到的问题",
    3: "相关肌群｜分别优先加强什么",
    4: "一次训练｜下一次直接怎么练",
}
SKILL_ROOT = Path(__file__).resolve().parent.parent
DEADLIFT_ASSET = SKILL_ROOT / "assets" / "canonical-anatomy-front-back.png"
HUD_X_BOUNDS = (52, 1028)
# Every full-width content component shares this exact outer grid.  Individual
# cards may differ in height, but their left and right rails must not drift.
FULL_X_BOUNDS = HUD_X_BOUNDS
STRUCTURAL_RADIUS = 18
STRUCTURAL_BORDER = 4
STRUCTURAL_GAP = 24
HEADER_BOX = (52, 44, 1028, 152)
SUMMARY_BOX = (52, 176, 1028, 318)
MUSCLE_SUMMARY_BOX = None
PHOTO_BOXES = ((52, 342, 524, 968), (556, 342, 1028, 968))
ANATOMY_BOX = (52, 176, 1028, 782)
ANALYSIS_BOX = (52, 806, 1028, 1196)
TRAINING_BOXES = ((52, 342, 1028, 604), (52, 628, 1028, 890), (52, 914, 1028, 1176))
SCORE_BOX = (52, 176, 1028, 730)
SCORE_TRAINING_BOXES = ((52, 790, 1028, 954), (52, 978, 1028, 1142), (52, 1166, 1028, 1330))
# Keep the conclusion band as a structural HUD outline: the grid background
# remains visible inside it, matching the lightweight framed bars elsewhere.
SUMMARY_PANEL_FILL = None
SUMMARY_PANEL_STYLE = "rounded_outline"
ANATOMY_PANEL_FILL = None
ANATOMY_PANEL_STYLE = "rounded_outline"
HEADER_ICON = "◆"

# Source-space safe zones on assets/canonical-anatomy-front-back.png (1536×1024).
# These deliberately cover the central muscle belly rather than every visible
# fibre: an index near a joint, an edge, or a neighbouring structure fails.
# A new named target must add a reviewed safe zone here before it can render.
CANONICAL_MUSCLE_SAFE_ZONES = {
    "胸大肌": [
        [(432, 267), (492, 258), (514, 293), (482, 326), (431, 306)],
        [(592, 267), (532, 258), (510, 293), (542, 326), (593, 306)],
    ],
    "前臂屈肌群": [
        [(365, 448), (404, 444), (411, 520), (382, 536)],
        [(659, 448), (620, 444), (613, 520), (642, 536)],
    ],
    "中下斜方肌": [[(1024, 286), (978, 329), (1024, 408), (1070, 329)]],
    "肱三头肌": [
        [(1136, 358), (1172, 369), (1170, 430), (1142, 439)],
        [(900, 358), (864, 369), (866, 430), (894, 439)],
    ],
    "背阔肌": [
        [(885, 352), (948, 364), (956, 411), (911, 437), (873, 396)],
        [(1163, 352), (1100, 364), (1092, 411), (1137, 437), (1175, 396)],
    ],
    "竖脊肌群": [
        [(976, 351), (1008, 352), (1007, 456), (978, 456)],
        [(1040, 351), (1072, 352), (1070, 456), (1041, 456)],
    ],
    "臀大肌": [
        [(918, 465), (994, 454), (1016, 503), (971, 538), (918, 506)],
        [(1130, 465), (1054, 454), (1032, 503), (1077, 538), (1130, 506)],
    ],
    "腘绳肌群": [
        [(918, 575), (994, 564), (1008, 684), (946, 714), (911, 650)],
        [(1130, 575), (1054, 564), (1040, 684), (1102, 714), (1137, 650)],
    ],
    "股四头肌群": [
        [(403, 570), (470, 554), (493, 650), (450, 688), (404, 655)],
        [(621, 570), (554, 554), (531, 650), (574, 688), (620, 655)],
    ],
}


def _text(draw, pos, text, size, fill=base.ARCADE_TEXT, max_width=None, spacing=7):
    content = base.wrap(draw, text, base.ft(size), max_width) if max_width else text
    draw.multiline_text(pos, content, font=base.ft(size), fill=fill, spacing=spacing)
    return content


def _primary(data):
    override = data.get("v3") or {}
    supplied = override.get("primary") or (data.get("findings") or {}).get("primary")
    model = base.report_model(data)
    finding = dict(supplied or model["primary"])
    legacy = (data.get("findings") or {}).get("improve")
    if not supplied and isinstance(legacy, str):
        if "髋先上移" in legacy:
            finding.update({"title": "起拉前髋先上移", "detail": "杠铃仍接近地面时，髋已经先上移；随后身体重新寻找更有力的离地角度。"})
        elif "前移" in legacy:
            finding.update({"title": "下降时杠铃轻微前移", "detail": "下降阶段出现轻微屏幕前移；该趋势需要结合标准侧面机位复核。"})
    defaults = muscle_defaults(base.exercise_of(data), finding.get("title", ""))
    finding.setdefault("title", model["primary"]["title"])
    finding.setdefault("detail", model["primary"]["detail"])
    if finding.get("no_muscle_direction"):
        finding["muscle_targets"] = []
    else:
        finding.setdefault("muscle_targets", defaults["muscle_targets"])
    finding.setdefault("optimization", defaults["optimization"])
    return finding


def muscle_defaults(exercise, title=""):
    lower = str(title)
    if exercise == "deadlift":
        return {"muscle_targets": [
            {"name": "腘绳肌与臀肌", "role": "帮助髋后坐时建立张力，并把髋向前上方带起"},
            {"name": "背阔肌与躯干稳定肌", "role": "帮助杠铃贴身、让躯干在离地初段保持稳定"},
        ], "optimization": "先后送髋并拉掉松量，再把地板推开。"}
    if exercise == "bench_press":
        return {"muscle_targets": [
            {"name": "上背与肩胛稳定肌", "role": "提供稳定的平台，让每次触胸落点一致"},
            {"name": "胸肌、肱三头肌与前臂", "role": "帮助杠铃从胸前平稳推起，并维持手腕承重"},
        ], "optimization": "触胸前固定上背压力，推起时两手同时向上发力。"}
    return {"muscle_targets": [
        {"name": "股四头肌与臀肌", "role": "帮助全脚掌压稳后，从底部平稳站起"},
        {"name": "核心与上背稳定肌", "role": "帮助躯干与杠铃在上升时维持稳定"},
    ], "optimization": "脚掌压稳，胸和髋一起离开底部。"}


def _guidance(exercise):
    return {
        "deadlift": "补拍：髋部高度后方｜60帧/秒｜从预拉到锁定",
        "bench_press": "补拍：卧推凳高度脚端｜60帧/秒｜从触胸到推起初段",
        "squat": "补拍：髋部高度后方｜60帧/秒｜从下降到底部再到锁定",
    }[exercise]


def report_mode(primary, secondary=None):
    """Public report contract; kept small enough for callers and tests."""
    result = {
        "exercise": base.exercise_of(primary),
        "view_one": _primary(primary),
        "view_two": _primary(secondary) if secondary else None,
        "page2": "view_two" if secondary else "filming_guidance",
        "guidance": _guidance(base.exercise_of(primary)),
    }
    return result


def _rep(data):
    return (data.get("repetitions") or [])[0]


def bar_path_available(data):
    """A side-path is drawable only after the strict hub tracker accepts it."""
    status = ((data.get("bar_tracking") or {}).get("status"))
    return status != "unavailable"


def display_bar_path(data, rep):
    """Use visual smoothing only from a strict tracker; never old path points."""
    tracked = (data.get("bar_tracking") or {})
    if tracked.get("status") == "available":
        return tracked.get("display_points") or []
    return rep.get("bar_path") or []


def _view(data):
    # Legacy tracking files predate the explicit view field. Their primary
    # recordings were captured as the default side/oblique review camera.
    return (data.get("v3") or {}).get("view") or data.get("view") or "oblique_side"


def _key_frames(rep, evidence=None):
    # A deadlift timing card may use manually reviewed hip landmarks as its
    # two photo anchors.  The bar path still supplies the trace, but the
    # evidence pin must sit on the hip when the conclusion is about hip timing.
    if evidence and evidence.get("first") and evidence.get("second"):
        return evidence["first"], evidence["second"]
    path = rep["bar_path"]
    # The first and final observation give novices a readable before/after pair.
    return path[0], path[-1]


def deadlift_path_review(data, rep):
    """Return the conservative screen-space bar-path result for a side view."""
    path = rep.get("bar_path") or []
    if len(path) < 2:
        return {"needs_report": False}
    start, endpoint = path[0], path[-1]
    max_point = max(path, key=lambda point: abs(float(point["x"]) - float(start["x"])))
    delta = float(endpoint["x"]) - float(start["x"])
    percent = abs(float(max_point["x"]) - float(start["x"])) / float(data.get("plate_diameter_px") or 1) * 100
    return {
        "needs_report": percent > 10,
        "direction": "画面右侧" if delta > 0 else "画面左侧",
        "percent": percent,
        "start": start,
        "endpoint": endpoint,
    }


def validate_deadlift_path_reporting(data, finding):
    """Prevent a conspicuous tracked drift from being drawn but left unexplained."""
    if not bar_path_available(data):
        return
    if base.exercise_of(data) != "deadlift" or base.normalize_view(_view(data)) not in {"side", "oblique_side"}:
        return
    review = deadlift_path_review(data, _rep(data))
    if not review["needs_report"]:
        return
    findings = data.get("findings") or {}
    improve = findings.get("improve") or []
    text = " ".join(str(item.get(key, "")) for item in [finding, *improve] if isinstance(item, dict) for key in ("title", "detail"))
    if "漂移" not in text:
        raise ValueError("deadlift visible bar drift must be explained in findings.primary or findings.improve")
    good = findings.get("good") or []
    good_text = " ".join(str(item.get(key, "")) for item in good if isinstance(item, dict) for key in ("title", "detail"))
    if any(term in good_text for term in ("路径连续", "路径稳定", "接近垂直")):
        raise ValueError("deadlift visible bar drift cannot be labelled as a stable or continuous bar path")


def _deadlift_drift_callout(draw, data, frames_dir, rep, crop, photo_box):
    """Add a readable start-line and endpoint offset only when it is material."""
    review = deadlift_path_review(data, rep)
    if not review["needs_report"]:
        return
    start = base.map_point(review["start"], crop, photo_box)
    endpoint = base.map_point(review["endpoint"], crop, photo_box)
    x0, y0 = start
    xe, ye = endpoint
    base.dotted(draw, (x0, photo_box[1] + 14), (x0, photo_box[3] - 14), fill="#AAB7D1", width=3)
    draw.line((x0, ye, xe, ye), fill=base.ARCADE_PINK, width=4)
    direction = 1 if xe >= x0 else -1
    draw.polygon(((xe, ye), (xe - direction * 14, ye - 8), (xe - direction * 14, ye + 8)), fill=base.ARCADE_PINK)
    label = "终点向右偏移" if review["direction"] == "画面右侧" else "终点向左偏移"
    existing = getattr(draw, "_callout_boxes", [])
    occupancy = _annotation_occupancy(
        data, frames_dir, review["endpoint"]["frame"], crop, photo_box,
        ((review["start"], 44, True), (review["endpoint"], 44, True)), existing,
    )
    result = _draw_external_label(draw, occupancy, photo_box, endpoint, label, base.ARCADE_PINK, direction)
    draw._callout_boxes = [*existing, result["label_box"]]


def pin_label_text(label, max_chars=8):
    """Wrap Chinese screenshot labels before they can overflow a video pin."""
    if "\n" in label:
        return label
    if len(label) <= max_chars:
        return label
    # Prefer a natural phrase break near the visual limit; otherwise use a
    # deterministic character wrap rather than letting PIL draw past the box.
    for token in ("，", "、", "；", "："):
        index = label.find(token)
        if 0 < index < max_chars:
            return label[:index + 1] + "\n" + label[index + 1:]
    return "\n".join(label[index:index + max_chars] for index in range(0, len(label), max_chars))


def rear_bar_level_evidence(data):
    """Return paired bar-end evidence for a rear squat or deadlift view.

    `rear_bar_evidence` remains a squat-only compatibility alias. New reports
    use semantic `reference` and `ascent` stages for either lift.
    """
    exercise = base.exercise_of(data)
    if exercise not in {"squat", "deadlift"} or base.normalize_view(_view(data)) != "rear":
        return None
    render = data.get("render") or {}
    current = render.get("rear_bar_level_evidence")
    if current:
        return current
    legacy = render.get("rear_bar_evidence") if exercise == "squat" else None
    if legacy:
        return {"reference": legacy["bottom"], "ascent": legacy["press"]}
    return None


def _content_contains(box, content, inset=0):
    return box[0] >= content[0] + inset and box[1] >= content[1] + inset and box[2] <= content[2] - inset and box[3] <= content[3] - inset


def _mask_cache_path(frame_path):
    digest = hashlib.sha256(str(frame_path.resolve()).encode() + str(frame_path.stat().st_mtime_ns).encode()).hexdigest()
    return Path(tempfile.gettempdir()) / "powerlifting-person-masks" / f"{digest}.png"


def _person_mask_for_frame(frame_path):
    """Return a Vision-derived person silhouette or fail closed.

    It intentionally does not borrow RTMPose coordinates: pose may be missing
    exactly when a label needs to avoid a partially occluded athlete.
    """
    cached = _mask_cache_path(frame_path)
    if not cached.exists():
        script = Path(__file__).with_name("segment_person.swift")
        completed = subprocess.run(
            ["swift", str(script), str(frame_path), str(cached)], text=True,
            capture_output=True, check=False,
        )
        if completed.returncode != 0 or not cached.exists():
            detail = (completed.stderr or completed.stdout or "unknown Vision error").strip()
            raise ValueError(f"person segmentation unavailable; refusing label placement: {detail}")
    mask = Image.open(cached).convert("L")
    if mask.getbbox() is None:
        raise ValueError("person segmentation returned an empty mask; refusing label placement")
    with Image.open(frame_path) as source:
        if mask.size != source.size:
            mask = mask.resize(source.size, Image.Resampling.NEAREST)
    foreground = sum(mask.histogram()[24:])
    coverage = foreground / max(1, mask.width * mask.height)
    if coverage < 0.003 or coverage > 0.90:
        raise ValueError(f"person segmentation mask confidence is unusable ({coverage:.1%} foreground); refusing label placement")
    return mask


def _mask_to_content(mask, crop, photo_box):
    """Map a source person mask through the exact crop/contain transform."""
    x1, y1, x2, y2 = map(int, crop)
    region = mask.crop((x1, y1, x2, y2))
    width, height = photo_box[2] - photo_box[0], photo_box[3] - photo_box[1]
    return region.resize((width, height), Image.Resampling.LANCZOS)


def _point_obstacle(mask, point, crop, photo_box, radius=30, horizontal_bar=False):
    x, y = base.map_point(point, crop, photo_box)
    local = ImageDraw.Draw(mask)
    local_x, local_y = int(x - photo_box[0]), int(y - photo_box[1])
    local.ellipse((local_x-radius, local_y-radius, local_x+radius, local_y+radius), fill=255)
    if horizontal_bar:
        local.rectangle((0, local_y - 16, mask.width, local_y + 16), fill=255)


def _annotation_occupancy(data, frames_dir, frame, crop, photo_box, blockers=(), existing_boxes=()):
    """Build the zero-overlap exclusion mask in local photo coordinates."""
    frame_path = base.frame_file(frames_dir, int(frame))
    source = _person_mask_for_frame(frame_path)
    mask = _mask_to_content(source, crop, photo_box)
    # Anti-aliased silhouette edges and clothing boundaries need a real safety
    # margin, otherwise a dark label can visually touch the athlete.
    mask = mask.point(lambda value: 255 if value >= 24 else 0).filter(ImageFilter.MaxFilter(33))
    for point, radius, is_bar in blockers:
        _point_obstacle(mask, point, crop, photo_box, radius, is_bar)
    # The full continuous trace is visible on the final evidence screenshot.
    # Treat it as occupied so an explanatory card cannot cover it.
    rep = _rep(data)
    path = display_bar_path(data, rep) if bar_path_available(data) else []
    if path and int(frame) == int(path[-1].get("frame", -1)):
        for point in path:
            _point_obstacle(mask, point, crop, photo_box, radius=10, horizontal_bar=False)
    for box in existing_boxes:
        local = (int(box[0] - photo_box[0]), int(box[1] - photo_box[1]), int(box[2] - photo_box[0]), int(box[3] - photo_box[1]))
        if local[2] > 0 and local[3] > 0 and local[0] < mask.width and local[1] < mask.height:
            ImageDraw.Draw(mask).rectangle(local, fill=255)
    return mask


def _label_measure(label, font_size, max_width):
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8), base.ARCADE_BG))
    chars = max(3, int((max_width - 30) // font_size))
    text = pin_label_text(label, chars)
    bounds = probe.multiline_textbbox((0, 0), text, font=base.ft(font_size), spacing=4)
    return text, int(bounds[2] - bounds[0] + 30), int(bounds[3] - bounds[1] + 24)


def _safe_label_box(occupancy, photo_box, target, label, direction=1, margin=16):
    """Find a readable, in-frame background box with zero obstacle overlap."""
    local_photo = (0, 0, photo_box[2] - photo_box[0], photo_box[3] - photo_box[1])
    target_local = (target[0] - photo_box[0], target[1] - photo_box[1])
    available_w = local_photo[2] - margin * 2
    available_h = local_photo[3] - margin * 2
    if available_w < 120 or available_h < 74:
        raise ValueError("video annotation cannot fit inside the displayed content box")
    for font_size in (23, 22, 21, 20):
        text, width, height = _label_measure(label, font_size, available_w)
        if width > available_w or height > available_h:
            continue
        # Candidate search is deliberately in-frame only.  It favours the
        # requested side but scores every background corner/edge before use.
        candidates = []
        for y in range(margin, max(margin + 1, local_photo[3] - height - margin + 1), 12):
            for x in range(margin, max(margin + 1, local_photo[2] - width - margin + 1), 12):
                box = (x, y, x + width, y + height)
                if occupancy.crop(box).getbbox() is not None:
                    continue
                center_x, center_y = x + width / 2, y + height / 2
                side_penalty = 0 if (center_x - target_local[0]) * direction >= 0 else 1500
                distance = (center_x - target_local[0]) ** 2 + (center_y - target_local[1]) ** 2
                candidates.append((side_penalty + distance, box))
        if candidates:
            _, box = min(candidates, key=lambda item: item[0])
            return (
                (box[0] + photo_box[0], box[1] + photo_box[1], box[2] + photo_box[0], box[3] + photo_box[1]),
                font_size,
                text,
            )
    raise ValueError("no safe background inside video content for annotation label")


def _draw_external_label(draw, occupancy, photo_box, target, label, color, direction=1):
    label_box, font_size, text = _safe_label_box(occupancy, photo_box, target, label, direction)
    anchor = _nearest_box_edge(target, label_box)
    # The line may leave the target point on the subject, but all text and
    # label chrome stay in verified background.  It is kept thin to avoid
    # obscuring unrelated anatomy on its way out.
    draw.line((*target, *anchor), fill=color, width=2)
    draw.rounded_rectangle(label_box, radius=8, fill=base.ARCADE_BG, outline=color, width=3)
    draw.multiline_text((label_box[0] + 14, label_box[1] + 10), text, font=base.ft(font_size), fill=color, spacing=4)
    return {"label_box": label_box, "anchor": anchor, "font_size": font_size}


def bilateral_wrists_at(rep, frame):
    """Return the closest screen-left/right wrist observations for a frame."""
    landmarks = rep.get("landmarks") or {}
    left = landmarks.get("wrist_screen_left") or []
    right = landmarks.get("wrist_screen_right") or []
    if not left or not right:
        return None, None
    nearest = lambda items: min(items, key=lambda item: abs(int(item.get("frame", frame)) - int(frame)))
    return nearest(left), nearest(right)


def _nearest_box_edge(point, box):
    """Return the closest perimeter point so a callout visibly attaches."""
    x, y = point
    x1, y1, x2, y2 = box
    candidates = (
        (x1, min(max(y, y1), y2)),
        (x2, min(max(y, y1), y2)),
        (min(max(x, x1), x2), y1),
        (min(max(x, x1), x2), y2),
    )
    return min(candidates, key=lambda candidate: (candidate[0] - x) ** 2 + (candidate[1] - y) ** 2)


def _pin(draw, data, frames_dir, point, crop, photo_box, label, color, direction=1, bar_target=True):
    x, y = base.map_point(point, crop, photo_box)
    # A point from a full-source/contain mapping must remain an actual video
    # point. Do not move it merely to make room for the label.
    if not (photo_box[0] + 10 <= x <= photo_box[2] - 10 and photo_box[1] + 10 <= y <= photo_box[3] - 10):
        raise ValueError("video annotation point falls outside the displayed content box")
    blockers = ((point, 44, True),) if bar_target else ()
    existing = getattr(draw, "_callout_boxes", [])
    occupancy = _annotation_occupancy(data, frames_dir, point["frame"], crop, photo_box, blockers, existing)
    draw.ellipse((x - 10, y - 10, x + 10, y + 10), fill=color, outline=base.ARCADE_BG, width=3)
    result = _draw_external_label(draw, occupancy, photo_box, (x, y), label, color, direction)
    draw._callout_boxes = [*existing, result["label_box"]]
    return {"point": (x, y), **result}


POSE_CONNECTIONS = (
    ("left_shoulder", "left_elbow"), ("left_elbow", "left_wrist"),
    ("right_shoulder", "right_elbow"), ("right_elbow", "right_wrist"),
    ("left_shoulder", "left_hip"), ("right_shoulder", "right_hip"),
    ("left_hip", "left_knee"), ("left_knee", "left_ankle"),
    ("right_hip", "right_knee"), ("right_knee", "right_ankle"),
)


def _pose_sample(data, time):
    """Return the closest already confidence-gated pose sample, never a guess."""
    pose = data.get("_pose_tracking") or {}
    samples = pose.get("frames") or []
    candidates = [sample for sample in samples if isinstance(sample.get("time"), (int, float))]
    if not candidates:
        return None
    sample = min(candidates, key=lambda value: abs(float(value["time"]) - float(time)))
    return sample if abs(float(sample["time"]) - float(time)) <= 1 / 20 else None


def _draw_pose_overlay(draw, data, point, crop, photo_box):
    """Draw only RTMPose's confident, visible joints on a key screenshot."""
    sample = _pose_sample(data, float(point.get("time", 0)))
    if sample is None:
        return
    joints = sample.get("joints") or {}
    mapped = {}
    for name, joint in joints.items():
        if not isinstance(joint, dict) or not joint.get("available"):
            continue
        if not isinstance(joint.get("x"), (int, float)) or not isinstance(joint.get("y"), (int, float)):
            continue
        xy = base.map_point(joint, crop, photo_box)
        if photo_box[0] + 5 <= xy[0] <= photo_box[2] - 5 and photo_box[1] + 5 <= xy[1] <= photo_box[3] - 5:
            mapped[name] = xy
    for start, end in POSE_CONNECTIONS:
        if start in mapped and end in mapped:
            draw.line((*mapped[start], *mapped[end]), fill="#78E7DD", width=4)
    for x, y in mapped.values():
        draw.ellipse((x - 7, y - 7, x + 7, y + 7), fill="#0C1732", outline="#78E7DD", width=3)
    # No text legend is placed over the evidence frame: the visible rings and
    # links are sufficient, while textual callouts use the safe-zone gate.


def _bilateral_wrist_evidence(draw, rep, point, crop, photo_box, color):
    """Show the visible left/right wrist height difference without fake numbers."""
    left, right = bilateral_wrists_at(rep, int(point["frame"]))
    if not left or not right:
        return False
    lx, ly = base.map_point(left, crop, photo_box)
    rx, ry = base.map_point(right, crop, photo_box)
    for x, y in ((lx, ly), (rx, ry)):
        draw.ellipse((x - 9, y - 9, x + 9, y + 9), fill=color, outline=base.ARCADE_BG, width=3)
    reference_y = min(ly, ry)
    lower_x, lower_y = (lx, ly) if ly > ry else (rx, ry)
    draw.line((lx, ly, rx, ry), fill=color, width=3)
    draw.line((lx, reference_y, rx, reference_y), fill="#AAB4C9", width=2)
    draw.line((lower_x, reference_y, lower_x, lower_y), fill=color, width=3)
    draw.line((lower_x - 8, reference_y, lower_x + 8, reference_y), fill=color, width=3)
    draw.line((lower_x - 8, lower_y, lower_x + 8, lower_y), fill=color, width=3)
    return True


def _rear_bar_end_evidence(draw, data, frames_dir, evidence, crop, photo_box, color, show_arrows=False):
    """Rear evidence: compare both bar ends, never a single-point path."""
    left = evidence["screen_left"]
    right = evidence["screen_right"]
    lx, ly = base.map_point(left, crop, photo_box)
    rx, ry = base.map_point(right, crop, photo_box)
    for x, y in ((lx, ly), (rx, ry)):
        if not (photo_box[0] + 10 <= x <= photo_box[2] - 10 and photo_box[1] + 10 <= y <= photo_box[3] - 10):
            raise ValueError("rear bar endpoint falls outside the displayed video content")
        draw.ellipse((x - 10, y - 10, x + 10, y + 10), fill=color, outline=base.ARCADE_BG, width=3)
    # Do not join the two endpoints with a coloured pseudo-trajectory: this
    # rear view answers only level/synchrony.  The dashed neutral line is the
    # sole height reference for novice readers.
    level_y = min(ly, ry)
    canvas = draw._image
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    base.dotted(ImageDraw.Draw(overlay), (lx, level_y), (rx, level_y), fill=(170, 183, 209, 115), width=2)
    canvas.paste(overlay, (0, 0), overlay)
    if show_arrows:
        for x, y in ((lx, ly), (rx, ry)):
            tip_y = max(photo_box[1] + 18, y - 44)
            draw.line((x, y - 4, x, tip_y + 9), fill=color, width=4)
            draw.polygon(((x, tip_y), (x - 9, tip_y + 14), (x + 9, tip_y + 14)), fill=color)

    mid_x, mid_y = (lx + rx) / 2, (ly + ry) / 2
    existing = getattr(draw, "_callout_boxes", [])
    occupancy = _annotation_occupancy(
        data, frames_dir, evidence["frame"], crop, photo_box,
        ((left, 44, True), (right, 44, True)), existing,
    )
    result = _draw_external_label(draw, occupancy, photo_box, (mid_x, mid_y), evidence["label"], color, 1)
    draw._callout_boxes = [*existing, result["label_box"]]
    return {"left": (lx, ly), "right": (rx, ry), **result}


def _header(draw, page, exercise, title, color, show_summary=True, header_title=None):
    left, right = HUD_X_BOUNDS
    base.arcade_panel(draw, HEADER_BOX, color, width=STRUCTURAL_BORDER)
    heading = header_title or PAGE_TITLES[page]
    draw.text((80, 66), f"{HEADER_ICON}  第{page}关｜{heading}", font=base.ft(34), fill=base.ARCADE_TEXT)
    progress_x, y = 82, 124
    for index in range(4):
        fill = color if index < page else "#263758"
        draw.rectangle((progress_x + index * 220, y, progress_x + index * 220 + 198, y + 10), fill=fill)
    if show_summary:
        # Keep the grid visible in the conclusion bar while matching every
        # other structural card's rounded geometry.
        _transparent_panel(draw, SUMMARY_BOX, color)
        _text(draw, (82, 207), title, 46, base.ARCADE_TEXT, 850)


def _transparent_panel(draw, box, color):
    """Draw a no-fill structural card using the shared rounded HUD geometry."""
    draw.rounded_rectangle(box, radius=STRUCTURAL_RADIUS, outline=color, width=STRUCTURAL_BORDER)


def _pixel_outline(draw, box, color, width=STRUCTURAL_BORDER, step=14):
    """Compatibility wrapper for prior audit helpers; now uses rounded geometry."""
    _transparent_panel(draw, box, color)


def _photo_pair(data, frames_dir, finding, page):
    rep = _rep(data)
    exercise = base.exercise_of(data)
    first, last = _key_frames(rep, (data.get("v3") or {}).get("evidence"))
    image = base.arcade_canvas(); draw = ImageDraw.Draw(image)
    draw._callout_boxes = []
    # Colour communicates the camera role consistently: the preferred
    # side/oblique view is pink, while the independent symmetry camera is
    # cyan.  A non-stable title must not accidentally recolour Page 2 pink.
    is_secondary_view = base.normalize_view(_view(data)) in {"front", "rear", "foot_end", "head_end"}
    color = base.ARCADE_CYAN if is_secondary_view else base.ARCADE_PINK
    _header(draw, page, base.exercise_of(data), finding["title"], color)
    boxes = PHOTO_BOXES
    contexts = []
    foot_end_bench = exercise == "bench_press" and base.normalize_view(_view(data)) == "foot_end"
    hip_timing_deadlift = exercise == "deadlift" and (data.get("v3") or {}).get("evidence")
    rear_level_evidence = rear_bar_level_evidence(data)
    if rear_level_evidence:
        first, last = rear_level_evidence["reference"], rear_level_evidence["ascent"]
    path_available = bar_path_available(data)
    if page == 1:
        validate_deadlift_path_reporting(data, finding)
    for index, (point, box) in enumerate(zip((first, last), boxes), 1):
        stage = point.get("phase") if hip_timing_deadlift else None
        tag = f"{index}｜{base.view_label(_view(data))}｜{float(point.get('time', 0)):.2f}秒"
        if stage:
            tag += f"｜{stage}"
        # A report can opt its evidence pages into complete, uncropped source
        # frames.  The legacy Page-1 flag remains as a backward-compatible
        # fallback for existing reports.
        render = data.get("render") or {}
        evidence_fit = render.get("video_photo_fit", render.get("page_one_photo_fit", "cover"))
        crop, inner = base.arcade_photo(
            image, data, frames_dir, int(point["frame"]), box, color, tag,
            fit=evidence_fit if page in {1, 2} else "cover",
        )
        contexts.append((crop, inner))
        # This visual layer is optional and does not create a technique
        # conclusion.  Low-confidence/occluded joints are absent by design.
        _draw_pose_overlay(draw, data, point, crop, inner)
        if foot_end_bench:
            _bilateral_wrist_evidence(draw, rep, point, crop, inner, color)
            # A foot-end view must report the reviewed bilateral observation,
            # not a hard-coded asymmetry.  `label` lives on the manually
            # verified evidence point and keeps a stable pair from being
            # mislabelled as screen-left low.
            label = point.get("label") or ("画面左端略低" if index == 1 else "两端同步推起")
            _pin(draw, data, frames_dir, point, crop, inner, label, color, 1 if index == 1 else -1)
        elif rear_level_evidence:
            _rear_bar_end_evidence(draw, data, frames_dir, point, crop, inner, color, show_arrows=index == 2)
        elif hip_timing_deadlift:
            label = point.get("label") or ("起始髋位" if index == 1 else "髋已先上移")
            _pin(draw, data, frames_dir, point, crop, inner, label, color, 1 if index == 1 else -1, bar_target=False)
        elif path_available:
            # Key-frame labels describe the evidence visible in that exact
            # frame.  Fall back to the report title only for older tracking
            # JSON that has no frame-specific annotation.
            label = point.get("label") or (finding["title"] if index == 1 else "推起回程")
            _pin(draw, data, frames_dir, point, crop, inner, label, color, 1 if index == 1 else -1)
    # Path remains within the second frame and only represents this view.
    # Rear squat uses paired bar ends instead of a misleading one-point path.
    if not rear_level_evidence and not foot_end_bench and path_available:
        points = display_bar_path(data, rep)
        if (data.get("bar_tracking") or {}).get("status") == "available":
            base.arcade_continuous_trace(draw, points, contexts[1][0], contexts[1][1], exercise, 8)
            if any(point.get("display_source") == "smoothed_gap" for point in points):
                draw.rounded_rectangle((contexts[1][1][0] + 12, contexts[1][1][3] - 38, contexts[1][1][0] + 202, contexts[1][1][3] - 14), radius=6, fill="#0C1732", outline="#B9C8D9", width=2)
                draw.text((contexts[1][1][0] + 20, contexts[1][1][3] - 35), "浅色段＝平滑显示", font=base.ft(16), fill="#D5E1F0")
        else:
            base.arcade_trace(draw, points, contexts[1][0], contexts[1][1], base.ARCADE_CYAN, base.ARCADE_BLUE, 8)
    if page == 1 and exercise == "deadlift" and path_available:
        _deadlift_drift_callout(draw, data, frames_dir, rep, contexts[1][0], contexts[1][1])
    base.arcade_panel(draw, (FULL_X_BOUNDS[0], 992, FULL_X_BOUNDS[1], 1166), base.ARCADE_YELLOW, width=STRUCTURAL_BORDER)
    draw.text((84, 1018), "看到了什么", font=base.ft(32), fill=base.ARCADE_YELLOW)
    _text(draw, (84, 1066), finding["detail"], 28, base.ARCADE_TEXT, 880)
    base.arcade_panel(draw, (FULL_X_BOUNDS[0], 1190, FULL_X_BOUNDS[1], 1358), color, width=STRUCTURAL_BORDER)
    draw.text((84, 1216), "这意味着什么", font=base.ft(32), fill=color)
    _text(draw, (84, 1263), finding["optimization"], 28, base.ARCADE_TEXT, 880)
    return image


def _filming_guidance(data):
    exercise = base.exercise_of(data)
    image = base.arcade_canvas(); draw = ImageDraw.Draw(image)
    _header(draw, 2, exercise, "补拍这个角度，才能确认左右稳定", base.ARCADE_BLUE)
    cards = [
        ("当前无法确认", "左右端是否同时移动、站距或脚掌是否对称。"),
        ("建议机位", _guidance(exercise)),
        ("拍摄方法", "镜头固定；完整拍到准备、关键阶段和锁定。"),
    ]
    for i, (heading, body) in enumerate(cards):
        y = 342 + i * (220 + STRUCTURAL_GAP)
        base.arcade_panel(draw, (FULL_X_BOUNDS[0], y, FULL_X_BOUNDS[1], y + 220), (base.ARCADE_BLUE, base.ARCADE_CYAN, base.ARCADE_YELLOW)[i], width=STRUCTURAL_BORDER)
        draw.text((84, y + 34), heading, font=base.ft(38), fill=(base.ARCADE_BLUE, base.ARCADE_CYAN, base.ARCADE_YELLOW)[i])
        _text(draw, (84, y + 100), body, 32, base.ARCADE_TEXT, 880)
    base.arcade_panel(draw, (FULL_X_BOUNDS[0], 1074, FULL_X_BOUNDS[1], 1194), base.ARCADE_PINK, width=STRUCTURAL_BORDER)
    _text(draw, (84, 1111), "补拍不是为了找更多问题，而是避免从错误角度下结论。", 28, base.ARCADE_TEXT, 880)
    return image


def _anatomy_base(asset_path=DEADLIFT_ASSET):
    if asset_path.exists():
        return Image.open(asset_path).convert("RGBA")
    # Safe fallback for local tests before the generated asset is available.
    image = Image.new("RGBA", (900, 440), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    for x in (280, 610):
        draw.ellipse((x - 45, 28, x + 45, 118), fill="#C8D1DA", outline="#73839A", width=4)
        draw.rounded_rectangle((x - 72, 124, x + 72, 292), radius=46, fill="#C8D1DA", outline="#73839A", width=4)
        draw.line((x - 42, 288, x - 60, 418), fill="#73839A", width=24)
        draw.line((x + 42, 288, x + 60, 418), fill="#73839A", width=24)
    return image


def anatomy_asset_for(exercise):
    """Use one canonical front/back scan mannequin across all three lifts."""
    if exercise not in {"deadlift", "bench_press", "squat"}:
        raise ValueError(f"unsupported anatomy exercise: {exercise}")
    return DEADLIFT_ASSET


def _canonical_anatomy_transform(panel=ANATOMY_BOX):
    """Map source asset points to the contained canonical Page-3 panel."""
    with Image.open(DEADLIFT_ASSET) as asset:
        source_w, source_h = asset.size
    panel_w, panel_h = panel[2] - panel[0], panel[3] - panel[1]
    scale = min(panel_w / source_w, panel_h / source_h)
    displayed_w, displayed_h = round(source_w * scale), round(source_h * scale)
    origin_x = panel[0] + (panel_w - displayed_w) // 2
    origin_y = panel[1] + (panel_h - displayed_h) // 2
    return origin_x, origin_y, scale


def _point_in_polygon(point, polygon):
    """Inclusive ray-cast test for a card-space anatomy safe-zone polygon."""
    px, py = point
    inside = False
    for index, (x1, y1) in enumerate(polygon):
        x2, y2 = polygon[(index + 1) % len(polygon)]
        if (y1 > py) != (y2 > py):
            intersect_x = (x2 - x1) * (py - y1) / (y2 - y1) + x1
            if px <= intersect_x:
                inside = not inside
    return inside


def validate_anatomy_locations(indices):
    """Reject an index unless its ring centre is in the named muscle safe zone."""
    origin_x, origin_y, scale = _canonical_anatomy_transform()
    for item in indices:
        source_zones = CANONICAL_MUSCLE_SAFE_ZONES.get(item["muscle"])
        if not source_zones:
            raise ValueError(f"no canonical muscle mask is defined for: {item['muscle']}")
        card_zones = [
            [(origin_x + x * scale, origin_y + y * scale) for x, y in polygon]
            for polygon in source_zones
        ]
        if not any(_point_in_polygon(item["target"], polygon) for polygon in card_zones):
            raise ValueError(f"anatomy index is outside the canonical {item['muscle']} muscle mask")


def _highlight(draw, box, exercise, side):
    x1, y1, x2, y2 = box; w, h = x2 - x1, y2 - y1
    # Pixel scan zones: educational emphasis, not a measurement or diagnosis.
    asset_w = min(w, h * 1.5)
    asset_x = x1 + (w - asset_w) / 2
    def region(rx1, ry1, rx2, ry2, color):
        area = (asset_x + asset_w * rx1, y1 + h * ry1, asset_x + asset_w * rx2, y1 + h * ry2)
        draw.rectangle(area, fill="#111D3A", outline=color, width=4)
        # Small square corner indicators make the zones part of the arcade HUD.
        ax1, ay1, ax2, ay2 = area
        for px, py in ((ax1, ay1), (ax2 - 10, ay1), (ax1, ay2 - 10), (ax2 - 10, ay2 - 10)):
            draw.rectangle((px, py, px + 10, py + 10), fill=color)
    if exercise == "bench_press":
        regions = [(0.23, .22, .45, .37, base.ARCADE_PINK), (.60, .22, .79, .37, base.ARCADE_PINK), (.40, .32, .50, .50, base.ARCADE_PURPLE), (.57, .31, .66, .50, base.ARCADE_PURPLE)]
    elif exercise == "deadlift":
        regions = [(0.21, .47, .44, .72, base.ARCADE_CYAN), (.59, .47, .78, .72, base.ARCADE_CYAN), (.42, .35, .55, .62, base.ARCADE_BLUE)]
    else:
        regions = [(0.22, .55, .43, .82, base.ARCADE_YELLOW), (.60, .55, .78, .82, base.ARCADE_YELLOW), (.38, .41, .57, .61, base.ARCADE_CYAN)]
    for rx1, ry1, rx2, ry2, color in regions:
        region(rx1, ry1, rx2, ry2, color)


def _pixel_muscle_region(image, points, color, striped=False):
    """Add a clipped pixel highlight that follows a simplified muscle shape."""
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    rgb = tuple(int(color[index:index + 2], 16) for index in (1, 3, 5))
    draw.polygon(points, fill=(*rgb, 118))
    if striped:
        left = int(min(x for x, _ in points)); right = int(max(x for x, _ in points))
        top = int(min(y for _, y in points)); bottom = int(max(y for _, y in points))
        for offset in range(left - (bottom - top), right + 20, 13):
            draw.line((offset, bottom, offset + (bottom - top), top), fill=(*rgb, 230), width=5)
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).polygon(points, fill=255)
    overlay.putalpha(ImageChops.multiply(overlay.getchannel("A"), mask))
    image.paste(overlay, (0, 0), overlay)
    outline = ImageDraw.Draw(image)
    outline.line([*points, points[0]], fill=color, width=4, joint="curve")
    # Deliberately square corner pixels, so the marker reads as HUD rather than medical art.
    for x, y in points[::max(1, len(points) // 3)]:
        outline.rectangle((x - 4, y - 4, x + 4, y + 4), fill=color)


def _pixel_label(draw, box, text, color, target):
    x1, y1, x2, y2 = box
    anchor_x = x2 if target[0] > x2 else x1
    anchor_y = min(max(target[1], y1 + 12), y2 - 12)
    draw.line((anchor_x, anchor_y, target[0], target[1]), fill=color, width=3)
    draw.ellipse((target[0] - 5, target[1] - 5, target[0] + 5, target[1] + 5), fill=color)
    draw.rectangle(box, fill="#101A35", outline=color, width=3)
    # stepped corner chips make each tag an intentionally arcade component.
    for px, py in ((x1, y1), (x2 - 8, y1), (x1, y2 - 8), (x2 - 8, y2 - 8)):
        draw.rectangle((px, py, px + 8, py + 8), fill=color)
    draw.text((x1 + 14, y1 + 10), text, font=base.ft(21), fill=color)


def bench_muscle_indices():
    """Reviewed, index-only anatomy landmarks for the front/back bench panel."""
    return [
        {"number": "①", "muscle": "胸大肌", "view": "正面", "name": "胸大肌｜两机位", "target": (374, 347), "label": (84, 255), "colors": (base.ARCADE_PINK, base.ARCADE_CYAN)},
        {"number": "②", "muscle": "中下斜方肌", "view": "背面", "name": "中下斜方肌｜两机位", "target": (691, 372), "label": (770, 255), "colors": (base.ARCADE_PINK, base.ARCADE_CYAN)},
        {"number": "③", "muscle": "肱三头肌", "view": "背面", "name": "肱三头肌｜两机位", "target": (769, 407), "label": (770, 445), "colors": (base.ARCADE_PINK, base.ARCADE_CYAN)},
        {"number": "④", "muscle": "前臂屈肌群", "view": "正面", "name": "前臂屈肌群｜机位二", "target": (316, 468), "label": (84, 510), "colors": (base.ARCADE_CYAN,)},
    ]


def _draw_index_label(draw, item):
    """Draw an outline-only index and leader: no anatomy colour blocks."""
    tx, ty = item["target"]
    lx, ly = item["label"]
    colors = item["colors"]
    primary = colors[0]
    # The numbered ring stays directly on the precise anatomical centre; its
    # leader points to an unboxed text label outside the mannequin.
    marker = (tx - 13, ty - 13, tx + 13, ty + 13)
    draw.ellipse(marker, fill="#0B1329", outline=primary, width=3)
    if len(colors) == 2:
        # Pink maps to the first (机位一) card; cyan maps to the second.  A
        # split ring signals that the same muscle matters to both cards.
        draw.arc(marker, 90, 270, fill=colors[0], width=4)
        draw.arc(marker, 270, 450, fill=colors[1], width=4)
    draw.text((tx - 10, ty - 14), item["number"], font=base.ft(21), fill=base.ARCADE_TEXT)
    label_box = item.get("label_box")
    if label_box:
        anchor_x, anchor_y = _nearest_box_edge((tx, ty), label_box)
    else:
        anchor_x, anchor_y = (lx + 155 if lx < tx else lx - 12), ly + 14
    if len(colors) == 2:
        draw.line((anchor_x, anchor_y - 1, tx, ty - 1), fill=colors[0], width=2)
        draw.line((anchor_x, anchor_y + 1, tx, ty + 1), fill=colors[1], width=2)
    else:
        draw.line((anchor_x, anchor_y, tx, ty), fill=primary, width=2)
    if label_box:
        draw.rounded_rectangle(label_box, radius=7, fill=base.ARCADE_BG, outline=primary, width=2)
        draw.text((label_box[0] + 9, label_box[1] + 7), f"{item['number']} {item['name']}", font=base.ft(item.get("label_font_size", 20)), fill=primary)
    else:
        draw.text((lx, ly), f"{item['number']} {item['name']}", font=base.ft(20), fill=primary, stroke_width=1, stroke_fill="#0B1329")


def _bench_muscle_annotations(image, target):
    """Bench page: anatomy remains clean; only indexed landmarks are shown."""
    draw = ImageDraw.Draw(image)
    for item in bench_muscle_indices():
        _draw_index_label(draw, item)
    draw.text((82, 736), "粉＋青＝两机位都涉及｜青＝机位二", font=base.ft(18), fill=base.ARCADE_TEXT)


def deadlift_muscle_indices():
    """Index-only training directions for a single oblique deadlift view.

    Pink mirrors the sole lower evidence card (机位一).  These are training
    directions, rather than claims that a particular muscle is weak.
    """
    return [
        {"number": "①", "muscle": "臀大肌", "view": "背面", "name": "臀大肌｜机位一", "target": (657, 469), "label": (760, 500), "colors": (base.ARCADE_PINK,)},
        {"number": "②", "muscle": "腘绳肌群", "view": "背面", "name": "腘绳肌群｜机位一", "target": (657, 552), "label": (760, 585), "colors": (base.ARCADE_PINK,)},
        {"number": "③", "muscle": "背阔肌", "view": "背面", "name": "背阔肌｜机位一", "target": (636, 405), "label": (84, 338), "colors": (base.ARCADE_PINK,)},
        {"number": "④", "muscle": "竖脊肌群", "view": "背面", "name": "竖脊肌群｜机位一", "target": (670, 426), "label": (760, 455), "colors": (base.ARCADE_PINK,)},
    ]


def muscle_indices(exercise):
    """Return only indexes with a reviewed, single-structure anatomy target.

    Squat deliberately has no fallback index map: the shared mannequin's
    clothing obscures gluteal anatomy, so generic boxes would mislead.
    """
    return {
        "deadlift": deadlift_muscle_indices,
        "bench_press": bench_muscle_indices,
        "squat": lambda: [],
    }[exercise]()


_ANATOMY_SCOPE = {
    "view_one": ("机位一", (base.ARCADE_PINK,)),
    "view_two": ("机位二", (base.ARCADE_CYAN,)),
    "shared": ("两机位", (base.ARCADE_PINK, base.ARCADE_CYAN)),
}
_GENERIC_ANATOMY_TERMS = ("臀腿后侧", "躯干稳定", "上背", "核心", "下肢", "胸肌", "臀肌", "肩胛稳定肌")
_GENERIC_ANATOMY_EXACT_TERMS = {"相关肌群", "臀腿后侧", "躯干稳定", "上背", "核心", "下肢", "胸肌", "臀肌", "前臂", "肩胛稳定肌"}


def reviewed_anatomy_indices(data):
    """Return validated analyst-supplied anatomy indexes, or reviewed defaults.

    A custom index must name one structure, state front/back view, and place
    both a ring target and external label in the 1080px card coordinate space.
    """
    supplied = ((data.get("render") or {}).get("anatomy_indices"))
    if supplied is None:
        return []
    if not isinstance(supplied, list):
        raise ValueError("render.anatomy_indices must be a list")
    result = []
    for item in supplied:
        muscle = str(item.get("muscle", "")).strip()
        view = str(item.get("view", "")).strip()
        scope = str(item.get("scope", "")).strip()
        target, label = item.get("target"), item.get("label")
        if not muscle or muscle in _GENERIC_ANATOMY_EXACT_TERMS or any(term in muscle for term in _GENERIC_ANATOMY_TERMS) or any(token in muscle for token in ("与", "、", "/", "／")):
            raise ValueError("each anatomy index must name one precise muscle, not a generic region")
        if view not in {"正面", "背面"} or scope not in _ANATOMY_SCOPE:
            raise ValueError("anatomy index requires view=正面/背面 and a valid scope")
        if not (isinstance(target, list) and len(target) == 2 and isinstance(label, list) and len(label) == 2):
            raise ValueError("anatomy index requires [x, y] target and label coordinates")
        scope_name, colors = _ANATOMY_SCOPE[scope]
        result.append({
            "number": str(item.get("number", "")), "muscle": muscle, "view": view,
            "scope": scope, "name": f"{muscle}｜{scope_name}", "target": tuple(target), "label": tuple(label), "colors": colors,
        })
    return result


def validate_anatomy_coverage(indices, primary, secondary=None):
    """Require an exact, same-scope Page 3 marker for every muscle described."""
    required = []
    for data, scope in ((primary, "view_one"), (secondary, "view_two")):
        if not data:
            continue
        finding = _primary(data)
        required.extend((str(item.get("name", "")).strip(), scope) for item in (finding.get("muscle_targets") or []))
    available = {(item["muscle"], item["scope"]) for item in indices}
    missing = [
        (muscle, scope) for muscle, scope in required
        if muscle and (muscle, scope) not in available and (muscle, "shared") not in available
    ]
    if missing:
        summary = "、".join(f"{muscle}({scope})" for muscle, scope in missing)
        raise ValueError(f"missing anatomy indexes for described muscles: {summary}")


def validate_anatomy_layout(indices, panel):
    """Keep every index ring and its readable label inside the anatomy panel."""
    x1, y1, x2, y2 = panel
    measure = ImageDraw.Draw(Image.new("RGB", SIZE, base.ARCADE_BG))
    for item in indices:
        tx, ty = item["target"]
        lx, ly = item["label"]
        text = f"{item['number']} {item['name']}"
        bounds = measure.textbbox((lx, ly), text, font=base.ft(20), stroke_width=1)
        if not (x1 + 14 <= tx <= x2 - 14 and y1 + 14 <= ty <= y2 - 14):
            raise ValueError(f"anatomy panel target is outside bounds: {item['muscle']}")
        if not (x1 + 12 <= bounds[0] and y1 + 12 <= bounds[1] and bounds[2] <= x2 - 12 and bounds[3] <= y2 - 12):
            raise ValueError(f"anatomy panel label is outside bounds: {item['muscle']}")


def _anatomy_occupancy(asset, panel):
    """Build a local panel mask from the canonical mannequin alpha channel."""
    width, height = panel[2] - panel[0], panel[3] - panel[1]
    fitted = ImageOps.contain(asset, (width, height), Image.Resampling.LANCZOS)
    mask = Image.new("L", (width, height), 0)
    alpha = fitted.getchannel("A")
    mask.paste(alpha, ((width - fitted.width) // 2, (height - fitted.height) // 2))
    return mask.filter(ImageFilter.MaxFilter(17)), fitted


def _place_anatomy_labels(indices, occupancy, panel):
    """Place Page-3 text cards only in transparent space around mannequins."""
    placed = []
    for item in indices:
        copy = dict(item)
        tx, ty = copy["target"]
        # Place on the side that keeps the leader short, but always defer to
        # the no-overlap candidate search.
        direction = -1 if tx > (panel[0] + panel[2]) / 2 else 1
        label_box, font_size, _ = _safe_label_box(
            occupancy, panel, (tx, ty), f"{copy['number']} {copy['name']}", direction,
        )
        copy["label_box"] = label_box
        copy["label"] = (label_box[0] + 9, label_box[1] + 7)
        copy["label_font_size"] = font_size
        placed.append(copy)
    return placed


def validate_anatomy_label_clearance(indices, occupancy, panel):
    """Reject any Page-3 label card that touches the mannequin silhouette."""
    for item in indices:
        box = item.get("label_box")
        if not box:
            raise ValueError(f"anatomy index lacks an external label box: {item['muscle']}")
        local = (box[0] - panel[0], box[1] - panel[1], box[2] - panel[0], box[3] - panel[1])
        if occupancy.crop(local).getbbox() is not None:
            raise ValueError(f"anatomy label overlaps mannequin: {item['muscle']}")


def _deadlift_muscle_annotations(image, target):
    """Keep the pixel mannequins clean: landmarks replace coloured scan boxes."""
    draw = ImageDraw.Draw(image)
    for item in deadlift_muscle_indices():
        _draw_index_label(draw, item)
    draw.text((82, 736), "粉色索引＝机位一优先关注的相关能力", font=base.ft(18), fill=base.ARCADE_TEXT)


def _muscle_page(primary, secondary=None):
    exercise = base.exercise_of(primary)
    image = base.arcade_canvas(); draw = ImageDraw.Draw(image)
    stable_report = _report_is_stable(primary, secondary)
    _header(
        draw, 3, exercise, "", base.ARCADE_PURPLE, show_summary=False,
        header_title="相关肌群｜无需专项强化" if stable_report else None,
    )
    asset = _anatomy_base(anatomy_asset_for(exercise))
    # Prioritize the scan panel at phone width: it is the visual anchor of
    # this page, so give it materially more space than the explanation cards.
    target = ANATOMY_BOX
    panel_size = (target[2]-target[0], target[3]-target[1])
    # No illustration-card fill: the page grid remains visible behind the
    # extracted mannequins and a rounded purple outline preserves the common HUD grid.
    _transparent_panel(draw, target, base.ARCADE_PURPLE)
    occupancy, asset = _anatomy_occupancy(asset, target)
    asset_x = target[0] + (panel_size[0] - asset.width) // 2
    asset_y = target[1] + (panel_size[1] - asset.height) // 2
    image.paste(asset, (asset_x, asset_y), asset)
    indices = reviewed_anatomy_indices(primary)
    validate_anatomy_coverage(indices, primary, secondary)
    validate_anatomy_layout(indices, target)
    validate_anatomy_locations(indices)
    indices = _place_anatomy_labels(indices, occupancy, target)
    validate_anatomy_label_clearance(indices, occupancy, target)
    if indices:
        for item in indices:
            _draw_index_label(draw, item)
        scopes = {item["colors"] for item in indices}
        legend = "粉色索引＝机位一优先关注的相关能力" if scopes == {(base.ARCADE_PINK,)} else "粉＝机位一｜青＝机位二｜粉＋青＝两机位"
        draw.text((82, 738), legend, font=base.ft(18), fill=base.ARCADE_TEXT)
    else:
        draw.text((82, 738), "本组未发现需要专项强化的可见问题。", font=base.ft(21), fill=base.ARCADE_TEXT)
    findings = [("机位一", _primary(primary))]
    if secondary:
        findings.append(("机位二", _primary(secondary)))
    panel_h = 260 if len(findings) == 2 else 390
    for i, (label, finding) in enumerate(findings):
        x = FULL_X_BOUNDS[0]
        y = ANALYSIS_BOX[1] + i * (panel_h + STRUCTURAL_GAP) if len(findings) == 2 else ANALYSIS_BOX[1]
        width = FULL_X_BOUNDS[1] - FULL_X_BOUNDS[0]
        color = base.ARCADE_PINK if i == 0 else base.ARCADE_CYAN
        base.arcade_panel(draw, (x, y, x + width, y + panel_h), color, width=STRUCTURAL_BORDER)
        draw.text((x + 28, y + 20), label, font=base.ft(31), fill=color)
        muscle_problem = str(finding.get("muscle_problem") or finding["title"])
        observation_label = "观察" if finding.get("no_muscle_direction") else "问题"
        observation_text = str(finding.get("title") or muscle_problem) if finding.get("no_muscle_direction") else muscle_problem
        _text(draw, (x + 28, y + 65), f"{observation_label}：{observation_text}", 28, base.ARCADE_TEXT, width - 56)
        targets = finding.get("muscle_targets") or []
        names = "、".join(str(item.get("name", "相关肌群")) for item in targets)
        # A compact capability summary can explain several precisely indexed
        # muscles without pretending that a video diagnosed weakness.
        roles = str(finding.get("capacity_summary") or (targets[0].get("role", "帮助动作稳定") if targets else "帮助动作稳定"))
        muscle_heading = str(finding.get("muscle_heading", "优先加强"))
        if targets:
            _text(draw, (x + 28, y + 112), f"{muscle_heading}：{names}", 26, base.ARCADE_TEXT, width - 56)
            _text(draw, (x + 28, y + 158), f"作用：{roles}", 24, base.ARCADE_MUTED, width - 56)
            _text(draw, (x + 28, y + (207 if len(findings) == 2 else 300)), f"提示：{finding['optimization']}", 23, color, width - 56)
        else:
            _text(draw, (x + 28, y + 128), "无需新增强化方向：该机位未见需要纠正的稳定性问题。", 26, base.ARCADE_MUTED, width - 56)
    return image


def _training_items(primary, secondary=None):
    exercise = base.exercise_of(primary)
    defaults = base.default_action_plan(exercise)
    def normalize(data):
        plan = dict(defaults); supplied = data.get("plan") or {}
        plan.update({key: value for key, value in supplied.items() if key != "drills"})
        drills = supplied.get("drills") or []
        if drills:
            technical = next((item for item in drills if "主项" in item.get("name", "")), None)
            non_technical = [item for item in drills if item is not technical]
            # Explicit V3 slots always win over the legacy drill list.  This
            # prevents a historical “主项” entry from replacing the clearly
            # prescribed technical pause drill on the public card.
            plan["technical"] = supplied.get("technical") or technical or drills[0]
            plan["main_drill"] = supplied.get("main_drill") or (non_technical[0] if non_technical else drills[0])
            plan["assist_drill"] = supplied.get("assist_drill") or (non_technical[1] if len(non_technical) > 1 else defaults["assist_drill"])
        return plan
    primary_plan = normalize(primary)
    second_plan = normalize(secondary or primary)
    def get(plan, key, fallback):
        item = plan.get(key) or fallback
        return {
            "name": item.get("name", "训练动作"),
            "dose": item.get("dose", "3组×5次"),
            "cue": item.get("cue", plan.get("cue", "动作保持可控")),
            "label": item.get("label"),
            "source_ids": item.get("source_ids") or [],
            "target_label": item.get("target_label") or "针对：本页已展示的动作问题",
        }
    technical = get(primary_plan, "technical", primary_plan.get("main_drill", defaults["main_drill"]))
    correction = get(primary_plan, "correction", primary_plan.get("assist_drill", defaults["assist_drill"]))
    # A stable secondary view cannot invent a corrective drill.  When the
    # primary has a real finding, its already-linked assistance is used.
    assistance_plan = primary_plan if _report_status(secondary) == "stable" else second_plan
    assistance = get(assistance_plan, "assistance", assistance_plan.get("assist_drill", defaults["assist_drill"]))
    return [
        ("技术主项", technical),
        ("机位一纠正", correction),
        (assistance.get("label") or ("机位二辅助" if secondary else "同问题辅助"), assistance),
    ]


def validate_training_links(primary, secondary=None):
    """Refuse a final card unless every visible drill cites prior evidence."""
    if _report_is_stable(primary, secondary):
        return
    evidence_ids = set()
    evidence_targets = {}
    for data in (primary, secondary):
        for evidence in ((data or {}).get("findings") or {}).get("evidence") or []:
            if isinstance(evidence, dict) and isinstance(evidence.get("id"), str):
                evidence_id = evidence["id"].strip()
                evidence_ids.add(evidence_id)
                training_target = evidence.get("training_target")
                if isinstance(training_target, str) and training_target.strip():
                    evidence_targets[evidence_id] = training_target.strip()
    for label, item in _training_items(primary, secondary):
        source_ids = item.get("source_ids") or []
        if not source_ids:
            raise ValueError(f"final training card {label} is missing source_ids")
        if any(source not in evidence_ids for source in source_ids):
            raise ValueError(f"final training card {label} references evidence not shown on Page 1 or 2")
        if any(source not in evidence_targets for source in source_ids):
            raise ValueError(f"final training card {label} references evidence without a training_target")
        target_label = str(item.get("target_label") or "")
        if not target_label.startswith("针对：") or target_label == "针对：":
            raise ValueError(f"final training card {label} is missing a user-visible target_label")
        expected = "针对：" + "＋".join(dict.fromkeys(evidence_targets[source] for source in source_ids))
        if target_label != expected:
            raise ValueError(f"final training card {label} target label does not match source training target")


def _report_status(data):
    findings = ((data or {}).get("findings") or {})
    explicit = findings.get("report_status")
    if explicit:
        return explicit
    # Legacy rear/foot-end files did not carry report_status.  Their explicit
    # no-muscle direction is the old representation of a stable camera, and
    # must not revive an unrelated primary-view prescription.
    if isinstance(findings.get("primary"), dict) and findings["primary"].get("no_muscle_direction") is True:
        return "stable"
    return "actionable_issue"


def _report_is_stable(primary, secondary=None):
    reports = [primary] + ([secondary] if secondary else [])
    return all(_report_status(data) == "stable" for data in reports)


def _stable_summary(primary, secondary=None):
    observations = []
    for data in (primary, secondary):
        if not data:
            continue
        for evidence in ((data.get("findings") or {}).get("evidence") or []):
            title = str(evidence.get("title") or "").strip()
            if title:
                observations.append(title)
    seen = list(dict.fromkeys(observations))
    return "；".join(seen) if seen else "当前机位未见明确待改善项。"


def _stable_closing_page(primary, secondary=None):
    image = base.arcade_canvas(); draw = ImageDraw.Draw(image)
    _header(draw, 4, base.exercise_of(primary), "本组保持即可", base.ARCADE_YELLOW, header_title="本组总结｜稳定结尾")
    base.arcade_panel(draw, (52, 342, 1028, 610), base.ARCADE_CYAN, width=STRUCTURAL_BORDER)
    draw.text((84, 374), "本次总评", font=base.ft(38), fill=base.ARCADE_CYAN)
    _text(draw, (84, 440), _stable_summary(primary, secondary), 34, base.ARCADE_TEXT, 880)
    _text(draw, (84, 526), "没有新增纠正训练；继续按照原有训练安排推进即可。", 26, base.ARCADE_MUTED, 880)
    base.arcade_panel(draw, (52, 634, 1028, 874), base.ARCADE_YELLOW, width=STRUCTURAL_BORDER)
    draw.text((84, 668), "报告结尾", font=base.ft(38), fill=base.ARCADE_YELLOW)
    _text(draw, (84, 748), "动作控制稳定，继续保持这套节奏。", 42, base.ARCADE_TEXT, 880)
    return image


def _score_summary(score):
    """Turn traceable internal items into the three reader-facing rows."""
    items = score.get("items") or []
    good = [item["title"] for item in items if item.get("status") == "稳定"]
    improve = [item for item in items if item.get("status") in {"轻微待改善", "明显待改善"}]
    neutral = [item["title"] for item in items if item.get("source") == "中性基准" or item.get("status") == "中性基准"]
    if not improve:
        return (
            "六项中可见项通过当前二维评分门槛。" if neutral else "六项证据均通过当前二维评分门槛。",
            "、".join(good[:3]) or "动作控制稳定",
            "本次未发现需要优先纠正的评分项。",
            f"部分关节受遮挡：{'、'.join(neutral)}未直接评分，按中性基准计入。" if neutral else "",
        )
    strongest = next((item for item in improve if item.get("status") == "明显待改善"), improve[0])
    return (
        f"主要需要复查：{strongest['title']}。",
        "、".join(good[:2]) or "已完成的动作环节可保持",
        "；".join(f"{item['title']}：{item['detail']}" for item in improve[:2]),
        f"部分关节受遮挡：{'、'.join(neutral)}按中性基准计入。" if neutral else "",
    )


def _score_badge(draw, center, grade):
    """Yellow arcade grade seal; grades deliberately have no plus/minus."""
    cx, cy = center
    draw.ellipse((cx - 126, cy - 126, cx + 126, cy + 126), fill="#0A142B", outline=base.ARCADE_YELLOW, width=7)
    draw.ellipse((cx - 108, cy - 108, cx + 108, cy + 108), outline="#7E6720", width=3)
    bbox = draw.textbbox((0, 0), grade, font=base.ft(78))
    draw.text((cx - (bbox[2] - bbox[0]) / 2, cy - 54), grade, font=base.ft(78), fill=base.ARCADE_YELLOW)


def _score_training_card(draw, index, label, item):
    box = SCORE_TRAINING_BOXES[index]
    x1, y1, x2, y2 = box
    color = (base.ARCADE_CYAN, base.ARCADE_PINK, base.ARCADE_YELLOW)[index]
    base.arcade_panel(draw, box, color, width=STRUCTURAL_BORDER)
    draw.text((x1 + 28, y1 + 18), f"{index + 1}｜{label}", font=base.ft(27), fill=color)
    _text(draw, (x1 + 28, y1 + 55), item["name"], 31, base.ARCADE_TEXT, 510)
    _text(draw, (x1 + 28, y1 + 101), item["dose"], 24, base.ARCADE_MUTED, 510)
    draw.line((x1 + 545, y1 + 24, x1 + 545, y2 - 24), fill="#405070", width=2)
    _text(draw, (x1 + 580, y1 + 33), item["target_label"], 22, color, 350)
    _text(draw, (x1 + 580, y1 + 78), f"口令：{item['cue']}", 21, base.ARCADE_TEXT, 350)


def _deadlift_unscorable_page(primary, secondary, score):
    image = base.arcade_canvas(); draw = ImageDraw.Draw(image)
    _header(draw, 4, "deadlift", "当前视频不足以完成完整评分", base.ARCADE_YELLOW, header_title="动作总评｜暂不评分")
    base.arcade_panel(draw, SCORE_BOX, base.ARCADE_YELLOW, width=STRUCTURAL_BORDER)
    draw.text((84, 236), "暂不显示分数或评级", font=base.ft(50), fill=base.ARCADE_TEXT)
    _text(draw, (84, 328), str(score.get("unavailable_reason") or "评分证据不足。"), 32, base.ARCADE_YELLOW, 850)
    _text(draw, (84, 440), "需要补齐：传统常规单次、侧面＋后方双机位，以及可信的杠铃与姿态关键点。", 27, base.ARCADE_TEXT, 840)
    _text(draw, (84, 548), "本页不生成训练处方，避免把不完整证据变成纠正建议。", 26, base.ARCADE_MUTED, 840)
    return image


def _deadlift_score_page(primary, secondary, score):
    """Fourth-page-only HUD settlement for a scorable conventional deadlift."""
    if not score.get("scorable"):
        return _deadlift_unscorable_page(primary, secondary, score)
    image = base.arcade_canvas(); draw = ImageDraw.Draw(image)
    _header(draw, 4, "deadlift", "", base.ARCADE_YELLOW, show_summary=False, header_title="动作总评｜这次硬拉表现如何")
    base.arcade_panel(draw, SCORE_BOX, base.ARCADE_YELLOW, width=STRUCTURAL_BORDER)
    total, grade = score["total"], score["grade"]
    draw.text((104, 236), str(total), font=base.ft(190), fill=base.ARCADE_YELLOW)
    draw.text((495, 400), "分", font=base.ft(49), fill=base.ARCADE_YELLOW)
    draw.line((610, 235, 610, 465), fill="#80651C", width=3)
    _score_badge(draw, (814, 346), grade)
    draw.text((738, 490), f"评级：{grade}", font=base.ft(31), fill=base.ARCADE_YELLOW)
    draw.line((82, 526, 998, 526), fill="#59647C", width=2)
    headline, good, improve, neutral = _score_summary(score)
    _text(draw, (116, 552), headline, 29, base.ARCADE_TEXT, 830)
    _text(draw, (116, 610), f"做得好：{good}", 25, base.ARCADE_CYAN, 830)
    _text(draw, (116, 664), f"待改善：{improve}", 24, base.ARCADE_PINK, 830)
    if neutral:
        _text(draw, (116, 704), neutral, 18, base.ARCADE_MUTED, 830)
    draw.text((52, 748), "下一次训练建议", font=base.ft(34), fill=base.ARCADE_YELLOW)
    if _report_is_stable(primary, secondary):
        # A fully stable scored report never receives filler prescriptions.
        _text(draw, (84, 840), "动作控制稳定，继续保持这套节奏。", 42, base.ARCADE_TEXT, 860)
        return image
    for index, (label, item) in enumerate(_training_items(primary, secondary)):
        _score_training_card(draw, index, label, item)
    return image


def _training_page(primary, secondary=None):
    score = primary.get("_deadlift_score")
    if base.exercise_of(primary) == "deadlift" and score is not None:
        return _deadlift_score_page(primary, secondary, score)
    if _report_is_stable(primary, secondary):
        return _stable_closing_page(primary, secondary)
    image = base.arcade_canvas(); draw = ImageDraw.Draw(image)
    _header(draw, 4, base.exercise_of(primary), "下一次训练，只做这三项", base.ARCADE_YELLOW)
    for i, (label, item) in enumerate(_training_items(primary, secondary)):
        _, y, _, _ = TRAINING_BOXES[i]
        color = (base.ARCADE_CYAN, base.ARCADE_PINK, base.ARCADE_YELLOW)[i]
        base.arcade_panel(draw, TRAINING_BOXES[i], color, width=STRUCTURAL_BORDER)
        draw.text((84, y + 24), f"{i+1}｜{label}", font=base.ft(28), fill=color)
        _text(draw, (84, y + 65), item["name"], 38, base.ARCADE_TEXT, 880)
        _text(draw, (84, y + 113), item["target_label"], 24, color, 880)
        _text(draw, (84, y + 153), item["dose"], 26, base.ARCADE_MUTED, 880)
        _text(draw, (84, y + 198), f"口令：{item['cue']}", 23, color, 880)
    return image


def _write(image, path):
    image.convert("RGB").save(path, "PNG", optimize=True)


def _preview(paths, out):
    pages = [Image.open(path).convert("RGB").resize((360, 480), Image.Resampling.LANCZOS) for path in paths]
    preview = Image.new("RGB", (360, 1920), base.ARCADE_BG)
    for i, page in enumerate(pages):
        preview.paste(page, (0, 480*i))
    preview.save(out, "JPEG", quality=90)


def render(primary, frames_dir, output_dir, secondary=None, secondary_frames_dir=None):
    output_dir = Path(output_dir); output_dir.mkdir(parents=True, exist_ok=True)
    if base.exercise_of(primary) == "deadlift" and secondary:
        primary["_deadlift_score"] = score_deadlift(
            primary, secondary, primary.get("_pose_tracking"), secondary.get("_pose_tracking"),
        )
    score = primary.get("_deadlift_score")
    if not (score and not score.get("scorable")):
        validate_training_links(primary, secondary)
    model = report_mode(primary, secondary)
    pages = [_photo_pair(primary, frames_dir, model["view_one"], 1)]
    pages.append(_photo_pair(secondary, secondary_frames_dir, model["view_two"], 2) if secondary else _filming_guidance(primary))
    pages.append(_muscle_page(primary, secondary))
    pages.append(_training_page(primary, secondary))
    paths = []
    for name, page in zip(PAGE_NAMES, pages):
        path = output_dir / name; _write(page, path); paths.append(path)
    _preview(paths, output_dir / "mobile-preview.jpg")
    return paths


VIEW_ORDER = {
    "deadlift": ({"side", "oblique_side"}, {"front", "rear"}),
    "bench_press": ({"side", "oblique_side"}, {"foot_end"}),
    "squat": ({"side", "oblique_side"}, {"rear"}),
}


def _manifest(frames_dir: Path) -> dict:
    path = Path(frames_dir) / "frame-manifest.json"
    if not path.is_file():
        raise ValueError(f"missing frame manifest: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid frame manifest {path}: {error}") from error
    source = data.get("source_video") or {}
    if not isinstance(source.get("sha256"), str) or len(source["sha256"]) != 64:
        raise ValueError(f"frame manifest {path} has no valid source_video.sha256")
    view = base.normalize_view(data.get("detected_view"))
    confidence = data.get("classification_confidence")
    if view == "unknown" or not isinstance(confidence, (int, float)) or confidence < 0.85:
        raise ValueError(f"frame manifest {path} camera view is uncertain (view={view}, confidence={confidence})")
    return data


def _tracked_source(tracking: dict, label: str) -> tuple[str, str]:
    source = tracking.get("source_video") or {}
    sha = source.get("sha256")
    detected = base.normalize_view(source.get("detected_view"))
    confidence = source.get("classification_confidence")
    if not isinstance(sha, str) or len(sha) != 64:
        raise ValueError(f"{label} tracking has no source_video.sha256; create a manifest and bind this tracking first")
    if detected == "unknown" or not isinstance(confidence, (int, float)) or confidence < 0.85:
        raise ValueError(f"{label} tracking has an uncertain source_video camera view")
    if base.normalize_view(_view(tracking)) != detected:
        raise ValueError(f"{label} tracking.view={_view(tracking)} disagrees with source_video.detected_view={detected}")
    return sha, detected


def bind_camera_inputs(primary: dict, primary_frames: Path, secondary: dict | None = None, secondary_frames: Path | None = None):
    """Bind tracking to frames by source hash, then return page-one/page-two order.

    This prevents a harmless-looking swapped CLI pair from producing cards that
    show the other camera's evidence.  It intentionally fails before any PNG
    is written if binding is incomplete or ambiguous.
    """
    if (secondary is None) != (secondary_frames is None):
        raise ValueError("secondary tracking and frames must be supplied together")
    if secondary is None:
        return primary, Path(primary_frames), None, None
    exercise = base.exercise_of(primary)
    if exercise != base.exercise_of(secondary):
        raise ValueError("both tracking files must belong to the same exercise")
    tracked = [(primary, "primary"), (secondary, "secondary")]
    frames = [(Path(primary_frames), "primary"), (Path(secondary_frames), "secondary")]
    tracked_by_sha = {}
    for data, label in tracked:
        sha, view = _tracked_source(data, label)
        if sha in tracked_by_sha:
            raise ValueError("two tracking files point to the same source video")
        tracked_by_sha[sha] = (data, view, label)
    frames_by_sha = {}
    for directory, label in frames:
        manifest = _manifest(directory)
        sha = manifest["source_video"]["sha256"]
        if sha in frames_by_sha:
            raise ValueError("two frame directories point to the same source video")
        frames_by_sha[sha] = (directory, base.normalize_view(manifest["detected_view"]), label)
    if set(tracked_by_sha) != set(frames_by_sha):
        raise ValueError("tracking source hash does not match either supplied frame manifest")
    bound = []
    for sha, (data, tracked_view, tracked_label) in tracked_by_sha.items():
        directory, manifest_view, frame_label = frames_by_sha[sha]
        if tracked_view != manifest_view:
            raise ValueError(f"{tracked_label} tracking view={tracked_view} does not match {frame_label} manifest view={manifest_view}")
        bound.append((data, directory, tracked_view))
    primary_views, secondary_views = VIEW_ORDER[exercise]
    first = [item for item in bound if item[2] in primary_views]
    second = [item for item in bound if item[2] in secondary_views]
    if len(first) != 1 or len(second) != 1:
        got = ", ".join(item[2] for item in bound)
        raise ValueError(f"unsupported {exercise} dual-camera pair: {got}; cannot determine Page 1/Page 2 safely")
    return first[0][0], first[0][1], second[0][0], second[0][1]


def main():
    parser = argparse.ArgumentParser(description="Render V3 view-first arcade cards")
    parser.add_argument("--tracking", type=Path, required=True)
    parser.add_argument("--frames-dir", type=Path, required=True)
    parser.add_argument("--secondary-tracking", type=Path)
    parser.add_argument("--secondary-frames-dir", type=Path)
    parser.add_argument("--pose-tracking", type=Path, help="Optional RTMPose JSON shown only as confidence-gated Page-1 key-frame markers")
    parser.add_argument("--secondary-pose-tracking", type=Path, help="Optional source-bound RTMPose JSON for Page 2 visual markers")
    parser.add_argument("--bar-tracking", type=Path, help="Strict side/oblique near-plate hub tracking JSON for Page 1")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if bool(args.secondary_tracking) != bool(args.secondary_frames_dir):
        parser.error("--secondary-tracking and --secondary-frames-dir must be supplied together")
    primary = json.loads(args.tracking.read_text(encoding="utf-8"))
    secondary = json.loads(args.secondary_tracking.read_text(encoding="utf-8")) if args.secondary_tracking else None
    pose = json.loads(args.pose_tracking.read_text(encoding="utf-8")) if args.pose_tracking else None
    secondary_pose = json.loads(args.secondary_pose_tracking.read_text(encoding="utf-8")) if args.secondary_pose_tracking else None
    bar_tracking = json.loads(args.bar_tracking.read_text(encoding="utf-8")) if args.bar_tracking else None
    try:
        primary, primary_frames, secondary, secondary_frames = bind_camera_inputs(
            primary, args.frames_dir, secondary, args.secondary_frames_dir
        )
        if bar_tracking:
            primary = compose_bar_tracking(primary, bar_tracking)
        if pose:
            pose_sha = ((pose.get("source_video") or {}).get("sha256"))
            tracking_sha = ((primary.get("source_video") or {}).get("sha256"))
            if pose_sha != tracking_sha:
                raise ValueError("pose tracking source hash does not match Page 1 tracking video")
            primary["_pose_tracking"] = pose
        if secondary_pose:
            if secondary is None:
                raise ValueError("secondary pose tracking requires a secondary video")
            pose_sha = ((secondary_pose.get("source_video") or {}).get("sha256"))
            tracking_sha = ((secondary.get("source_video") or {}).get("sha256"))
            if pose_sha != tracking_sha:
                raise ValueError("secondary pose tracking source hash does not match Page 2 tracking video")
            secondary["_pose_tracking"] = secondary_pose
        render(primary, primary_frames, args.output_dir, secondary, secondary_frames)
    except ValueError as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
