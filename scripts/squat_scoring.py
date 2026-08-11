#!/usr/bin/env python3
"""Ordinary-filming-friendly 2D quality score for side + rear squats."""
from __future__ import annotations

import math
from pathlib import Path
import argparse
import json

from squat_phase_detection import detect_squat_phases


WEIGHTS = {"SQ-01": 20, "SQ-02": 15, "SQ-03": 20, "SQ-04": 20, "SQ-05": 15, "SQ-06": 10}
CORE_RULES = {"SQ-01", "SQ-03", "SQ-04"}
LIMITATION = "仅基于当前侧面与后方代表重复的二维视频趋势，不代表比赛裁判或医疗判断。"


def _item(rule_id, title, status, score, detail, frames=(), metrics=None, source="直接证据", neutral_reason=None):
    return {"id": rule_id, "title": title, "max_score": WEIGHTS[rule_id], "score": int(score), "status": status,
            "detail": detail, "evidence_frames": list(frames), "metrics": metrics or {}, "limitation": LIMITATION,
            "source": source, "neutral_reason": neutral_reason}


def _neutral(rule_id, title, reason, frames=()):
    return _item(rule_id, title, "中性基准", round(WEIGHTS[rule_id] * .80),
                 "当前视频未能可靠看清这一项，按中性基准计入，不作为动作问题。",
                 frames, {"中性基准比例": 80}, "中性基准", reason)


def _band(rule_id, title, value, stable, mild, stable_detail, mild_detail, clear_detail, frames, metric):
    if value <= stable:
        return _item(rule_id, title, "稳定", WEIGHTS[rule_id], stable_detail, frames, {metric: round(value, 3)})
    if value <= mild:
        return _item(rule_id, title, "轻微待改善", round(WEIGHTS[rule_id] * .70), mild_detail, frames, {metric: round(value, 3)})
    return _item(rule_id, title, "明显待改善", round(WEIGHTS[rule_id] * .30), clear_detail, frames, {metric: round(value, 3)})


def _joint(sample, name):
    value = ((sample or {}).get("joints") or {}).get(name) or {}
    if not value.get("available") or float(value.get("confidence") or 0) < .60:
        return None
    if not all(isinstance(value.get(axis), (int, float)) for axis in ("x", "y")):
        return None
    return float(value["x"]), float(value["y"])


def _nearest_pose(pose, frame, max_gap=8):
    candidates = [entry for entry in ((pose or {}).get("frames") or []) if isinstance(entry.get("frame"), int)]
    result = min(candidates, key=lambda item: abs(item["frame"] - frame)) if candidates else None
    return result if result and abs(result["frame"] - frame) <= max_gap else None


def _side_chain(pose, frame):
    sample = _nearest_pose(pose, frame)
    for side in ("left", "right"):
        joints = [_joint(sample, f"{side}_{name}") for name in ("shoulder", "hip", "knee", "ankle")]
        if all(joints):
            return joints
    return None


def _angle(a, b, c):
    ba, bc = (a[0] - b[0], a[1] - b[1]), (c[0] - b[0], c[1] - b[1])
    denominator = math.hypot(*ba) * math.hypot(*bc)
    if not denominator:
        return None
    return math.degrees(math.acos(max(-1, min(1, (ba[0] * bc[0] + ba[1] * bc[1]) / denominator))))


def _torso(chain):
    shoulder, hip = chain[:2]
    return math.degrees(math.atan2(shoulder[1] - hip[1], shoulder[0] - hip[0]))


def _phase_samples(side, side_pose):
    raw = ((side.get("bar_tracking") or {}).get("raw_points") or [])
    samples = []
    for bar in raw:
        chain = _side_chain(side_pose, int(bar["frame"]))
        if not chain:
            continue
        shoulder, hip, knee, ankle = chain
        angle = _angle(hip, knee, ankle)
        distance = math.dist(hip, knee)
        if angle is None or distance <= 0:
            continue
        samples.append({"frame": int(bar["frame"]), "time": float(bar["time"]), "hip_y": hip[1],
                        "knee_angle": angle, "bar_y": float(bar["y"]), "hip_knee_distance": distance,
                        "ankle_x": ankle[0]})
    return samples


def _phase_frames(result):
    return (result.get("representative_frames") or {}) if result.get("available") else {}


def _grade(total, items):
    statuses = {item["status"] for item in items}
    clear_core = any(item["id"] in CORE_RULES and item["status"] == "明显待改善" for item in items)
    if total >= 95 and statuses == {"稳定"}:
        grade = "SS"
    elif total >= 90:
        grade = "S"
    elif total >= 80:
        grade = "A"
    elif total >= 70:
        grade = "B"
    elif total >= 60:
        grade = "C"
    else:
        grade = "D"
    return "A" if clear_core and grade in {"SS", "S"} else grade


def _unavailable(reason):
    return {"schema_version": "squat-score-v1", "scorable": False, "total": None, "grade": None,
            "items": [], "unavailable_reason": reason, "limitation": LIMITATION}


def _rear_item(rear):
    evidence = ((rear.get("render") or {}).get("rear_bar_level_evidence") or {})
    if not all(stage in evidence for stage in ("reference", "ascent")):
        return None
    def angle(stage):
        left, right = stage["screen_left"], stage["screen_right"]
        return math.degrees(math.atan2(float(right["y"]) - float(left["y"]), float(right["x"]) - float(left["x"])))
    reference, ascent = evidence["reference"], evidence["ascent"]
    value = max(abs(angle(reference)), abs(angle(ascent)), abs(angle(ascent) - angle(reference)))
    return _band("SQ-05", "左右稳定", value, 2, 4,
                 "后方两端高度接近，推起同步。", "后方出现轻微高度或同步差。", "后方出现持续明显的一高一低或不同步趋势。",
                 (reference["frame"], ascent["frame"]), "后方双端最大倾斜_度")


def score_squat(side, rear, side_pose, rear_pose=None):
    """Score ordinary barbell squats; unknown joints use a neutral baseline."""
    if not side or not rear or side.get("exercise") != "squat" or rear.get("exercise") != "squat":
        return _unavailable("需要同一次训练中的侧面与后方深蹲视频。")
    if side.get("view") not in {"side", "oblique_side"} or rear.get("view") != "rear":
        return _unavailable("需要侧面／斜侧面与后方双机位。")
    variation = ((side.get("render") or {}).get("squat_variation"))
    if variation in {"pause", "box", "tempo"}:
        return _unavailable("当前仅评分常规深蹲；暂停、箱式或节奏变式暂不评分。")
    raw = ((side.get("bar_tracking") or {}).get("raw_points") or [])
    if (side.get("bar_tracking") or {}).get("status") != "available" or len(raw) < 5:
        return _unavailable("侧面杠铃连续轨迹不可靠，无法完成评分。")
    rear_item = _rear_item(rear)
    if rear_item is None:
        return _unavailable("后方左右杠铃端点证据不足，无法完成评分。")
    plate = float(side.get("plate_diameter_px") or 0)
    midfoot = ((side.get("reference") or {}).get("midfoot_x"))
    if plate <= 0 or not isinstance(midfoot, (int, float)):
        return _unavailable("缺少可信杠片直径或中足参考，无法完成评分。")

    max_midfoot = max(abs(float(point["x"]) - float(midfoot)) for point in raw) / plate * 100
    bar_item = _band("SQ-01", "杠铃趋势", max_midfoot, 8, 15,
                     "侧面杠铃整体趋势保持在当前中足参考附近。", "出现轻微二维屏幕前后偏移。", "出现持续明显二维屏幕前后偏移。",
                     (raw[0]["frame"], raw[-1]["frame"]), "相对中足最大偏移_杠片直径百分比")

    phase_result = detect_squat_phases(_phase_samples(side, side_pose))
    frames = _phase_frames(phase_result)
    if phase_result.get("available") and phase_result.get("pause_bottom"):
        return _unavailable("检测到明显底部暂停；当前常规深蹲评分模型不适用。")
    if not phase_result.get("available"):
        depth_item = _neutral("SQ-02", "深度与底部控制", phase_result.get("reason") or "侧面髋膝关键点不足。")
        trunk_item = _neutral("SQ-03", "躯干稳定", "侧面肩髋关键点不足，无法识别完整阶段。")
        coordination_item = _neutral("SQ-04", "髋膝协同", "侧面髋膝关键点不足，无法识别底部与起身阶段。")
        flow_item = _neutral("SQ-06", "动作流畅度", "无法可靠识别完整深蹲阶段与锁定。")
    else:
        bottom_frame, ascent_frame, lockout_frame = frames.get("bottom"), frames.get("ascent"), frames.get("lockout")
        if lockout_frame is None:
            depth_item = _item("SQ-02", "深度与底部控制", "轻微待改善", 10,
                               "已到达最低点，但当前视频未见稳定锁定完成。", (bottom_frame,), {"阶段完整": False})
            flow_item = _item("SQ-06", "动作流畅度", "明显待改善", 3,
                              "本次重复未见稳定锁定完成。", (bottom_frame,), {"锁定完成": False})
        else:
            depth_item = _item("SQ-02", "深度与底部控制", "稳定", 15,
                               "侧面已识别明确最低点与受控反向。", (bottom_frame, ascent_frame), {"阶段完整": True})
            y_values = [float(point["y"]) for point in raw]
            bottom_i = max(range(len(y_values)), key=y_values.__getitem__)
            reversals = sum(1 for index in range(1, bottom_i) if y_values[index] < y_values[index - 1] - plate * .01)
            reversals += sum(1 for index in range(bottom_i + 1, len(y_values)) if y_values[index] > y_values[index - 1] + plate * .01)
            flow_item = _band("SQ-06", "动作流畅度", reversals, 0, 1,
                              "阶段衔接连续，锁定完成。", "动作中出现一次轻微非计划性调整。", "动作中出现反复调整或未完成锁定。",
                              (raw[0]["frame"], raw[-1]["frame"]), "非计划性杠铃反向次数")
        setup_chain = _side_chain(side_pose, frames.get("setup") or raw[0]["frame"])
        bottom_chain = _side_chain(side_pose, bottom_frame)
        ascent_chain = _side_chain(side_pose, ascent_frame)
        if setup_chain and bottom_chain and ascent_chain:
            # Squat involves intentional torso inclination.  Score only an
            # abrupt bottom-to-early-ascent adjustment, not the whole descent.
            torso_change = abs(_torso(ascent_chain) - _torso(bottom_chain))
            trunk_item = _band("SQ-03", "躯干稳定", torso_change, 10, 20,
                               "底部到起身初段躯干角变化连续可控。", "起身初段出现轻微躯干角调整。", "起身初段出现明显躯干角突变。",
                               (bottom_frame, ascent_frame), "底部至起身初段躯干角变化_度")
            hip_rise = bottom_chain[1][1] - ascent_chain[1][1]
            knee_extension = _angle(bottom_chain[1], bottom_chain[2], bottom_chain[3])
            knee_ascent = _angle(ascent_chain[1], ascent_chain[2], ascent_chain[3])
            scale = max(math.dist(bottom_chain[1], bottom_chain[2]), 1)
            # A large hip rise while the knee scarcely opens is the conservative
            # 2D signature of a persistent early hip "rush".
            imbalance = max(0.0, hip_rise / scale - max(0.0, (knee_ascent - knee_extension) / 90.0))
            coordination_item = _band("SQ-04", "髋膝协同", imbalance, .12, .28,
                                      "底部到起身初段髋膝协同上升。", "起身初段出现轻微髋膝节奏差。", "起身初段髋部持续先行，髋膝协同不足。",
                                      (bottom_frame, ascent_frame), "起身初段髋膝协同差")
        else:
            trunk_item = _neutral("SQ-03", "躯干稳定", "底部或起身初段肩髋关键点不足。", (bottom_frame, ascent_frame))
            coordination_item = _neutral("SQ-04", "髋膝协同", "底部或起身初段髋膝关键点不足。", (bottom_frame, ascent_frame))

    items = [bar_item, depth_item, trunk_item, coordination_item, rear_item, flow_item]
    total = sum(item["score"] for item in items)
    return {"schema_version": "squat-score-v1", "scorable": True, "total": int(total), "grade": _grade(total, items),
            "items": items, "unavailable_reason": None, "limitation": LIMITATION,
            "phase_detection": phase_result}


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description="Practical side + rear squat AI score")
    parser.add_argument("--side", type=Path, required=True); parser.add_argument("--rear", type=Path, required=True)
    parser.add_argument("--side-pose", type=Path, required=True); parser.add_argument("--rear-pose", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    side, rear, side_pose = _load(args.side), _load(args.rear), _load(args.side_pose)
    rear_pose = _load(args.rear_pose) if args.rear_pose else None
    for tracking, pose, label in ((side, side_pose, "侧面"), (rear, rear_pose, "后方")):
        if pose is None:
            continue
        if (tracking.get("source_video") or {}).get("sha256") != (pose.get("source_video") or {}).get("sha256"):
            parser.error(f"{label}姿态数据与动作视频不匹配，拒绝评分")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(score_squat(side, rear, side_pose, rear_pose), ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
