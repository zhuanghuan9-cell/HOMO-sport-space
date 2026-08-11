#!/usr/bin/env python3
"""Compose a strict bar-tracking result into a safe report copy."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path


BAR_WORDS = ("杠铃", "轨迹", "漂移", "前移", "中足", "j形", "J形", "路径")


def is_bar_finding(item: object) -> bool:
    if not isinstance(item, dict):
        return False
    text = " ".join(str(item.get(key, "")) for key in ("id", "title", "detail", "training_target"))
    return any(word in text for word in BAR_WORDS)


def compose(tracking: dict, bar: dict) -> dict:
    result = copy.deepcopy(tracking)
    bar_data = bar["bar_tracking"]
    source_sha = ((result.get("source_video") or {}).get("sha256"))
    if source_sha and source_sha != ((bar.get("source_video") or {}).get("sha256")):
        raise ValueError("bar tracking source hash does not match report tracking")
    result["bar_tracking"] = bar_data
    if bar_data["status"] == "available":
        raw_points = bar_data.get("raw_points", bar_data.get("points", []))
        if len(raw_points) < 2:
            raise ValueError("available bar tracking requires raw_points")
        result["repetitions"][-1]["bar_path"] = [{key: point[key] for key in ("frame", "time", "phase", "x", "y")} for point in raw_points]
        return result
    findings = result.setdefault("findings", {})
    removed_ids = {item.get("id") for item in findings.get("evidence", []) if is_bar_finding(item)}
    remaining_evidence = [item for item in findings.get("evidence", []) if not is_bar_finding(item)]
    if remaining_evidence:
        findings["evidence"] = remaining_evidence
    else:
        findings.pop("evidence", None)
    # A legacy card can contain unlinked checklist rows (for example a
    # path-derived shoe/stability suggestion) that have no independently
    # verified evidence or training source.  They may not survive as a
    # corrective finding once the sole path evidence has been rejected.
    findings["improve"] = []
    findings["primary"] = {
        "title": "当前视频无法可靠判断杠铃轨迹",
        "detail": "自动追踪没有稳定锁定同一近侧杠片轴心，因此不报告杠铃路径或由路径推导的问题。",
        "no_muscle_direction": True,
        "optimization": "保留当前可靠的视频观察；下次让近侧杠片完整清楚地进入画面，再复查杠铃路径。",
    }
    plan = result.setdefault("plan", {})
    for slot in ("technical", "correction", "assistance", "main_drill", "assist_drill"):
        item = plan.get(slot)
        if isinstance(item, dict) and (not item.get("source_ids") or removed_ids.intersection(item.get("source_ids", []))):
            plan.pop(slot, None)
    plan.pop("cue", None)
    findings["report_status"] = "stable"
    # Renderer retains phase timing for screenshots but must never draw it.
    result.setdefault("render", {})["analysis_mode"] = "bar_path_unavailable"
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tracking", required=True, type=Path)
    parser.add_argument("--bar-tracking", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    data = compose(json.loads(args.tracking.read_text(encoding="utf-8")), json.loads(args.bar_tracking.read_text(encoding="utf-8")))
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
