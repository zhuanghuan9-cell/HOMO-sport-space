#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


EXERCISES = {"deadlift", "squat", "bench_press"}
CAMERA_VIEWS = {"side", "oblique_side", "front", "rear", "foot_end", "head_end"}
REPORT_STATUSES = {"stable", "actionable_issue"}
LANDMARKS = {
    "deadlift": ("hip", "shoulder"),
    "squat": ("hip", "knee", "ankle"),
    "bench_press": ("wrist", "elbow", "shoulder"),
}
ANATOMY_SCOPES = {"view_one", "view_two", "shared"}
GENERIC_ANATOMY_TERMS = ("臀腿后侧", "躯干稳定", "上背", "核心", "下肢", "胸肌", "臀肌", "肩胛稳定肌")
GENERIC_ANATOMY_EXACT_TERMS = {"相关肌群", "臀腿后侧", "躯干稳定", "上背", "核心", "下肢", "胸肌", "臀肌", "前臂", "肩胛稳定肌"}
VAGUE_TRAINING_ACTIONS = {"技术硬拉", "技术卧推", "技术深蹲", "直臂下拉", "手腕承重控制练习"}


def precise_muscle_name(value: object) -> bool:
    """Require one anatomical target rather than a combined body-region label."""
    normalized = value.strip() if isinstance(value, str) else ""
    return (
        bool(normalized) and normalized not in GENERIC_ANATOMY_EXACT_TERMS
        and not any(term in normalized for term in GENERIC_ANATOMY_TERMS)
        and not any(token in normalized for token in ("与", "、", "/", "／"))
    )


def valid_finding(item: object) -> bool:
    return isinstance(item, dict) and all(isinstance(item.get(key), str) and item[key].strip() for key in ("title", "detail"))


def visible_evidence_ids(findings: dict) -> set[str]:
    """Return explicit Page 1/2 evidence IDs for Page 4 action links."""
    result: set[str] = set()
    for item in findings.get("evidence") or []:
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip():
            result.add(item["id"].strip())
    return result


def evidence_training_targets(findings: dict) -> dict[str, str]:
    """Return the controlled Page-4 focus attached to each visible finding."""
    targets: dict[str, str] = {}
    for item in findings.get("evidence") or []:
        if not isinstance(item, dict):
            continue
        identifier, target = item.get("id"), item.get("training_target")
        if isinstance(identifier, str) and identifier.strip() and isinstance(target, str) and target.strip():
            targets[identifier.strip()] = target.strip()
    return targets


def expected_target_label(source_ids: list[str], targets: dict[str, str]) -> str | None:
    """Compose the visible label without inventing an unobserved diagnosis."""
    if not source_ids or any(source not in targets for source in source_ids):
        return None
    return "针对：" + "＋".join(dict.fromkeys(targets[source] for source in source_ids))


def action_execution_error(slot: str, drill: dict) -> str | None:
    """Require action names and execution details a beginner can reproduce."""
    name = str(drill.get("name") or "").strip()
    phrase = " ".join(str(drill.get(key) or "") for key in ("name", "dose", "cue"))
    if name in VAGUE_TRAINING_ACTIONS:
        return f"plan.{slot}.name must name the exact variation or equipment"
    standard_rules = {
        "常规硬拉": "每次落地重置",
        "常规卧推": "每次触胸停稳",
        "常规深蹲": "每次站稳重置",
    }
    if name in standard_rules and standard_rules[name] not in phrase:
        return f"plan.{slot}.execution must state {standard_rules[name]}"
    pause_rules = {"暂停硬拉": ("离地", "秒"), "暂停卧推": ("触胸", "秒"), "暂停深蹲": ("底部", "秒")}
    for action, required in pause_rules.items():
        if action in name and not all(token in phrase for token in required):
            return f"plan.{slot}.execution must state the pause location and duration"
    if "3秒离心深蹲" in name and not all(token in phrase for token in ("3秒", "下降")):
        return f"plan.{slot}.execution must state the eccentric duration and descent phase"
    return None


def validate_report_model(data: dict) -> list[str]:
    """Validate optional beginner-facing finding and action-plan fields.

    Legacy `findings.improve/good` and `plan.drills` remain valid; the new
    fields add explicit priority and a deliberately small prescription.
    """
    errors: list[str] = []
    findings = data.get("findings")
    if findings is not None:
        if not isinstance(findings, dict):
            errors.append("findings must be an object")
        else:
            report_status = findings.get("report_status", "actionable_issue")
            if report_status not in REPORT_STATUSES:
                errors.append("findings.report_status must be stable or actionable_issue")
            evidence = findings.get("evidence")
            if evidence is not None:
                if not isinstance(evidence, list) or not evidence:
                    errors.append("findings.evidence must be a non-empty list when supplied")
                else:
                    ids: list[str] = []
                    for position, item in enumerate(evidence, start=1):
                        if not isinstance(item, dict) or not all(isinstance(item.get(key), str) and item[key].strip() for key in ("id", "title", "view")) or item.get("page") not in {1, 2}:
                            errors.append(f"findings.evidence[{position}] needs id/title/view and page 1 or 2")
                            continue
                        if report_status != "stable" and (not isinstance(item.get("training_target"), str) or not item["training_target"].strip()):
                            errors.append(f"findings.evidence[{position}].training_target must be concise non-empty text")
                        ids.append(item["id"].strip())
                    if len(ids) != len(set(ids)):
                        errors.append("findings.evidence ids must be unique")
            if "primary" in findings and not valid_finding(findings["primary"]):
                errors.append("findings.primary needs non-empty title/detail")
            primary = findings.get("primary") or {}
            if report_status == "stable":
                if not isinstance(primary, dict) or primary.get("no_muscle_direction") is not True:
                    errors.append("stable report requires findings.primary.no_muscle_direction=true")
                if isinstance(primary, dict) and primary.get("muscle_targets"):
                    errors.append("stable report must not supply muscle_targets")
                improve = findings.get("improve") or []
                if improve:
                    errors.append("stable report must not contain findings.improve")
            if isinstance(primary, dict) and "muscle_targets" in primary:
                targets = primary["muscle_targets"]
                valid_target = lambda item: isinstance(item, dict) and precise_muscle_name(item.get("name")) and isinstance(item.get("role"), str) and bool(item["role"].strip())
                if not isinstance(targets, list) or not targets or not all(valid_target(item) for item in targets):
                    errors.append("findings.primary.muscle_targets needs non-empty name/role objects")
            if isinstance(primary, dict) and "optimization" in primary:
                if not isinstance(primary["optimization"], str) or not primary["optimization"].strip():
                    errors.append("findings.primary.optimization must be non-empty text")
            for group in ("improve", "good", "unavailable"):
                if group in findings:
                    if group in {"improve", "good"} and isinstance(findings[group], str) and findings[group].strip():
                        continue  # Legacy single-sentence finding.
                    if not isinstance(findings[group], list) or not all(valid_finding(item) for item in findings[group]):
                        errors.append(f"findings.{group} must be finding objects with title/detail")
    plan = data.get("plan")
    if plan is not None:
        if not isinstance(plan, dict):
            errors.append("plan must be an object")
        else:
            report_status = ((findings or {}).get("report_status") if isinstance(findings, dict) else None) or "actionable_issue"
            if report_status == "stable" and any(key in plan for key in ("cue", "main_drill", "assist_drill", "technical", "correction", "assistance", "drills")):
                errors.append("stable report must not contain training drills or cues")
            if "cue" in plan and (not isinstance(plan["cue"], str) or not plan["cue"].strip()):
                errors.append("plan.cue must be non-empty text")
            for key in ("main_drill", "assist_drill", "technical", "correction", "assistance"):
                if key in plan:
                    drill = plan[key]
                    if not isinstance(drill, dict) or not isinstance(drill.get("name"), str) or not drill["name"].strip() or not isinstance(drill.get("dose"), str) or not drill["dose"].strip():
                        errors.append(f"plan.{key} needs non-empty name/dose")
                    elif key in {"technical", "correction", "assistance"} and "cue" in drill and (not isinstance(drill["cue"], str) or not drill["cue"].strip()):
                        errors.append(f"plan.{key}.cue must be non-empty text")
            # V3's three visible training cards may not be generic.  Each one
            # must cite a visible Page 1/2 finding and provide the short tag
            # that the reader sees on Page 4.
            v3_slots = ("technical", "correction", "assistance")
            if report_status != "stable" and any(key in plan for key in v3_slots):
                evidence_ids = visible_evidence_ids(findings if isinstance(findings, dict) else {})
                targets = evidence_training_targets(findings if isinstance(findings, dict) else {})
                if not evidence_ids:
                    errors.append("V3 training slots require findings.evidence")
                for key in v3_slots:
                    if key not in plan:
                        continue
                    drill = plan[key]
                    if not isinstance(drill, dict):
                        continue
                    source_ids = drill.get("source_ids")
                    if not isinstance(source_ids, list) or not source_ids or not all(isinstance(source, str) and source.strip() for source in source_ids):
                        errors.append(f"plan.{key}.source_ids needs one or more visible evidence ids")
                    label = drill.get("target_label")
                    if not isinstance(label, str) or not label.startswith("针对：") or len(label.strip()) <= len("针对："):
                        errors.append(f"plan.{key}.target_label must start with 针对：")
                    elif isinstance(source_ids, list) and all(isinstance(source, str) and source.strip() for source in source_ids):
                        # A secondary-camera JSON may deliberately cite Page-1
                        # evidence from its paired primary JSON.  Resolve that
                        # cross-view reference in the renderer; validate the
                        # exact label here when all sources are local.
                        local_sources = [source.strip() for source in source_ids]
                        expected = expected_target_label(local_sources, targets)
                        if expected is not None and label.strip() != expected:
                            errors.append(f"plan.{key}.target_label must match source evidence training_target")
                    execution_error = action_execution_error(key, drill)
                    if execution_error:
                        errors.append(execution_error)
    anatomy = (data.get("render") or {}).get("anatomy_indices")
    if anatomy is not None:
        if not isinstance(anatomy, list):
            errors.append("render.anatomy_indices must be a list")
        else:
            for index, item in enumerate(anatomy, start=1):
                muscle = item.get("muscle") if isinstance(item, dict) else None
                if not precise_muscle_name(muscle):
                    errors.append(f"render.anatomy_indices[{index}] needs one precise muscle name")
                    continue
                if item.get("view") not in {"正面", "背面"}:
                    errors.append(f"render.anatomy_indices[{index}].view must be 正面 or 背面")
                if item.get("scope") not in ANATOMY_SCOPES:
                    errors.append(f"render.anatomy_indices[{index}].scope must be view_one/view_two/shared")
                for key in ("target", "label"):
                    value = item.get(key)
                    if not isinstance(value, list) or len(value) != 2 or not all(isinstance(point, (int, float)) for point in value) or not (0 <= value[0] <= 1080 and 0 <= value[1] <= 1440):
                        errors.append(f"render.anatomy_indices[{index}].{key} must be [x, y] in card space")
    return errors


def exercise_of(data: dict) -> str:
    return data.get("exercise", "deadlift")


def landmarks_of(repetition: dict) -> dict:
    values = dict(repetition.get("landmarks") or {})
    for name in ("hip", "shoulder"):
        legacy = repetition.get(f"{name}_path")
        if legacy and name not in values:
            values[name] = legacy
    return values


def validate(data: dict) -> list[str]:
    errors: list[str] = []
    exercise = exercise_of(data)
    if exercise not in EXERCISES:
        errors.append(f"exercise must be one of {sorted(EXERCISES)}")
        return errors
    source_video = data.get("source_video")
    if source_video is not None:
        if not isinstance(source_video, dict):
            errors.append("source_video must be an object when supplied")
        else:
            sha = source_video.get("sha256")
            detected_view = str(source_video.get("detected_view") or "").strip()
            confidence = source_video.get("classification_confidence")
            if not isinstance(sha, str) or len(sha) != 64 or any(char not in "0123456789abcdef" for char in sha.lower()):
                errors.append("source_video.sha256 must be a SHA-256 hex digest")
            if detected_view not in CAMERA_VIEWS:
                errors.append(f"source_video.detected_view must be one of {sorted(CAMERA_VIEWS)}")
            if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
                errors.append("source_video.classification_confidence must be between 0 and 1")
            if detected_view in CAMERA_VIEWS and data.get("view") and data.get("view") != detected_view:
                errors.append("tracking.view must match source_video.detected_view")
    size = data.get("image_size")
    if not isinstance(size, list) or len(size) != 2 or not all(isinstance(v, (int, float)) and v > 0 for v in size):
        return errors + ["image_size must be [width, height]"]
    width, height = size
    plate = data.get("plate_diameter_px")
    if not isinstance(plate, (int, float)) or plate <= 0:
        errors.append("plate_diameter_px must be positive")
    repetitions = data.get("repetitions")
    if not isinstance(repetitions, list) or not repetitions:
        return errors + ["repetitions must be a non-empty list"]
    if exercise == "squat":
        midfoot = (data.get("reference") or {}).get("midfoot_x")
        if not isinstance(midfoot, (int, float)) or not 0 <= midfoot < width:
            errors.append("squat requires reference.midfoot_x inside image")
    analysis_mode = (data.get("render") or {}).get("analysis_mode", "full")
    bar_tracking = data.get("bar_tracking") or {}
    bar_path_unavailable = analysis_mode == "bar_path_unavailable"
    if bar_tracking:
        status = bar_tracking.get("status")
        if status not in {"available", "unavailable"}:
            errors.append("bar_tracking.status must be available or unavailable")
        if status == "available":
            raw = bar_tracking.get("raw_points", bar_tracking.get("points"))
            display = bar_tracking.get("display_points")
            if not isinstance(raw, list) or len(raw) < 2:
                errors.append("available bar_tracking requires at least two raw_points")
            if not isinstance(display, list) or len(display) < len(raw):
                errors.append("available bar_tracking requires display_points")
            for point in display or []:
                if point.get("display_source") == "smoothed_gap" and any(key in point for key in ("confidence", "radius")):
                    errors.append("smoothed_gap must not masquerade as a raw measurement")
    if bar_path_unavailable:
        if bar_tracking.get("status") != "unavailable" or not bar_tracking.get("rejection_reasons"):
            errors.append("bar_path_unavailable requires rejected bar_tracking with a reason")
    for position, repetition in enumerate(repetitions, start=1):
        bar = repetition.get("bar_path") or []
        if not bar_path_unavailable and len(bar) < 6:
            errors.append(f"rep {position}: bar_path needs at least 6 points")
        point_groups = list(landmarks_of(repetition).items())
        if not bar_path_unavailable:
            point_groups.insert(0, ("bar_path", bar))
        for name, points in point_groups:
            for point in points:
                if not all(key in point for key in ("frame", "time", "x", "y")):
                    errors.append(f"rep {position}: {name} point missing frame/time/x/y")
                    continue
                if not (0 <= point["x"] < width and 0 <= point["y"] < height):
                    errors.append(f"rep {position}: {name} point outside image")
        if exercise == "bench_press" and not bar_path_unavailable:
            phases = {point.get("phase") for point in bar}
            for phase in ("start", "touch", "lockout"):
                if phase not in phases:
                    errors.append(f"rep {position}: bench bar_path needs {phase} phase")
    if analysis_mode not in {"full", "bar_path_only", "symmetry_only", "bar_path_unavailable"}:
        errors.append("render.analysis_mode must be full/bar_path_only/symmetry_only/bar_path_unavailable")
    if analysis_mode == "full":
        detailed = landmarks_of(repetitions[-1])
        for name in LANDMARKS[exercise]:
            if len(detailed.get(name, [])) < 6:
                errors.append(f"detailed/last repetition needs at least 6 {name} points")
    rear_evidence = (data.get("render") or {}).get("rear_bar_evidence")
    if rear_evidence is not None:
        if not (exercise == "squat" and data.get("view") == "rear"):
            errors.append("render.rear_bar_evidence is only valid for a rear squat view")
        elif not isinstance(rear_evidence, dict):
            errors.append("render.rear_bar_evidence must be an object")
        else:
            for stage in ("bottom", "press"):
                item = rear_evidence.get(stage)
                if not isinstance(item, dict) or not isinstance(item.get("frame"), int) or not isinstance(item.get("time"), (int, float)) or not isinstance(item.get("label"), str) or not item["label"].strip():
                    errors.append(f"render.rear_bar_evidence.{stage} needs frame/time/label")
                    continue
                for end in ("screen_left", "screen_right"):
                    point = item.get(end)
                    if not isinstance(point, dict) or not all(isinstance(point.get(axis), (int, float)) for axis in ("x", "y")) or not (0 <= point["x"] < width and 0 <= point["y"] < height):
                        errors.append(f"render.rear_bar_evidence.{stage}.{end} must be inside image")
    rear_level = (data.get("render") or {}).get("rear_bar_level_evidence")
    if rear_level is not None:
        if not (exercise in {"squat", "deadlift"} and data.get("view") == "rear"):
            errors.append("render.rear_bar_level_evidence is only valid for a rear squat or deadlift view")
        elif not isinstance(rear_level, dict):
            errors.append("render.rear_bar_level_evidence must be an object")
        else:
            for stage in ("reference", "ascent"):
                item = rear_level.get(stage)
                if not isinstance(item, dict) or not isinstance(item.get("frame"), int) or not isinstance(item.get("time"), (int, float)) or not isinstance(item.get("label"), str) or not item["label"].strip():
                    errors.append(f"render.rear_bar_level_evidence.{stage} needs frame/time/label")
                    continue
                for end in ("screen_left", "screen_right"):
                    point = item.get(end)
                    if not isinstance(point, dict) or not all(isinstance(point.get(axis), (int, float)) for axis in ("x", "y")) or not (0 <= point["x"] < width and 0 <= point["y"] < height):
                        errors.append(f"render.rear_bar_level_evidence.{stage}.{end} must be inside image")
    return errors + validate_report_model(data)


def vertical_label(percent: float) -> str:
    if percent <= 5:
        return "接近垂直"
    if percent <= 10:
        return "轻微漂移"
    return "明显漂移"


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate squat, bench press, or deadlift tracking JSON.")
    parser.add_argument("--input", required=True, type=Path)
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8"))
    errors = validate(data)
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1

    exercise = exercise_of(data)
    plate = float(data["plate_diameter_px"])
    repetitions = data["repetitions"]
    mode = {"deadlift": "vertical_reference", "squat": "midfoot_reference", "bench_press": "j_curve"}[exercise]
    print(f"exercise={exercise} mode={mode} repetitions={len(repetitions)} image_size={data['image_size'][0]}x{data['image_size'][1]}")
    if (data.get("render") or {}).get("analysis_mode") == "bar_path_unavailable":
        print("bar_path=unavailable reason=" + "；".join((data.get("bar_tracking") or {}).get("rejection_reasons", [])))
        return 0
    for repetition in repetitions:
        bar = repetition["bar_path"]
        if exercise == "deadlift":
            percent = max(abs(float(point["x"]) - float(bar[0]["x"])) for point in bar) / plate * 100
            print(f"rep={repetition.get('rep')} max_lateral_percent={percent:.1f} result={vertical_label(percent)}")
        elif exercise == "squat":
            midfoot = float(data["reference"]["midfoot_x"])
            percent = max(abs(float(point["x"]) - midfoot) for point in bar) / plate * 100
            print(f"rep={repetition.get('rep')} max_midfoot_deviation_percent={percent:.1f}")
        else:
            start = next(point for point in bar if point.get("phase") == "start")
            touch = next(point for point in bar if point.get("phase") == "touch")
            lockout = next(point for point in reversed(bar) if point.get("phase") == "lockout")
            displacement = (float(touch["x"]) - float(start["x"])) / plate * 100
            return_error = abs(float(lockout["x"]) - float(start["x"])) / plate * 100
            print(f"rep={repetition.get('rep')} top_to_touch_percent={displacement:.1f} lockout_return_error_percent={return_error:.1f}")
    assessment = repetitions[-1].get("assessment") or {}
    if exercise == "deadlift":
        print(f"early_hip_rise={str(bool(assessment.get('early_hip_rise', False))).lower()}")
    findings = data.get("findings") or {}
    if findings.get("primary"):
        print(f"primary={findings['primary']['title']}")
    plan = data.get("plan") or {}
    if plan.get("cue"):
        print(f"cue={plan['cue']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
