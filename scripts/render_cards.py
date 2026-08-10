#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps


SIZE = (1080, 1440)
FONT = "/System/Library/Fonts/Hiragino Sans GB.ttc"
BG, PAPER, INK, MUTED, LINE = "#F5F0E8", "#FFFDFC", "#27312F", "#69736F", "#D9D7D0"
GREEN, GREEN_L, GREEN_P = "#426F60", "#7FAF9B", "#E0ECE6"
ROSE, ROSE_L, ROSE_P = "#8B4F49", "#C9867F", "#F3E1DE"
BLUE, BLUE_L, BLUE_P = "#506F85", "#7E9FB8", "#E2EAF0"
PURPLE, PURPLE_P = "#77718B", "#E9E6EF"
ARCADE_BG, ARCADE_PANEL = "#070F22", "#101A35"
ARCADE_CYAN, ARCADE_PINK = "#25E6C1", "#FF4F8B"
ARCADE_BLUE, ARCADE_YELLOW, ARCADE_PURPLE = "#55A8FF", "#FFD85A", "#A98BFF"
ARCADE_TEXT, ARCADE_MUTED = "#EDF4FF", "#AAB7D1"

LABELS = {
    "deadlift": {"cn": "硬拉", "question": "杠铃直不直？髋有没有抢跑？", "mode": "离地垂线"},
    "squat": {"cn": "深蹲", "question": "杠铃有没有守住中足？", "mode": "中足参考线"},
    "bench_press": {"cn": "卧推", "question": "触胸与回肩路径顺不顺？", "mode": "J 型参考"},
}
LANDMARK_COLORS = {
    "hip": ROSE_L, "shoulder": BLUE_L, "knee": PURPLE, "ankle": "#B28A59",
    "wrist": ROSE_L, "elbow": PURPLE, "bar": GREEN_L,
}
LANDMARK_CN = {"hip": "髋", "shoulder": "肩", "knee": "膝", "ankle": "踝", "wrist": "腕", "elbow": "肘"}


def ft(size: int):
    return ImageFont.truetype(FONT, size)


def rounded(draw, box, fill=PAPER, radius=28, outline=None, width=2):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def wrap(draw, text, font, max_width):
    lines, current = [], ""
    for char in str(text):
        test = current + char
        if current and draw.textbbox((0, 0), test, font=font)[2] > max_width:
            lines.append(current); current = char
        else:
            current = test
    if current:
        lines.append(current)
    return "\n".join(lines)


def centered(draw, box, text, font, fill=INK, spacing=7):
    x1, y1, x2, y2 = box
    bounds = draw.multiline_textbbox((0, 0), text, font=font, spacing=spacing, align="center")
    x = x1 + ((x2 - x1) - (bounds[2] - bounds[0])) / 2
    y = y1 + ((y2 - y1) - (bounds[3] - bounds[1])) / 2
    draw.multiline_text((x, y), text, font=font, fill=fill, spacing=spacing, align="center")


def pill(draw, xy, text, fill=INK, size=23):
    font = ft(size); bounds = draw.textbbox((0, 0), text, font=font)
    width, height = bounds[2] + 36, bounds[3] - bounds[1] + 20
    x, y = xy; rounded(draw, (x, y, x + width, y + height), fill, height // 2)
    draw.text((x + 18, y + 7), text, font=font, fill="#FFFFFF")


def header(draw, page, kicker, title, subtitle="", title_size=58):
    pill(draw, (72, 56), f"{page}/5  {kicker}")
    draw.text((72, 128), title, font=ft(title_size), fill=INK)
    if subtitle:
        draw.text((74, 218), subtitle, font=ft(27), fill=MUTED)


def exercise_of(data):
    return data.get("exercise", "deadlift")


def normalize_view(view):
    value = str(view or "unknown").strip().lower().replace("-", "_")
    aliases = {
        "lateral": "side", "oblique": "oblique_side", "diagonal": "oblique_side",
        "front_end": "foot_end", "feet_end": "foot_end", "feet": "foot_end",
        "head": "head_end", "back": "rear",
    }
    return aliases.get(value, value)


def view_context(exercise, primary_view, secondary_view=None):
    primary, secondary = normalize_view(primary_view), normalize_view(secondary_view)
    side_views = {"side", "oblique_side"}
    standard = False
    if secondary_view is not None:
        pair = {primary, secondary}
        if exercise == "deadlift":
            standard = bool(pair & side_views) and bool(pair & {"front", "rear"})
        elif exercise == "bench_press":
            standard = bool(pair & side_views) and "foot_end" in pair
        elif exercise == "squat":
            standard = bool(pair & side_views) and "rear" in pair
    if secondary_view is None:
        limit = "单机位复盘：只报告当前画面能直接支持的趋势。"
    elif standard:
        limit = "双机位互相补充，但仍属于二维屏幕复盘。"
    else:
        limit = "视角限制：当前组合不是标准双机位，只保留各画面直接可见的证据。"
    return {"primary": primary, "secondary": secondary, "standard": standard, "limit": limit}


def view_label(view):
    return {
        "side": "侧面", "oblique_side": "斜侧面", "front": "前方", "rear": "后方",
        "foot_end": "脚端", "head_end": "头端", "unknown": "当前机位",
    }.get(normalize_view(view), "补充机位")


def landmarks_of(rep):
    result = dict(rep.get("landmarks") or {})
    for name in ("hip", "shoulder"):
        if rep.get(f"{name}_path") and name not in result:
            result[name] = rep[f"{name}_path"]
    return result


def frame_file(frames_dir: Path, index: int):
    for pattern in (f"frame_{index}_*.jpg", f"frame_{index:04d}_*.jpg", f"frame_{index:02d}_*.jpg"):
        matches = sorted(frames_dir.glob(pattern))
        if matches:
            return matches[0]
    raise FileNotFoundError(f"frame {index} not found in {frames_dir}")


def blur_face(image, box):
    if not box or len(box) != 4:
        return image.convert("RGB")
    result = image.convert("RGB").copy()
    x1, y1, x2, y2 = map(int, box)
    x1, y1, x2, y2 = max(0, x1), max(0, y1), min(result.width, x2), min(result.height, y2)
    if x2 <= x1 or y2 <= y1:
        return result
    crop = result.crop((x1, y1, x2, y2)).filter(ImageFilter.GaussianBlur(18))
    mask = Image.new("L", crop.size, 0)
    ImageDraw.Draw(mask).ellipse((2, 2, crop.width - 2, crop.height - 2), fill=240)
    result.paste(crop, (x1, y1), mask)
    return result


def source_crop(data, image):
    crop = (data.get("render") or {}).get("crop") or [0, 0, image.width, image.height]
    x1, y1, x2, y2 = map(float, crop)
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(image.width, x2), min(image.height, y2)
    if x2 - x1 < 10 or y2 - y1 < 10:
        return (0.0, 0.0, float(image.width), float(image.height))
    return (x1, y1, x2, y2)


def contained_box(source_size, box):
    """Return the largest centered box that contains a source without cropping."""
    sx, sy = source_size
    x1, y1, x2, y2 = box
    if sx <= 0 or sy <= 0:
        return box
    scale = min((x2 - x1) / sx, (y2 - y1) / sy)
    width = max(1, round(sx * scale))
    height = max(1, round(sy * scale))
    left = round(x1 + ((x2 - x1) - width) / 2)
    top = round(y1 + ((y2 - y1) - height) / 2)
    return (left, top, left + width, top + height)


def photo(data, frames_dir, index, out_size, fit="cover"):
    raw = Image.open(frame_file(frames_dir, index))
    privacy = data.get("privacy") or {}
    face_box = (privacy.get("face_boxes") or {}).get(str(index), privacy.get("face_box"))
    raw = blur_face(raw, face_box)
    if fit == "contain":
        crop = (0.0, 0.0, float(raw.width), float(raw.height))
        region = raw
        return region.resize(out_size, Image.Resampling.LANCZOS), crop
    if fit != "cover":
        raise ValueError(f"unknown photo fit mode: {fit}")
    crop = source_crop(data, raw)
    region = raw.crop(tuple(map(int, crop)))
    return ImageOps.fit(region, out_size, Image.Resampling.LANCZOS), crop


def paste_round(canvas, image, box, radius=28):
    x1, y1, x2, y2 = box
    if image.size != (x2 - x1, y2 - y1):
        image = ImageOps.fit(image, (x2 - x1, y2 - y1), Image.Resampling.LANCZOS)
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, image.width, image.height), radius=radius, fill=255)
    canvas.paste(image, (x1, y1), mask)


def map_point(point, crop, box):
    cx1, cy1, cx2, cy2 = crop; bx1, by1, bx2, by2 = box
    cw, ch, bw, bh = cx2 - cx1, cy2 - cy1, bx2 - bx1, by2 - by1
    scale = max(bw / cw, bh / ch)
    excess_x, excess_y = cw * scale - bw, ch * scale - bh
    return (bx1 + (point["x"] - cx1) * scale - excess_x / 2, by1 + (point["y"] - cy1) * scale - excess_y / 2)


def dotted(draw, start, end, fill=LINE, width=4):
    distance = max(1, math.dist(start, end)); count = max(1, int(distance / 14))
    for i in range(0, count, 2):
        a, b = i / count, min(1, (i + 1) / count)
        draw.line((start[0] + (end[0] - start[0]) * a, start[1] + (end[1] - start[1]) * a,
                   start[0] + (end[0] - start[0]) * b, start[1] + (end[1] - start[1]) * b), fill=fill, width=width)


def draw_path(draw, points, crop, box, color, width=8, radius=5):
    mapped = [map_point(point, crop, box) for point in points]
    if len(mapped) > 1:
        draw.line(mapped, fill="#FFFFFF", width=width + 5, joint="curve")
        draw.line(mapped, fill=color, width=width, joint="curve")
    for x, y in mapped:
        draw.ellipse((x - radius - 2, y - radius - 2, x + radius + 2, y + radius + 2), fill="#FFFFFF")
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)
    return mapped


def metrics(data, rep):
    exercise = exercise_of(data); bar = rep["bar_path"]; plate = float(data["plate_diameter_px"])
    if exercise == "deadlift":
        value = max(abs(float(p["x"]) - float(bar[0]["x"])) for p in bar) / plate * 100
        label = "接近垂直" if value <= 5 else "轻微漂移" if value <= 10 else "明显漂移"
        return {"value": value, "label": label, "unit": "最大横向偏移", "detail": "占可见杠片直径"}
    if exercise == "squat":
        midfoot = float(data["reference"]["midfoot_x"])
        value = max(abs(float(p["x"]) - midfoot) for p in bar) / plate * 100
        return {"value": value, "label": "结合中足与阶段复核", "unit": "最大中足偏离", "detail": "占可见杠片直径"}
    start = next(p for p in bar if p.get("phase") == "start")
    touch = next(p for p in bar if p.get("phase") == "touch")
    lockout = next(p for p in reversed(bar) if p.get("phase") == "lockout")
    value = (float(touch["x"]) - float(start["x"])) / plate * 100
    error = abs(float(lockout["x"]) - float(start["x"])) / plate * 100
    return {"value": value, "return": error, "label": "看触胸后是否上推回肩", "unit": "顶点→触胸横移", "detail": "正负号只表示屏幕方向"}


def bench_reference_phases(rep):
    """Return the three observable phases that define a bench J-path review."""
    path = rep["bar_path"]
    return [
        next(point for point in path if point.get("phase") == "start"),
        next(point for point in path if point.get("phase") == "touch"),
        next(point for point in reversed(path) if point.get("phase") == "lockout"),
    ]


def arcade_landmark_color(name):
    return {
        "hip": ARCADE_PINK,
        "wrist": ARCADE_PINK,
        "shoulder": ARCADE_BLUE,
        "knee": ARCADE_PURPLE,
        "elbow": ARCADE_PURPLE,
        "ankle": ARCADE_YELLOW,
    }.get(name)


def layout_bench_phase_labels(points, box):
    """Place start/touch/lockout labels with deterministic separation."""
    x1, y1, x2, y2 = box
    positions = [
        (min(max(x + 12, x1), x2 - 64), min(max(y - 35, y1), y2 - 34))
        for x, y in points
    ]
    if len(positions) >= 3:
        start_x, start_y = positions[0]
        lock_x, lock_y = positions[2]
        if abs(start_x - lock_x) < 72 and abs(start_y - lock_y) < 34:
            lock_y = min(y2 - 34, start_y + 38)
            if abs(start_y - lock_y) < 34:
                start_y = max(y1, lock_y - 38)
            positions[0] = (start_x, start_y)
            positions[2] = (lock_x, lock_y)
    return positions


def default_findings(exercise):
    return {
        "deadlift": (
            [("起始髋位", "避免主动蹲低"), ("预拉时序", "腹压·背阔·拉松量"), ("肩髋同步", "离地初段保持角度"), ("颈部位置", "视线前下方")],
            [("杠铃贴身", "减少额外力矩"), ("全脚掌稳定", "压力没有明显前移"), ("腰背形态", "全程基本稳定"), ("顶端锁定", "无需额外后仰")]),
        "squat": (
            [("杠铃—中足", "看漂移发生在哪一段"), ("底部稳定", "避免失去腹压"), ("胸髋同步", "上升初段别折叠"), ("脚掌压力", "保持三点支撑")],
            [("深度一致", "每次使用同一标准"), ("下蹲节奏", "可控而不松散"), ("膝髋配合", "不强求固定先后"), ("锁定稳定", "站直不过伸")]),
        "bench_press": (
            [("触胸位置", "每次落点一致"), ("推起方向", "上推并回向肩部"), ("腕肘堆叠", "减少腕部折叠"), ("腿驱时序", "触胸前已建立张力")],
            [("肩胛稳定", "上背持续支撑"), ("臀部接触", "遵循目标规则"), ("下降可控", "避免失控砸胸"), ("锁定完整", "肩带不突然前探")]),
    }[exercise]


def findings(data):
    improve, good = default_findings(exercise_of(data)); supplied = data.get("findings") or {}
    def convert(items, fallback):
        if isinstance(items, str) and items.strip():
            return [("本次观察", items)]
        result = []
        for item in items or []:
            result.append((item.get("title", "观察项"), item.get("detail", "结合原帧复核")))
        return (result + fallback)[:4]
    return convert(supplied.get("improve"), improve), convert(supplied.get("good"), good)


def finding(title, detail):
    return {"title": title, "detail": detail}


def default_primary(exercise):
    return {
        "deadlift": finding("起拉时序", "杠铃离地前先确认髋、肩与预拉是否同步。"),
        "squat": finding("底部协同", "先确认杠铃相对中足，再看胸髋是否一起离开底部。"),
        "bench_press": finding("触胸与回程", "先确认落点一致，再看推起是否回向肩侧。"),
    }[exercise]


def default_action_plan(exercise):
    actions = {
        "deadlift": {
            "cue": "微收下巴，腋下夹紧后推地",
            "technical": {"name": "常规硬拉（每次落地重置）", "dose": "60–70%｜3组×3次", "cue": "每次落地重置后再推地"},
            "correction": {"name": "暂停硬拉（离地3–5厘米停1秒）", "dose": "55–65%｜3组×3次", "cue": "杠铃离地3–5厘米停1秒"},
            "assistance": {"name": "绳索直臂下拉", "dose": "3组×10–12次", "cue": "肘微弯但不屈肘，腋下夹紧"},
        },
        "squat": {
            "cue": "全脚掌压稳，底部后肩髋一起起",
            "technical": {"name": "常规深蹲（每次站稳重置）", "dose": "60–70%｜3组×4次", "cue": "每次站稳重置后下降"},
            "correction": {"name": "暂停深蹲（底部停1–2秒）", "dose": "60–70%｜3组×4次", "cue": "底部停1–2秒，压力留在全脚掌"},
            "assistance": {"name": "3秒离心深蹲（自锁定起控制下降）", "dose": "轻重量｜3组×5次", "cue": "3秒控制下降"},
        },
        "bench_press": {
            "cue": "触胸停稳后，双手同步推起",
            "technical": {"name": "常规卧推（每次触胸停稳）", "dose": "60–70%｜3组×4次", "cue": "每次触胸停稳后再推"},
            "correction": {"name": "暂停卧推（触胸停1秒）", "dose": "60–70%｜3组×4次", "cue": "触胸停1秒，保持上背压力"},
            "assistance": {"name": "双手哑铃农夫走", "dose": "中轻重量｜3组×20米", "cue": "两手同重量，掌根承重，手腕中立"},
        },
    }[exercise]
    # Legacy callers still use these aliases; V3 reads the explicit slots.
    actions["main_drill"] = actions["correction"]
    actions["assist_drill"] = actions["assistance"]
    return actions


def report_model(data):
    """Return the fixed beginner-facing report contract for one view.

    Data keeps all directly visible observations, but cards foreground one
    primary finding. `unavailable` is the sole trigger for a re-shoot note.
    """
    exercise = exercise_of(data)
    supplied = data.get("findings") or {}
    improve_default, good_default = findings({"exercise": exercise})

    def group(name, fallback=()):
        items = supplied.get(name, fallback)
        if isinstance(items, str) and items.strip():
            labels = {"improve": "待改善", "good": "做得好", "unavailable": "无法判断"}
            return [finding(labels[name], items)]
        return [finding(item.get("title", "观察项"), item.get("detail", "结合原帧复核")) for item in items]

    primary = supplied.get("primary")
    if primary is None:
        legacy_improve = supplied.get("improve")
        if isinstance(legacy_improve, str) and legacy_improve.strip():
            legacy_titles = {"deadlift": "起拉时序", "squat": "动作观察", "bench_press": "动作观察"}
            primary = finding(legacy_titles[exercise], legacy_improve)
        elif isinstance(legacy_improve, list) and legacy_improve:
            primary = legacy_improve[0]
        else:
            primary = default_primary(exercise)
    plan = default_action_plan(exercise).copy()
    supplied_plan = data.get("plan") or {}
    for key in ("cue", "main_drill", "assist_drill"):
        if supplied_plan.get(key):
            plan[key] = supplied_plan[key]
    checks = supplied_plan.get("checks") or default_plan(exercise)[1]
    return {
        "primary": finding(primary["title"], primary["detail"]),
        "improve": group("improve", [finding(*item) for item in improve_default]),
        "good": group("good", [finding(*item) for item in good_default]),
        "unavailable": group("unavailable"),
        "plan": plan,
        "checks": list(checks)[:4],
        "show_recapture": bool(supplied.get("unavailable")),
    }


def card_cover(data, frames_dir, secondary_data=None, secondary_frames_dir=None):
    exercise = exercise_of(data); info = LABELS[exercise]; rep = data["repetitions"][-1]
    image = Image.new("RGB", SIZE, BG); draw = ImageDraw.Draw(image)
    pill(draw, (72, 58), f"1/5  {len(data['repetitions'])}次逐帧")
    draw.text((72, 140), f"{info['cn']}轨迹复盘", font=ft(72), fill=INK)
    draw.multiline_text((72, 255), wrap(draw, info["question"], ft(48), 900), font=ft(48), fill=GREEN, spacing=12)
    first, last = rep["bar_path"][0]["frame"], rep["bar_path"][-1]["frame"]
    left, right = (72, 470, 522, 1030), (558, 470, 1008, 1030)
    p1, _ = photo(data, frames_dir, first, (450, 560))
    if secondary_data is not None:
        secondary_rep = secondary_data["repetitions"][-1]
        secondary_frame = secondary_rep["bar_path"][-1]["frame"]
        p2, crop = photo(secondary_data, secondary_frames_dir, secondary_frame, (450, 560))
    else:
        p2, crop = photo(data, frames_dir, last, (450, 560))
    paste_round(image, p1, left); paste_round(image, p2, right)
    draw = ImageDraw.Draw(image); pill(draw, (92, 490), view_label(data.get("view")))
    pill(draw, (578, 490), view_label(secondary_data.get("view")) if secondary_data else "关键帧")
    if secondary_data is None:
        draw_path(draw, rep["bar_path"], crop, right, GREEN_L, 9, 6)
    rounded(draw, (72, 1080, 1008, 1262), PAPER, 32, LINE)
    draw.text((108, 1112), "分析不是只画一条线", font=ft(31), fill=MUTED)
    draw.text((108, 1165), f"参考：{info['mode']}  ·  再看关节时序", font=ft(34), fill=INK)
    rounded(draw, (72, 1300, 1008, 1372), INK, 22)
    centered(draw, (92, 1306, 988, 1365), "下一页：杠铃路径与动作专属参考 →", ft(26), "#FFFFFF")
    return image


def card_bar(data, frames_dir):
    exercise = exercise_of(data); info = LABELS[exercise]; rep = data["repetitions"][-1]; stat = metrics(data, rep)
    image = Image.new("RGB", SIZE, BG); draw = ImageDraw.Draw(image)
    title = "杠铃路径怎么走？" if exercise == "bench_press" else "杠铃有没有偏离参考？"
    header(draw, 2, "杠铃轨迹", title, f"绿色＝实际路径 · 灰色＝{info['mode']}", 54)
    box = (72, 300, 700, 1010); frame = rep["bar_path"][-1]["frame"]
    p, crop = photo(data, frames_dir, frame, (628, 710)); paste_round(image, p, box)
    draw = ImageDraw.Draw(image); mapped = draw_path(draw, rep["bar_path"], crop, box, GREEN_L, 10, 6)
    if exercise == "deadlift":
        dotted(draw, (mapped[0][0], 320), (mapped[0][0], 990), "#A8ACA9")
    elif exercise == "squat":
        ref = map_point({"x": data["reference"]["midfoot_x"], "y": crop[1]}, crop, box)[0]
        dotted(draw, (ref, 320), (ref, 990), "#A8ACA9")
    else:
        phases = {p.get("phase"): p for p in rep["bar_path"] if p.get("phase") in {"start", "touch", "lockout"}}
        ideal = [map_point(phases[k], crop, box) for k in ("start", "touch", "lockout")]
        for a, b in zip(ideal, ideal[1:]): dotted(draw, a, b, "#A8ACA9", 4)
    rounded(draw, (730, 300, 1008, 520), GREEN_P)
    draw.text((756, 328), stat["unit"], font=ft(24), fill=GREEN)
    draw.text((756, 380), f"{stat['value']:+.1f}%" if exercise == "bench_press" else f"{stat['value']:.1f}%", font=ft(50), fill=INK)
    draw.text((756, 452), stat["detail"], font=ft(19), fill=MUTED)
    rounded(draw, (730, 548, 1008, 770), PAPER, 28, LINE)
    draw.text((756, 577), "轨迹解释", font=ft(24), fill=MUTED)
    draw.multiline_text((756, 630), wrap(draw, stat["label"], ft(28), 220), font=ft(28), fill=INK, spacing=8)
    if exercise == "bench_press":
        draw.text((756, 714), f"锁定回位误差 {stat['return']:.1f}%", font=ft(20), fill=ROSE)
    rounded(draw, (730, 798, 1008, 1010), ROSE_P)
    note = "卧推合理路径通常是斜向/J 型，不以垂直为目标。" if exercise == "bench_press" else "百分比是本视频二维复盘，不是伤病阈值。"
    draw.multiline_text((756, 830), wrap(draw, note, ft(24), 220), font=ft(24), fill=INK, spacing=9)
    draw.text((72, 1050), "每次重复的小轨迹", font=ft(34), fill=INK)
    reps = data["repetitions"]; gap = 20; width = (936 - gap * (len(reps) - 1)) // len(reps)
    for i, item in enumerate(reps):
        x1 = 72 + i * (width + gap); box2 = (x1, 1110, x1 + width, 1325); rounded(draw, box2, PAPER, 22, LINE)
        pts = item["bar_path"]; xs = [p["x"] for p in pts]; ys = [p["y"] for p in pts]
        sx = max(xs) - min(xs) or 1; sy = max(ys) - min(ys) or 1
        mini = [(x1 + 28 + (p["x"] - min(xs)) / sx * (width - 56), 1290 - (max(ys) - p["y"]) / sy * 125) for p in pts]
        draw.line(mini, fill=GREEN_L, width=6, joint="curve"); draw.text((x1 + 18, 1125), f"第{item.get('rep')}次", font=ft(21), fill=INK)
    draw.text((74, 1360), "二维屏幕轨迹会受机位、透视与标记误差影响。", font=ft(21), fill=MUTED)
    return image


def card_joints(data, frames_dir):
    exercise = exercise_of(data); rep = data["repetitions"][-1]; landmarks = landmarks_of(rep)
    titles = {"deadlift": "髋有没有在杠离地前抢跑？", "squat": "髋、膝、踝配合是否稳定？", "bench_press": "腕、肘、肩与杠铃是否协调？"}
    header_title = titles[exercise]
    image = Image.new("RGB", SIZE, BG); draw = ImageDraw.Draw(image)
    header(draw, 3, "关节时序", header_title, "同一物理标志点逐帧追踪", 49)
    box = (72, 300, 1008, 935); p, crop = photo(data, frames_dir, rep["bar_path"][-1]["frame"], (936, 635)); paste_round(image, p, box)
    draw = ImageDraw.Draw(image); draw_path(draw, rep["bar_path"], crop, box, GREEN_L, 9, 6)
    for name, points in landmarks.items():
        if name in LANDMARK_COLORS:
            draw_path(draw, points, crop, box, LANDMARK_COLORS[name], 7, 4)
    rounded(draw, (72, 970, 1008, 1065), PAPER, 24, LINE)
    legend = [(GREEN_L, "杠铃")] + [(LANDMARK_COLORS[name], LANDMARK_CN.get(name, name)) for name in landmarks if name in LANDMARK_COLORS]
    spacing = 840 // max(1, len(legend))
    for i, (color, label) in enumerate(legend):
        x = 110 + i * spacing; draw.line((x, 1018, x + 46, 1018), fill=color, width=8); draw.text((x + 58, 996), label, font=ft(25), fill=INK)
    messages = {
        "deadlift": ["杠未离地时髋是否明显上升", "肩髋是否同步，躯干角度是否突变", "髋向前上方本身是正常伸髋"],
        "squat": ["下降与反向阶段是否保持腹压", "上升初段胸髋是否一起离开底部", "杠铃偏移要结合脚掌和机位解释"],
        "bench_press": ["触胸时腕肘在画面内是否合理堆叠", "推起是否上推并回向肩部", "腿驱、上背与触胸节奏是否一致"],
    }[exercise]
    for i, text in enumerate(messages):
        y = 1100 + i * 82; rounded(draw, (72, y, 1008, y + 64), [GREEN_P, BLUE_P, ROSE_P][i], 20)
        draw.ellipse((94, y + 16, 126, y + 48), fill=[GREEN, BLUE, ROSE][i]); centered(draw, (94, y + 16, 126, y + 48), str(i + 1), ft(16), "#FFFFFF")
        draw.text((146, y + 15), text, font=ft(25), fill=INK)
    draw.text((74, 1365), "轨迹用于定位时序问题，不单独证明肌力短板。", font=ft(21), fill=MUTED)
    return image


def card_findings(data, frames_dir, secondary_data=None, secondary_frames_dir=None):
    exercise = exercise_of(data); improve, good = findings(data); rep = data["repetitions"][-1]
    image = Image.new("RGB", SIZE, BG); draw = ImageDraw.Draw(image)
    header(draw, 4, "综合观察", "轨迹之外，还要看什么？", "把待改善和做得好的放在一起", 54)
    p1, _ = photo(data, frames_dir, rep["bar_path"][0]["frame"], (450, 340))
    if secondary_data is not None:
        secondary_rep = secondary_data["repetitions"][-1]
        p2, _ = photo(secondary_data, secondary_frames_dir, secondary_rep["bar_path"][-1]["frame"], (450, 340))
    else:
        p2, _ = photo(data, frames_dir, rep["bar_path"][-1]["frame"], (450, 340))
    paste_round(image, p1, (72, 295, 522, 635)); paste_round(image, p2, (558, 295, 1008, 635))
    draw = ImageDraw.Draw(image); pill(draw, (92, 315), view_label(data.get("view")), ROSE)
    pill(draw, (578, 315), view_label(secondary_data.get("view")) if secondary_data else "完成/锁定", GREEN)
    draw.text((72, 674), "待改善", font=ft(34), fill=ROSE); draw.text((558, 674), "做得好的", font=ft(34), fill=GREEN)
    for i in range(4):
        y = 725 + i * 132
        for x, items, fill, color in ((72, improve, ROSE_P, ROSE), (558, good, GREEN_P, GREEN)):
            rounded(draw, (x, y, x + 450, y + 112), fill, 24)
            draw.text((x + 24, y + 16), items[i][0], font=ft(26), fill=INK)
            draw.text((x + 24, y + 63), items[i][1], font=ft(21), fill=MUTED)
    context = view_context(exercise, data.get("view"), secondary_data.get("view") if secondary_data else None)
    limit = context["limit"]
    rounded(draw, (72, 1270, 1008, 1360), INK, 22); centered(draw, (92, 1280, 988, 1350), limit, ft(23), "#FFFFFF")
    return image


def default_plan(exercise):
    return {
        "deadlift": (["暂停硬拉｜离地3–5cm暂停", "技术主项｜每次落地重置", "罗马尼亚硬拉｜练后侧链张力"], ["杠铃接近垂直", "杠未离地髋不抢跑", "肩髋同步且腰颈稳定", "连续3次训练无疼痛"]),
        "squat": (["节奏深蹲｜3秒下降", "暂停深蹲｜底部停1–2秒", "技术主项｜保留2–3次余力"], ["杠铃大体守住中足", "底部深度一致", "胸髋同步离开底部", "全脚掌稳定且无疼痛"]),
        "bench_press": (["暂停卧推｜触胸停1秒", "Spoto卧推｜离胸短暂停", "技术主项｜固定触胸点"], ["下降落点重复", "推起回向肩部", "腕肘稳定、臀部接触", "上背稳定且无疼痛"]),
    }[exercise]


def card_plan(data):
    exercise = exercise_of(data); drills, checks = default_plan(exercise); supplied = data.get("plan") or {}
    if supplied.get("drills"):
        drills = [f"{item.get('name', '练习')}｜{item.get('dose') or item.get('cue', '')}" for item in supplied["drills"]][:3]
    checks = (supplied.get("checks") or checks)[:4]
    image = Image.new("RGB", SIZE, BG); draw = ImageDraw.Draw(image)
    header(draw, 5, "纠正与验收", "下一次训练怎么验证？", "先用可重复的技术组确认，再加重量", 54)
    draw.text((72, 300), "纠正练习", font=ft(36), fill=INK)
    for i, text in enumerate(drills):
        y = 355 + i * 135; rounded(draw, (72, y, 1008, y + 108), [GREEN_P, BLUE_P, PURPLE_P][i], 26)
        draw.ellipse((98, y + 27, 152, y + 81), fill=[GREEN, BLUE, PURPLE][i]); centered(draw, (98, y + 27, 152, y + 81), str(i + 1), ft(22), "#FFFFFF")
        draw.text((178, y + 30), text, font=ft(29), fill=INK)
    draw.text((72, 790), "验收清单", font=ft(36), fill=INK)
    for i, text in enumerate(checks):
        x = 72 + (i % 2) * 474; y = 850 + (i // 2) * 150
        rounded(draw, (x, y, x + 450, y + 120), PAPER, 25, LINE)
        draw.ellipse((x + 24, y + 33, x + 74, y + 83), outline=GREEN, width=4)
        draw.line((x + 37, y + 58, x + 48, y + 70, x + 65, y + 48), fill=GREEN, width=4)
        draw.multiline_text((x + 92, y + 28), wrap(draw, text, ft(25), 320), font=ft(25), fill=INK, spacing=6)
    rounded(draw, (72, 1175, 1008, 1278), GREEN, 25)
    centered(draw, (100, 1190, 980, 1264), "连续多次技术组稳定、无疼痛，再逐步恢复重重量", ft(28), "#FFFFFF")
    rounded(draw, (72, 1310, 1008, 1380), ROSE_P, 20)
    centered(draw, (90, 1317, 990, 1372), "尖锐疼痛、麻木、放射痛或力量骤降：停止重负荷并评估", ft(21), ROSE)
    return image


def arcade_canvas():
    image = Image.new("RGB", SIZE, ARCADE_BG)
    draw = ImageDraw.Draw(image)
    for y in range(24, SIZE[1], 24):
        draw.line((0, y, SIZE[0], y), fill="#0C1933", width=1)
    for x in range(48, SIZE[0], 48):
        draw.line((x, 0, x, SIZE[1]), fill="#0A162D", width=1)
    return image


def arcade_panel(draw, box, color=ARCADE_CYAN, fill=ARCADE_PANEL, width=4):
    draw.rounded_rectangle(box, radius=18, fill=fill, outline=color, width=width)


def arcade_header(draw, page, title, kicker, color=ARCADE_CYAN):
    arcade_panel(draw, (60, 52, 1020, 146), color)
    draw.text((88, 74), f"第{page}关｜{kicker}", font=ft(31), fill=ARCADE_TEXT)
    draw.text((844, 78), f"第 {page} / 4 页", font=ft(22), fill=color)
    arcade_panel(draw, (60, 176, 1020, 316), color)
    draw.text((88, 211), title, font=ft(48), fill=ARCADE_TEXT)


def arcade_photo(canvas, data, frames_dir, frame, box, color, tag, fit="cover"):
    x1, y1, x2, y2 = box
    ImageDraw.Draw(canvas).rounded_rectangle(box, radius=18, fill=ARCADE_PANEL, outline=color, width=4)
    inner = (x1 + 6, y1 + 56, x2 - 6, y2 - 6)
    if fit == "contain":
        with Image.open(frame_file(frames_dir, frame)) as source:
            content_box = contained_box(source.size, inner)
    else:
        content_box = inner
    shot, crop = photo(data, frames_dir, frame,
                       (content_box[2] - content_box[0], content_box[3] - content_box[1]), fit=fit)
    paste_round(canvas, shot, content_box, 12)
    draw = ImageDraw.Draw(canvas)
    draw.text((x1 + 20, y1 + 13), tag, font=ft(25), fill=color)
    return crop, content_box


def arcade_trace_mapped(draw, mapped, start_color=ARCADE_CYAN, end_color=ARCADE_BLUE, width=9):
    if len(mapped) < 2:
        return mapped
    start_rgb = tuple(int(start_color[i:i + 2], 16) for i in (1, 3, 5))
    end_rgb = tuple(int(end_color[i:i + 2], 16) for i in (1, 3, 5))
    for index, (a, b) in enumerate(zip(mapped, mapped[1:])):
        ratio = index / max(1, len(mapped) - 2)
        color = tuple(round(s + (e - s) * ratio) for s, e in zip(start_rgb, end_rgb))
        draw.line((*a, *b), fill=color, width=width)
    for index in sorted({max(0, len(mapped) // 3), max(0, len(mapped) * 2 // 3)}):
        if index >= len(mapped) - 1:
            continue
        a, b = mapped[index], mapped[index + 1]
        angle = math.atan2(b[1] - a[1], b[0] - a[0])
        tip = (a[0] * .35 + b[0] * .65, a[1] * .35 + b[1] * .65)
        size = 18
        left = (tip[0] - size * math.cos(angle - .55), tip[1] - size * math.sin(angle - .55))
        right = (tip[0] - size * math.cos(angle + .55), tip[1] - size * math.sin(angle + .55))
        draw.polygon((tip, left, right), fill=end_color)
    return mapped


def arcade_trace(draw, points, crop, box, start_color=ARCADE_CYAN, end_color=ARCADE_BLUE, width=9):
    mapped = []
    for point in points:
        x, y = map_point(point, crop, box)
        mapped.append((min(max(x, box[0]), box[2]), min(max(y, box[1]), box[3])))
    return arcade_trace_mapped(draw, mapped, start_color, end_color, width)


def bench_summary_touch_frames(data):
    first, last = data["repetitions"][0], data["repetitions"][-1]
    return (
        next(point["frame"] for point in first["bar_path"] if point.get("phase") == "touch"),
        next(point["frame"] for point in last["bar_path"] if point.get("phase") == "touch"),
    )


def bench_end_paths(rep):
    phases = {int(point["frame"]): point.get("phase") for point in rep["bar_path"]}
    landmarks = landmarks_of(rep)
    result = {}
    for side in ("screen_left", "screen_right"):
        result[side] = [
            {**point, "phase": phases.get(int(point["frame"]))}
            for point in landmarks[f"wrist_{side}"]
        ]
    return result


def bench_beginner_plan():
    return {
        "tasks": [
            "装备检查｜换平底防滑鞋",
            "暂停卧推｜60–70%｜3组×4–5次",
            "3秒离心卧推｜轻重量｜3组×5次",
            "技术主项｜每组保留2–3次余力",
        ],
        "checks": [
            "两端同时离胸",
            "同机位下高度差缩小",
            "脚端看手腕大致在肘上方",
            "上背和臀部稳定接触且无疼痛",
        ],
        "recapture": "复拍：卧推凳高度正侧面＋脚端｜60帧/秒",
    }


def bench_card_headlines():
    return {
        1: "4次卧推完成，触胸左端略低",
        2: "杠铃两端整体同步移动",
        3: "触胸左端略低，但两端都能推起",
        4: "按这4步练，再用双机位复拍",
    }


def bench_offset_lanes(mapped, offset=14):
    """Separate descending and pressing display lanes without altering height."""
    return ([(x - offset, y) for x, y in mapped], [(x + offset, y) for x, y in mapped])


def bench_bar_limit_lines(draw):
    """Keep the foot-end limitation inside the narrow right-hand card."""
    return wrap(draw, "侧面斜向杠路需要正侧面视频判断。", ft(23), 180).splitlines()


def arcade_bench_foot_end_summary(data, frames_dir):
    first, last = data["repetitions"][0], data["repetitions"][-1]
    first_frame, last_frame = bench_summary_touch_frames(data)
    model = report_model(data)
    image = arcade_canvas(); draw = ImageDraw.Draw(image)
    arcade_header(draw, 1, f"主问题｜{model['primary']['title']}", "动作总评")
    first_time = next(point["time"] for point in first["bar_path"] if point["frame"] == first_frame)
    last_time = next(point["time"] for point in last["bar_path"] if point["frame"] == last_frame)
    crop1, box1 = arcade_photo(image, data, frames_dir, first_frame, (60, 352, 516, 860), ARCADE_PINK, f"① {first_time:.2f}秒｜第1次触胸")
    crop2, box2 = arcade_photo(image, data, frames_dir, last_frame, (564, 352, 1020, 860), ARCADE_CYAN, f"② {last_time:.2f}秒｜第4次触胸")

    def touch_bar(rep, crop, box, color):
        paths = bench_end_paths(rep)
        left = next(point for point in paths["screen_left"] if point.get("phase") == "touch")
        right = next(point for point in paths["screen_right"] if point.get("phase") == "touch")
        a, b = map_point(left, crop, box), map_point(right, crop, box)
        draw.line((*a, *b), fill=color, width=7)
        for x, y in (a, b):
            draw.ellipse((x - 7, y - 7, x + 7, y + 7), fill=ARCADE_BG, outline=color, width=4)

    touch_bar(first, crop1, box1, ARCADE_PINK)
    touch_bar(last, crop2, box2, ARCADE_CYAN)
    arcade_panel(draw, (60, 898, 1020, 1074), ARCADE_YELLOW)
    draw.text((88, 928), "看到了什么", font=ft(25), fill=ARCADE_YELLOW)
    draw.multiline_text((88, 974), wrap(draw, model["primary"]["detail"], ft(28), 850), font=ft(28), fill=ARCADE_TEXT, spacing=8)
    arcade_panel(draw, (60, 1110, 516, 1244), ARCADE_CYAN)
    draw.text((86, 1134), "做得好", font=ft(24), fill=ARCADE_CYAN)
    good = model["good"][0]
    draw.multiline_text((86, 1180), wrap(draw, f"{good['title']}｜{good['detail']}", ft(21), 390), font=ft(21), fill=ARCADE_TEXT, spacing=5)
    arcade_panel(draw, (564, 1110, 1020, 1244), ARCADE_PINK)
    draw.text((590, 1134), "其他待改善", font=ft(24), fill=ARCADE_PINK)
    improve = model["improve"][0]
    draw.multiline_text((590, 1176), wrap(draw, f"{improve['title']}｜{improve['detail']}", ft(21), 390), font=ft(21), fill=ARCADE_TEXT, spacing=5)
    limit = model["unavailable"][0]["detail"] if model["unavailable"] else "脚端机位只报告左右同步趋势，不判断侧面斜向杠路。"
    draw.text((72, 1283), limit, font=ft(22), fill=ARCADE_MUTED)
    return image


def arcade_bench_foot_end_bar(data, frames_dir):
    rep = data["repetitions"][-1]
    paths = bench_end_paths(rep)
    touch_frame = next(point["frame"] for point in rep["bar_path"] if point.get("phase") == "touch")
    image = arcade_canvas(); draw = ImageDraw.Draw(image)
    arcade_header(draw, 2, bench_card_headlines()[2], "杠铃轨迹")
    crop, inner = arcade_photo(image, data, frames_dir, touch_frame, (60, 352, 760, 1088), ARCADE_CYAN, "青绿↓下降轨迹｜蓝色↑推起轨迹")
    mapped_touch = {}
    for side, label, label_x in (("screen_left", "画面左端", inner[0] + 24), ("screen_right", "画面右端", inner[2] - 132)):
        points = paths[side]
        touch_index = next(index for index, point in enumerate(points) if point.get("phase") == "touch")
        descent = points[:touch_index + 1]
        ascent = points[touch_index:]
        mapped = [map_point(point, crop, inner) for point in points]
        descent_actual = mapped[:touch_index + 1]
        ascent_actual = mapped[touch_index:]
        descent_lane, _ = bench_offset_lanes(descent_actual)
        _, ascent_lane = bench_offset_lanes(ascent_actual)
        arcade_trace_mapped(draw, descent_lane, "#8FF7E2", ARCADE_CYAN, 8)
        arcade_trace_mapped(draw, ascent_lane, "#9CCBFF", ARCADE_BLUE, 8)
        for actual, lane in ((descent_actual[0], descent_lane[0]), (descent_actual[-1], descent_lane[-1]),
                             (ascent_actual[-1], ascent_lane[-1])):
            draw.line((*actual, *lane), fill="#A9B5CD", width=2)
        mapped_touch[side] = descent_actual[-1]
        draw.text((label_x, inner[1] + 16), label, font=ft(21), fill=ARCADE_TEXT, stroke_width=2, stroke_fill=ARCADE_BG)
    reference_y = mapped_touch["screen_right"][1]
    dotted(draw, (inner[0] + 12, reference_y), (inner[2] - 12, reference_y), "#A9B5CD", 3)
    draw.line((*mapped_touch["screen_left"], *mapped_touch["screen_right"]), fill=ARCADE_PINK, width=6)
    draw.text((inner[0] + 24, reference_y + 16), "触胸：画面左端略低", font=ft(22), fill=ARCADE_PINK, stroke_width=2, stroke_fill=ARCADE_BG)
    arcade_panel(draw, (792, 352, 1020, 608), ARCADE_YELLOW)
    draw.text((816, 384), "轨迹结论", font=ft(26), fill=ARCADE_YELLOW)
    draw.multiline_text((816, 442), "两端整体\n同向移动", font=ft(30), fill=ARCADE_TEXT, spacing=8)
    arcade_panel(draw, (792, 642, 1020, 836), ARCADE_PINK)
    draw.text((816, 674), "触胸观察", font=ft(25), fill=ARCADE_PINK)
    draw.multiline_text((816, 726), "画面左端\n持续略低", font=ft(27), fill=ARCADE_TEXT, spacing=7)
    arcade_panel(draw, (792, 870, 1020, 1088), ARCADE_CYAN)
    draw.text((816, 902), "视角限制", font=ft(25), fill=ARCADE_CYAN)
    draw.multiline_text((816, 952), "\n".join(bench_bar_limit_lines(draw)), font=ft(23), fill=ARCADE_TEXT, spacing=8)
    arcade_panel(draw, (60, 1126, 1020, 1338), ARCADE_CYAN)
    draw.multiline_text((90, 1160), "读图：先看两端箭头方向 → 再看触胸水平线。\n双线左右错开只为分清方向，不代表杠铃横移。", font=ft(27), fill=ARCADE_TEXT, spacing=11)
    return image


def arcade_bench_plan(data):
    plan = bench_beginner_plan()
    supplied = data.get("plan") or {}
    if supplied.get("drills"):
        plan["tasks"] = [f"{item.get('name', '练习')}｜{item.get('dose') or item.get('cue', '')}" for item in supplied["drills"]][:4]
    if supplied.get("checks"):
        plan["checks"] = supplied["checks"][:4]
    image = arcade_canvas(); draw = ImageDraw.Draw(image)
    arcade_header(draw, 4, bench_card_headlines()[4], "纠正与验收", ARCADE_YELLOW)
    colors = [ARCADE_CYAN, ARCADE_BLUE, ARCADE_PURPLE, ARCADE_PINK]
    for index, item in enumerate(plan["tasks"]):
        y = 342 + index * 104
        arcade_panel(draw, (60, y, 1020, y + 82), colors[index], width=3)
        draw.text((84, y + 12), f"任务 {index + 1}", font=ft(19), fill=colors[index])
        draw.text((84, y + 43), item, font=ft(24), fill=ARCADE_TEXT)
    arcade_panel(draw, (60, 786, 1020, 1066), ARCADE_CYAN)
    draw.text((86, 812), "验收清单", font=ft(28), fill=ARCADE_CYAN)
    for index, item in enumerate(plan["checks"]):
        x = 88 + (index % 2) * 464; y = 874 + (index // 2) * 92
        draw.rectangle((x, y, x + 22, y + 22), outline=ARCADE_YELLOW, width=3)
        draw.multiline_text((x + 36, y - 4), wrap(draw, item, ft(21), 360), font=ft(21), fill=ARCADE_TEXT, spacing=5)
    arcade_panel(draw, (60, 1098, 1020, 1204), ARCADE_YELLOW)
    draw.text((86, 1120), "复拍要求", font=ft(22), fill=ARCADE_YELLOW)
    draw.text((86, 1156), plan["recapture"], font=ft(23), fill=ARCADE_TEXT)
    arcade_panel(draw, (60, 1234, 1020, 1342), ARCADE_PINK)
    draw.multiline_text((86, 1255), "肩、肘或手腕出现尖锐疼痛、麻木或力量骤降：\n停止加重并接受专业评估。", font=ft(22), fill=ARCADE_TEXT, spacing=6)
    return image


def arcade_summary(data, frames_dir, secondary_data=None, secondary_frames_dir=None):
    exercise = exercise_of(data); rep = data["repetitions"][-1]
    if exercise == "bench_press" and secondary_data is None and normalize_view(data.get("view")) == "foot_end":
        required = {"wrist_screen_left", "wrist_screen_right"}
        if all(required <= set(landmarks_of(item)) for item in (data["repetitions"][0], rep)):
            return arcade_bench_foot_end_summary(data, frames_dir)
    model = report_model(data)
    image = arcade_canvas(); draw = ImageDraw.Draw(image)
    arcade_header(draw, 1, f"主问题｜{model['primary']['title']}", "动作总评")
    if secondary_data is not None:
        left_frame = rep["bar_path"][-1]["frame"]
        secondary_rep = secondary_data["repetitions"][-1]
        right_frame = secondary_rep["bar_path"][-1]["frame"]
        left_tag = f"{view_label(data.get('view'))}｜{rep['bar_path'][-1]['time']:.2f}秒"
        right_tag = f"{view_label(secondary_data.get('view'))}｜{secondary_rep['bar_path'][-1]['time']:.2f}秒"
        arcade_photo(image, data, frames_dir, left_frame, (60, 352, 516, 900), ARCADE_PINK, left_tag)
        arcade_photo(image, secondary_data, secondary_frames_dir, right_frame, (564, 352, 1020, 900), ARCADE_CYAN, right_tag)
    else:
        start, key = rep["bar_path"][0], rep["bar_path"][-1]
        arcade_photo(image, data, frames_dir, start["frame"], (60, 352, 516, 900), ARCADE_PINK, f"起始｜{start['time']:.2f}秒")
        arcade_photo(image, data, frames_dir, key["frame"], (564, 352, 1020, 900), ARCADE_CYAN, f"关键阶段｜{key['time']:.2f}秒")
    arcade_panel(draw, (60, 936, 1020, 1215), ARCADE_YELLOW)
    draw.text((90, 968), f"看到了什么｜{model['primary']['title']}", font=ft(31), fill=ARCADE_YELLOW)
    context = view_context(exercise, data.get("view"), secondary_data.get("view") if secondary_data else None)
    observations = model["improve"][:2] + model["good"][:1]
    observation_text = " · ".join(item["title"] for item in observations)
    body = f"{model['primary']['detail']}\n其他观察：{observation_text}\n{context['limit']}"
    draw.multiline_text((90, 1014), wrap(draw, body, ft(25), 860), font=ft(25), fill=ARCADE_TEXT, spacing=8)
    arcade_panel(draw, (60, 1246, 1020, 1338), ARCADE_CYAN)
    draw.text((90, 1274), "下一页：看杠铃的实际屏幕轨迹", font=ft(29), fill=ARCADE_TEXT)
    return image


def arcade_bar(data, frames_dir):
    exercise = exercise_of(data); rep = data["repetitions"][-1]; stat = metrics(data, rep)
    if exercise == "bench_press" and normalize_view(data.get("view")) == "foot_end":
        required = {"wrist_screen_left", "wrist_screen_right"}
        if required <= set(landmarks_of(rep)):
            return arcade_bench_foot_end_bar(data, frames_dir)
    image = arcade_canvas(); draw = ImageDraw.Draw(image)
    arcade_header(draw, 2, "杠铃怎么移动？", "杠铃轨迹")
    crop, inner = arcade_photo(image, data, frames_dir, rep["bar_path"][-1]["frame"],
                               (60, 352, 760, 1088), ARCADE_CYAN, "绿色→蓝色＝运动方向")
    mapped = arcade_trace(draw, rep["bar_path"], crop, inner)
    if exercise == "deadlift" and mapped:
        dotted(draw, (mapped[0][0], inner[1]), (mapped[0][0], inner[3]), "#6D7890", 3)
    elif exercise == "squat":
        ref = map_point({"x": data["reference"]["midfoot_x"], "y": crop[1]}, crop, inner)[0]
        dotted(draw, (ref, inner[1]), (ref, inner[3]), "#6D7890", 3)
    elif exercise == "bench_press":
        phase_points = bench_reference_phases(rep)
        phase_mapped = [map_point(point, crop, inner) for point in phase_points]
        phase_mapped = [(min(max(x, inner[0]), inner[2]), min(max(y, inner[1]), inner[3])) for x, y in phase_mapped]
        for start, end in zip(phase_mapped, phase_mapped[1:]):
            dotted(draw, start, end, "#A9B5CD", 4)
        label_positions = layout_bench_phase_labels(phase_mapped, inner)
        for (x, y), (label_x, label_y), label in zip(phase_mapped, label_positions, ("起始", "触胸", "锁定")):
            draw.ellipse((x - 8, y - 8, x + 8, y + 8), fill=ARCADE_YELLOW)
            draw.text((label_x, label_y), label, font=ft(20), fill=ARCADE_YELLOW)
    arcade_panel(draw, (792, 352, 1020, 700), ARCADE_YELLOW)
    draw.text((816, 386), "动作判定", font=ft(27), fill=ARCADE_YELLOW)
    draw.multiline_text((816, 444), wrap(draw, stat["label"], ft(28), 180), font=ft(28), fill=ARCADE_TEXT, spacing=10)
    if exercise == "bench_press":
        draw.text((816, 560), f"触胸横移\n{stat['value']:+.1f}%", font=ft(23), fill=ARCADE_MUTED, spacing=8)
        draw.text((816, 636), f"锁定回位误差 {stat['return']:.1f}%", font=ft(18), fill=ARCADE_YELLOW)
    else:
        draw.text((816, 560), f"屏幕偏移\n{stat['value']:.1f}%", font=ft(24), fill=ARCADE_MUTED, spacing=8)
    arcade_panel(draw, (792, 736, 1020, 1088), ARCADE_PINK)
    draw.text((816, 770), "视角限制", font=ft(27), fill=ARCADE_PINK)
    note = ("卧推看起始→触胸→锁定的斜向/J形阶段，不以越垂直越好。脚端机位只能看左右同步。"
            if exercise == "bench_press" else
            "轨迹用于判断趋势。斜侧机位不能直接还原三维路径或真实中足距离。")
    draw.multiline_text((816, 828), wrap(draw, note, ft(25), 178), font=ft(25), fill=ARCADE_TEXT, spacing=10)
    arcade_panel(draw, (60, 1126, 1020, 1338), ARCADE_CYAN)
    draw.multiline_text((90, 1162), "读图顺序：先看方向箭头 → 再看偏移发生阶段 → 最后结合身体时序。",
                        font=ft(28), fill=ARCADE_TEXT, spacing=9)
    return image


def draw_landmark_traces(draw, data, rep, crop, box):
    arcade_trace(draw, rep["bar_path"], crop, box, ARCADE_CYAN, ARCADE_BLUE, 7)
    for name, points in landmarks_of(rep).items():
        color = arcade_landmark_color(name)
        if color:
            mapped = []
            for point in points:
                x, y = map_point(point, crop, box)
                mapped.append((min(max(x, box[0]), box[2]), min(max(y, box[1]), box[3])))
            if len(mapped) > 1:
                draw.line(mapped, fill=color, width=6, joint="curve")


def draw_landmark_snapshot(draw, data, rep, crop, box, frame):
    """Use direct body-point labels for novice evidence cards, not long trails."""
    exercise = exercise_of(data)
    names = {
        "deadlift": ("shoulder", "hip"),
        "squat": ("shoulder", "hip", "knee", "ankle"),
        "bench_press": ("wrist", "elbow", "shoulder"),
    }[exercise]
    points = landmarks_of(rep)
    label_map = {"shoulder": "肩", "hip": "髋", "knee": "膝", "ankle": "踝", "wrist": "腕", "elbow": "肘"}
    for name in names:
        candidates = points.get(name) or []
        if not candidates:
            continue
        item = min(candidates, key=lambda point: abs(int(point["frame"]) - int(frame)))
        x, y = map_point(item, crop, box)
        x, y = min(max(x, box[0] + 12), box[2] - 12), min(max(y, box[1] + 12), box[3] - 12)
        color = arcade_landmark_color(name) or ARCADE_CYAN
        draw.ellipse((x - 8, y - 8, x + 8, y + 8), fill=ARCADE_BG, outline=color, width=4)
        label_x = x + 12 if x < (box[0] + box[2]) / 2 else x - 34
        label_y = max(box[1] + 8, y - 26)
        draw.text((label_x, label_y), label_map[name], font=ft(18), fill=color, stroke_width=2, stroke_fill=ARCADE_BG)


def bench_foot_end_evidence(data, rep):
    """Return screen-left/right wrist and elbow evidence for two bench phases."""
    configured = ((data.get("render") or {}).get("bench_sync_frames") or {})
    touch_frame = int(configured.get("touch") or next(point["frame"] for point in rep["bar_path"] if point.get("phase") == "touch"))
    press_candidates = [point for point in rep["bar_path"] if point.get("phase") == "press" and point["frame"] >= touch_frame + 8]
    press_frame = int(configured.get("press") or (press_candidates[0]["frame"] if press_candidates else next(point["frame"] for point in rep["bar_path"] if point.get("phase") == "press")))
    landmarks = landmarks_of(rep)

    def at(name, frame):
        return next(point for point in landmarks[name] if int(point["frame"]) == frame)

    def phase(frame):
        return {
            "frame": frame,
            "screen_left": {"wrist": at("wrist_screen_left", frame), "elbow": at("elbow_screen_left", frame)},
            "screen_right": {"wrist": at("wrist_screen_right", frame), "elbow": at("elbow_screen_right", frame)},
        }

    return {"touch": phase(touch_frame), "press": phase(press_frame)}


def arcade_bench_foot_end_sync(data, rep, frames_dir):
    evidence = bench_foot_end_evidence(data, rep)
    image = arcade_canvas(); draw = ImageDraw.Draw(image)
    arcade_header(draw, 3, bench_card_headlines()[3], "左右同步", ARCADE_PINK)
    draw.text((72, 322), f"以第{rep.get('rep', 4)}次完整重复为例", font=ft(22), fill=ARCADE_MUTED)
    left_box, right_box = (60, 360, 516, 738), (564, 360, 1020, 738)
    crop1, inner1 = arcade_photo(image, data, frames_dir, evidence["touch"]["frame"], left_box, ARCADE_PINK, "① 触胸瞬间")
    crop2, inner2 = arcade_photo(image, data, frames_dir, evidence["press"]["frame"], right_box, ARCADE_CYAN, "② 推起初段")
    draw = ImageDraw.Draw(image)

    def mapped_phase(phase, crop, box):
        return {
            side: {joint: map_point(point, crop, box) for joint, point in joints.items()}
            for side, joints in (("screen_left", phase["screen_left"]), ("screen_right", phase["screen_right"]))
        }

    touch_left = mapped_phase(evidence["touch"], crop1, inner1)
    touch_right = mapped_phase(evidence["touch"], crop2, inner2)
    press = mapped_phase(evidence["press"], crop2, inner2)

    def draw_bar(points, box):
        left, right = points["screen_left"]["wrist"], points["screen_right"]["wrist"]
        dx = right[0] - left[0]
        slope = (right[1] - left[1]) / dx if abs(dx) > 1 else 0
        start_x, end_x = box[0] + 12, box[2] - 12
        start_y = left[1] + slope * (start_x - left[0])
        end_y = left[1] + slope * (end_x - left[0])
        draw.line((start_x, start_y, end_x, end_y), fill=ARCADE_CYAN, width=7)

    def draw_joints(points, with_labels=False):
        for side in ("screen_left", "screen_right"):
            for joint, color in (("wrist", ARCADE_PINK), ("elbow", ARCADE_PURPLE)):
                x, y = points[side][joint]
                draw.ellipse((x - 8, y - 8, x + 8, y + 8), fill=ARCADE_BG, outline=color, width=4)
                if with_labels:
                    label = "腕" if joint == "wrist" else "肘"
                    label_x = x - 34 if side == "screen_left" else x + 12
                    draw.text((label_x, y - 15), label, font=ft(18), fill=color, stroke_width=2, stroke_fill=ARCADE_BG)

    reference_y = touch_left["screen_right"]["wrist"][1]
    dotted(draw, (inner1[0] + 12, reference_y), (inner1[2] - 12, reference_y), "#A9B5CD", 3)
    draw_bar(touch_left, inner1); draw_joints(touch_left, True)
    left_wrist = touch_left["screen_left"]["wrist"]
    draw.text((inner1[0] + 14, inner1[1] + 14), "画面左端略低 ↓", font=ft(21), fill=ARCADE_PINK, stroke_width=2, stroke_fill=ARCADE_BG)
    draw.line((inner1[0] + 115, inner1[1] + 44, left_wrist[0], left_wrist[1] - 12), fill=ARCADE_PINK, width=3)

    draw_bar(press, inner2); draw_joints(press, False)
    for side in ("screen_left", "screen_right"):
        start = touch_right[side]["wrist"]
        end = press[side]["wrist"]
        draw.ellipse((start[0] - 7, start[1] - 7, start[0] + 7, start[1] + 7), outline=ARCADE_YELLOW, width=3)
        draw.line((*start, *end), fill=ARCADE_YELLOW, width=4)
        angle = math.atan2(end[1] - start[1], end[0] - start[0])
        size = 14
        left = (end[0] - size * math.cos(angle - .55), end[1] - size * math.sin(angle - .55))
        right = (end[0] - size * math.cos(angle + .55), end[1] - size * math.sin(angle + .55))
        draw.polygon((end, left, right), fill=ARCADE_YELLOW)
    draw.text((inner2[0] + 76, inner2[1] + 14), "两端都已离胸 ↑", font=ft(21), fill=ARCADE_YELLOW, stroke_width=2, stroke_fill=ARCADE_BG)

    rows = [
        (ARCADE_PINK, "1  触胸时：画面左端略低。"),
        (ARCADE_CYAN, "2  推起初段：两端都已离胸。"),
        (ARCADE_YELLOW, "3  有轻微高度差，但不能直接归因于单侧胸肌弱。"),
    ]
    for index, (color, message) in enumerate(rows):
        y = 778 + index * 96
        arcade_panel(draw, (60, y, 1020, y + 72), color, width=3)
        draw.text((88, y + 17), message, font=ft(25), fill=ARCADE_TEXT)
    arcade_panel(draw, (60, 1080, 1020, 1240), ARCADE_CYAN)
    draw.text((88, 1108), "下一次先检查", font=ft(27), fill=ARCADE_CYAN)
    draw.multiline_text((88, 1154), "握距对称 · 杠铃居中 · 两侧肩胛压力 · 腿驱时序", font=ft(25), fill=ARCADE_TEXT, spacing=8)
    draw.text((72, 1276), "脚端二维画面只用于左右同步复盘，不能判断侧面J形杠路。", font=ft(22), fill=ARCADE_MUTED)
    return image


def arcade_timing(data, frames_dir, secondary_data=None, secondary_frames_dir=None):
    exercise = exercise_of(data); rep = data["repetitions"][-1]
    if exercise == "bench_press":
        required = {"wrist_screen_left", "wrist_screen_right", "elbow_screen_left", "elbow_screen_right"}
        if normalize_view(data.get("view")) == "foot_end" and required <= set(landmarks_of(rep)):
            return arcade_bench_foot_end_sync(data, rep, frames_dir)
        if secondary_data is not None and normalize_view(secondary_data.get("view")) == "foot_end":
            secondary_rep = secondary_data["repetitions"][-1]
            if required <= set(landmarks_of(secondary_rep)):
                return arcade_bench_foot_end_sync(secondary_data, secondary_rep, secondary_frames_dir)
    source_data = secondary_data or data
    model = report_model(source_data)
    title = f"第二机位｜{model['primary']['title']}" if secondary_data is not None else f"身体协同｜{model['primary']['title']}"
    image = arcade_canvas(); draw = ImageDraw.Draw(image)
    arcade_header(draw, 3, title, "身体时序", ARCADE_PINK)
    key_frame, start_frame = rep["bar_path"][-1]["frame"], rep["bar_path"][0]["frame"]
    key_time = next(point["time"] for point in rep["bar_path"] if point["frame"] == key_frame)
    crop1, box1 = arcade_photo(image, data, frames_dir, key_frame,
                               (60, 352, 516, 900), ARCADE_PINK, f"{view_label(data.get('view'))}｜{key_time:.2f}秒")
    draw_landmark_snapshot(draw, data, rep, crop1, box1, key_frame)
    if secondary_data is not None:
        secondary_rep = secondary_data["repetitions"][-1]
        secondary_frame = secondary_rep["bar_path"][-1]["frame"]
        crop2, box2 = arcade_photo(image, secondary_data, secondary_frames_dir,
                                   secondary_frame,
                                   (564, 352, 1020, 900), ARCADE_CYAN, f"{view_label(secondary_data.get('view'))}｜{secondary_rep['bar_path'][-1]['time']:.2f}秒")
        draw_landmark_snapshot(draw, secondary_data, secondary_rep, crop2, box2, secondary_frame)
    else:
        crop2, box2 = arcade_photo(image, data, frames_dir, start_frame,
                                   (564, 352, 1020, 900), ARCADE_CYAN, f"起始对照｜{rep['bar_path'][0]['time']:.2f}秒")
        draw_landmark_snapshot(draw, data, rep, crop2, box2, start_frame)
    context = view_context(exercise, data.get("view"), secondary_data.get("view") if secondary_data else None)
    improve = model["improve"][0] if model["improve"] else finding("待改善", "结合关键帧复核")
    limit_item = model["unavailable"][0] if model["unavailable"] else finding("不代表什么", "二维画面不能单独诊断肌力、疼痛原因或三维关节受力。")
    messages = [
        f"发生了什么：{model['primary']['detail']}",
        f"代表什么：{improve['title']}｜{improve['detail']}",
        f"不代表什么：{limit_item['detail']}",
    ]
    for index, message in enumerate(messages):
        y = 942 + index * 104
        color = [ARCADE_CYAN, ARCADE_PINK, ARCADE_YELLOW][index]
        arcade_panel(draw, (60, y, 1020, y + 78), color, width=3)
        draw.multiline_text((88, y + 13), wrap(draw, f"{index + 1}  {message}", ft(24), 890), font=ft(24), fill=ARCADE_TEXT, spacing=5)
    draw.text((72, 1275), wrap(draw, context["limit"], ft(23), 910), font=ft(23), fill=ARCADE_MUTED)
    return image


def arcade_plan(data):
    """Fixed card 4: one cue, one main drill, one assistance drill, then checks."""
    model = report_model(data)
    plan, checks = model["plan"], model["checks"]
    image = arcade_canvas(); draw = ImageDraw.Draw(image)
    arcade_header(draw, 4, "下一次训练怎么验证？", "纠正与验收", ARCADE_YELLOW)
    tasks = [
        ("动作口令", plan["cue"]),
        ("主练", f"{plan['main_drill']['name']}｜{plan['main_drill']['dose']}"),
        ("辅助练", f"{plan['assist_drill']['name']}｜{plan['assist_drill']['dose']}"),
    ]
    for index, (label, item) in enumerate(tasks):
        y = 352 + index * 146; color = [ARCADE_CYAN, ARCADE_BLUE, ARCADE_PURPLE][index]
        arcade_panel(draw, (60, y, 1020, y + 116), color)
        draw.text((88, y + 19), label, font=ft(22), fill=color)
        draw.text((88, y + 57), item, font=ft(28), fill=ARCADE_TEXT)
    arcade_panel(draw, (60, 814, 1020, 1168), ARCADE_CYAN)
    draw.text((88, 846), "验收清单", font=ft(31), fill=ARCADE_CYAN)
    for index, item in enumerate(checks):
        x = 92 + (index % 2) * 454; y = 914 + (index // 2) * 106
        draw.rectangle((x, y, x + 24, y + 24), outline=ARCADE_YELLOW, width=3)
        draw.text((x + 42, y - 5), wrap(draw, item, ft(23), 360), font=ft(23), fill=ARCADE_TEXT)
    if model["show_recapture"]:
        unavailable = model["unavailable"][0]
        arcade_panel(draw, (60, 1204, 1020, 1262), ARCADE_YELLOW)
        draw.text((88, 1219), f"复拍补充：{unavailable['title']}｜{unavailable['detail']}", font=ft(21), fill=ARCADE_TEXT)
        safety_box = (60, 1280, 1020, 1362)
    else:
        safety_box = (60, 1204, 1020, 1338)
    arcade_panel(draw, safety_box, ARCADE_PINK)
    draw.multiline_text((88, safety_box[1] + 25), "尖锐疼痛、麻木、放射痛或力量骤降：\n停止重负荷并接受专业评估。",
                        font=ft(24), fill=ARCADE_TEXT, spacing=8)
    return image


def main():
    parser = argparse.ArgumentParser(description="Render Chinese powerlifting trajectory cards with optional dual views.")
    parser.add_argument("--tracking", required=True, type=Path)
    parser.add_argument("--frames-dir", required=True, type=Path)
    parser.add_argument("--secondary-tracking", type=Path)
    parser.add_argument("--secondary-frames-dir", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    if bool(args.secondary_tracking) != bool(args.secondary_frames_dir):
        parser.error("--secondary-tracking and --secondary-frames-dir must be provided together")
    data = json.loads(args.tracking.read_text(encoding="utf-8"))
    if not data.get("repetitions"):
        parser.error("primary tracking requires at least one valid repetition")
    secondary_data = None
    if args.secondary_tracking:
        secondary_data = json.loads(args.secondary_tracking.read_text(encoding="utf-8"))
        if not secondary_data.get("repetitions"):
            parser.error("secondary tracking requires at least one valid repetition")
        if exercise_of(secondary_data) != exercise_of(data):
            parser.error("primary and secondary tracking must describe the same exercise")
    output = args.output_dir; output.mkdir(parents=True, exist_ok=True)
    exercise = exercise_of(data)
    timing_name = {
        "deadlift": "03-stage-hip-timing.png",
        "squat": "03-stage-body-sync.png",
        "bench_press": "03-stage-upper-body-sync.png",
    }[exercise]
    cards = [
        ("01-stage-summary.png", arcade_summary(data, args.frames_dir, secondary_data, args.secondary_frames_dir)),
        ("02-stage-bar-path.png", arcade_bar(data, args.frames_dir)),
        (timing_name, arcade_timing(data, args.frames_dir, secondary_data, args.secondary_frames_dir)),
        ("04-final-training.png", arcade_plan(data)),
    ]
    for name, image in cards:
        image.convert("RGB").save(output / name, "PNG", optimize=True)
        print(output / name)
    preview = Image.new("RGB", (360, 1920), ARCADE_BG)
    for index, (_, card) in enumerate(cards):
        preview.paste(card.convert("RGB").resize((360, 480), Image.Resampling.LANCZOS), (0, index * 480))
    preview.save(output / "mobile-preview.jpg", "JPEG", quality=90, optimize=True)
    context = view_context(exercise, data.get("view"), secondary_data.get("view") if secondary_data else None)
    mode = "single-view" if secondary_data is None else "dual-view-standard" if context["standard"] else "dual-view-nonstandard"
    print(f"mode={mode} {context['limit']}")


if __name__ == "__main__":
    main()
