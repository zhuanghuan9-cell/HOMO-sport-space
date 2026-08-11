#!/usr/bin/env python3
"""Practical deadlift quality scoring for ordinary side + front/rear videos.

Hard evidence is always preferred.  When a single pose item is obscured, only
that rule receives an explicit 80%-weight neutral baseline; the report never
pretends that an invisible joint was directly observed.
"""
from __future__ import annotations

import math
import argparse
import json
from pathlib import Path


WEIGHTS = {
    "DL-01": 20,  # bar path
    "DL-02": 20,  # trunk stability
    "DL-03": 20,  # hip-knee relationship
    "DL-04": 15,  # bilateral symmetry
    "DL-05": 15,  # lockout
    "DL-06": 10,  # smoothness
}
CORE_RULES = {"DL-01", "DL-02", "DL-03"}


LIMITATION = "仅基于当前双机位的二维视频趋势，不代表比赛裁判或医疗判断。"


def _item(rule_id, title, status, score, detail, frames=(), metrics=None, source="直接证据", neutral_reason=None):
    return {
        "id": rule_id, "title": title, "max_score": WEIGHTS[rule_id],
        "score": score, "status": status, "detail": detail,
        "evidence_frames": list(frames), "metrics": metrics or {},
        "limitation": LIMITATION, "source": source, "neutral_reason": neutral_reason,
    }


def _nearest_pose_frame(pose, frame, max_gap=6):
    frames = (pose or {}).get("frames") or []
    candidates = [sample for sample in frames if isinstance(sample.get("frame"), int)]
    nearest = min(candidates, key=lambda sample: abs(sample["frame"] - frame)) if candidates else None
    if nearest is None or abs(nearest["frame"] - frame) > max_gap:
        return None
    return nearest


def _joint(sample, name):
    value = ((sample or {}).get("joints") or {}).get(name) or {}
    if not value.get("available") or float(value.get("confidence") or 0) < 0.60:
        return None
    if not all(isinstance(value.get(axis), (int, float)) for axis in ("x", "y")):
        return None
    return float(value["x"]), float(value["y"])


def _side_points(pose, frame, names):
    sample = _nearest_pose_frame(pose, frame)
    for side in ("left", "right"):
        points = [_joint(sample, f"{side}_{name}") for name in names]
        if all(points):
            return points
    return None


def _neutral_item(rule_id, title, reason, frames=()):
    return _item(
        rule_id, title, "中性基准", round(WEIGHTS[rule_id] * .80),
        "当前视频未能可靠看清这一项，按中性基准计入，不作为动作问题。",
        frames, {"中性基准比例": 80}, "中性基准", reason,
    )


def _angle(a, b, c):
    ba, bc = (a[0] - b[0], a[1] - b[1]), (c[0] - b[0], c[1] - b[1])
    denominator = math.hypot(*ba) * math.hypot(*bc)
    if denominator == 0:
        return None
    cosine = max(-1.0, min(1.0, (ba[0] * bc[0] + ba[1] * bc[1]) / denominator))
    return math.degrees(math.acos(cosine))


def _torso_angle(chain):
    shoulder, hip = chain[0], chain[1]
    return math.degrees(math.atan2(shoulder[1] - hip[1], shoulder[0] - hip[0]))


def _status_for_three_band(value, stable, mild, weight, title, stable_detail, mild_detail, clear_detail, frames, metric_name=None):
    metrics = {metric_name: round(value, 3)} if metric_name else {}
    if value <= stable:
        return _item(title[0], title[1], "稳定", weight, stable_detail, frames, metrics)
    if value <= mild:
        return _item(title[0], title[1], "轻微待改善", round(weight * .70), mild_detail, frames, metrics)
    return _item(title[0], title[1], "明显待改善", round(weight * .30), clear_detail, frames, metrics)


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
    return {
        "schema_version": "deadlift-score-v1", "scorable": False,
        "total": None, "grade": None, "items": [], "unavailable_reason": reason,
        "limitation": LIMITATION,
    }


def score_deadlift(side, rear, side_pose, rear_pose):
    """Score one conventional, reset deadlift only when every evidence gate passes."""
    if not side or not rear or side.get("exercise") != "deadlift" or rear.get("exercise") != "deadlift":
        return _unavailable("需要同一组传统硬拉的侧面与后方视频。")
    if side.get("view") not in {"side", "oblique_side"} or rear.get("view") not in {"front", "rear"}:
        return _unavailable("需要侧面／斜侧面与前方或后方双机位。")
    variation = ((side.get("render") or {}).get("deadlift_variation"))
    if variation and variation != "conventional":
        return _unavailable("当前仅评分常规单次硬拉；暂停或其他变式暂不评分。")
    execution = ((side.get("render") or {}).get("deadlift_execution"))
    if execution and execution != "reset_single":
        return _unavailable("当前仅评分每次落地重置的常规单次硬拉。")
    bar_tracking = side.get("bar_tracking") or {}
    raw = bar_tracking.get("raw_points") or []
    if bar_tracking.get("status") != "available" or len(raw) < 3:
        return _unavailable("侧面杠铃轨迹不可靠，无法完成评分。")
    rear_evidence = ((rear.get("render") or {}).get("rear_bar_level_evidence") or {})
    if not all(stage in rear_evidence for stage in ("reference", "ascent")):
        return _unavailable("后方左右杠铃端点证据不足，无法完成评分。")
    first, last = raw[0], raw[-1]
    early_frame = int(raw[min(1, len(raw) - 1)]["frame"])
    initial_trunk = _side_points(side_pose, int(first["frame"]), ("shoulder", "hip"))
    early_trunk = _side_points(side_pose, early_frame, ("shoulder", "hip"))
    initial_hip_knee = _side_points(side_pose, int(first["frame"]), ("hip", "knee"))
    early_hip = _side_points(side_pose, early_frame, ("hip",))
    lockout_chain = _side_points(side_pose, int(last["frame"]), ("shoulder", "hip", "knee", "ankle"))

    plate = float(side.get("plate_diameter_px") or 0)
    if plate <= 0:
        return _unavailable("缺少可信杠片直径，无法完成评分。")
    max_lateral = max(abs(float(point["x"]) - float(first["x"])) for point in raw) / plate * 100
    bar_item = _status_for_three_band(
        max_lateral, 5, 10, WEIGHTS["DL-01"], ("DL-01", "杠铃轨迹"),
        "离地到锁定的二维杠铃路径稳定。", "出现轻微二维横向漂移。", "出现明显二维横向漂移。",
        (first["frame"], last["frame"]), "最大横向漂移_杠片直径百分比",
    )

    if initial_trunk and early_trunk:
        trunk_change = abs(_torso_angle(early_trunk) - _torso_angle(initial_trunk))
        spine_item = _status_for_three_band(
            trunk_change, 8, 15, WEIGHTS["DL-02"], ("DL-02", "脊柱稳定"),
            "离地初段躯干角保持稳定。", "离地初段出现轻微躯干角调整。", "离地初段躯干角变化较大。",
            (first["frame"], early_frame), "离地初段躯干角变化_度",
        )
    else:
        spine_item = _neutral_item("DL-02", "脊柱稳定", "离地初段肩髋关键点受遮挡或置信度不足。", (first["frame"], early_frame))

    # Image y grows downward.  Hip must appear above the knee, and it must
    # not rise before a meaningful amount of bar movement has occurred.
    if initial_hip_knee and early_hip:
        hip_above_knee = initial_hip_knee[0][1] < initial_hip_knee[1][1]
        hip_rise = initial_hip_knee[0][1] - early_hip[0][1]
        bar_rise = float(first["y"]) - float(raw[min(1, len(raw) - 1)]["y"])
        early_ratio = max(0, hip_rise - bar_rise) / plate * 100
        if hip_above_knee and early_ratio <= 1:
            hip_item = _item("DL-03", "髋膝关系", "稳定", 20, "准备位与离地初段的肩髋配合稳定。", (first["frame"], raw[1]["frame"]), {"髋部提前上移_杠片直径百分比": round(early_ratio, 3)})
        elif hip_above_knee and early_ratio <= 2:
            hip_item = _item("DL-03", "髋膝关系", "轻微待改善", 14, "离地前出现轻微重新找位。", (first["frame"], raw[1]["frame"]), {"髋部提前上移_杠片直径百分比": round(early_ratio, 3)})
        else:
            hip_item = _item("DL-03", "髋膝关系", "明显待改善", 6, "杠铃仍接近地面时，髋部先出现明显上移。", (first["frame"], raw[1]["frame"]), {"髋部提前上移_杠片直径百分比": round(early_ratio, 3)})
    else:
        hip_item = _neutral_item("DL-03", "髋膝关系", "离地前髋或膝关键点被杠片遮挡。", (first["frame"], early_frame))

    reference, ascent = rear_evidence["reference"], rear_evidence["ascent"]
    def tilt(stage):
        left, right = stage["screen_left"], stage["screen_right"]
        return math.degrees(math.atan2(float(right["y"]) - float(left["y"]), float(right["x"]) - float(left["x"])))
    tilt_change = abs(tilt(ascent) - tilt(reference))
    rear_sample = _nearest_pose_frame(rear_pose, int(rear_evidence["reference"]["frame"]))
    shoulder_points = [_joint(rear_sample, name) for name in ("left_shoulder", "right_shoulder")]
    hip_points = [_joint(rear_sample, name) for name in ("left_hip", "right_hip")]
    pose_symmetry = []
    if all(shoulder_points):
        pose_symmetry.append(abs(shoulder_points[0][1] - shoulder_points[1][1]) / plate * 100)
    if all(hip_points):
        pose_symmetry.append(abs(hip_points[0][1] - hip_points[1][1]) / plate * 100)
    symmetry_value = max([tilt_change, *pose_symmetry])
    symmetry_item = _status_for_three_band(
        symmetry_value, 2, 4, WEIGHTS["DL-04"], ("DL-04", "左右对称"),
        "后方两端高度与身体左右趋势稳定。", "后方出现轻微左右高度或同步差。", "后方出现持续明显左右不同步趋势。",
        (reference["frame"], ascent["frame"]), "左右不对称综合指标",
    )

    if lockout_chain:
        hip_angle = _angle(lockout_chain[0], lockout_chain[1], lockout_chain[2])
        knee_angle = _angle(lockout_chain[1], lockout_chain[2], lockout_chain[3])
        lockout_angle = min(hip_angle or 0, knee_angle or 0)
        lockout_item = _status_for_three_band(
            180 - lockout_angle, 15, 25, WEIGHTS["DL-05"], ("DL-05", "锁定完成度"),
            "锁定时髋膝接近伸直，杠铃稳定。", "锁定接近完成，但姿势仍可更干净。", "锁定完成度不足或存在明显后仰趋势。",
            (last["frame"],), "距伸直差_度",
        )
    else:
        lockout_item = _neutral_item("DL-05", "锁定完成度", "锁定帧姿态关键点未被可靠覆盖。", (last["frame"],))

    y_values = [float(point["y"]) for point in raw]
    reversals = sum(1 for previous, current in zip(y_values, y_values[1:]) if current > previous + plate * .01)
    flow_item = _status_for_three_band(
        reversals, 0, 1, WEIGHTS["DL-06"], ("DL-06", "动作流畅度"),
        "杠铃离地后保持连续上升。", "起拉中出现一次轻微非计划性调整。", "起拉中出现明显回落或反复调整。",
        (first["frame"], last["frame"]), "非计划性回落次数",
    )

    items = [bar_item, spine_item, hip_item, symmetry_item, lockout_item, flow_item]
    total = sum(item["score"] for item in items)
    return {
        "schema_version": "deadlift-score-v1", "scorable": True,
        "total": total, "grade": _grade(total, items), "items": items,
        "unavailable_reason": None, "limitation": LIMITATION,
    }


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description="Practical side + front/rear deadlift AI score")
    parser.add_argument("--side", type=Path, required=True)
    parser.add_argument("--rear", type=Path, required=True)
    parser.add_argument("--side-pose", type=Path, required=True)
    parser.add_argument("--rear-pose", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    side, rear = _load(args.side), _load(args.rear)
    side_pose, rear_pose = _load(args.side_pose), _load(args.rear_pose)
    for tracking, pose, label in ((side, side_pose, "侧面"), (rear, rear_pose, "后方")):
        tracking_sha = ((tracking.get("source_video") or {}).get("sha256"))
        pose_sha = ((pose.get("source_video") or {}).get("sha256"))
        if not tracking_sha or tracking_sha != pose_sha:
            parser.error(f"{label}姿态数据与动作视频不匹配，拒绝评分")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(score_deadlift(side, rear, side_pose, rear_pose), ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
