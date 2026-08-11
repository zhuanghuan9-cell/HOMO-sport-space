# Unified tracking schema

Use one UTF-8 JSON file as the source of truth.

## Optional strict bar-tracking companion file

`bar-tracking.json` is a separate automatic audit file created by
`scripts/track_barbell.py`. It never overwrites the source tracking. Its
`bar_tracking.status` is either `available` or `unavailable`; it stores
`raw_points` from approximately 30fps circular/elliptical near-side plate
candidate tracking that passed size, continuity, and motion gates. It also
stores `display_points`: a presentation-only lightly smoothed version of raw
points, with short visual bridges marked `display_source: "smoothed_gap"`.
Only `raw_points` may drive `bar_path`, metrics, findings, muscle directions,
or training. It must include the source SHA-256, per-point confidence and
radius, action span, sampling rate, and rejection reasons when unavailable.
Do not manually correct, reuse an old path, or use colour/text/fixed-coordinate
detection.

`method` records whether a result came from direct
`circle_ellipse_continuity` or the stricter fallback
`circle_ellipse_seeded_csrt_continuity`. The latter is only eligible when it
starts from an automatic rim candidate and independently agrees with rim
geometry at at least 75% of required phases where such geometry is visible;
otherwise the entire path remains unavailable.

Pass the already source-bound Swift extraction directory with `--frames-dir`
whenever it is available. This makes every tracked image exactly match the
report frame and avoids codec seek differences near a video boundary.

Only an `available` result may be composed into `bar_path`:

```bash
python3 scripts/compose_bar_tracking.py --tracking tracking.json \
  --bar-tracking bar-tracking.json --output report-safe.json
```

When unavailable, `report-safe.json` uses
`render.analysis_mode: "bar_path_unavailable"`; it retains screenshots and
independent evidence but removes bar-path conclusions, path muscle targets,
and path-derived training. Rear squat/deadlift and foot-end bench use only
their bilateral endpoint protocol and do not use this companion file.

## Optional internal RTMPose companion file

`pose-tracking.json` is intentionally a separate file, so an experimental model
cannot silently overwrite manually reviewed bar tracking or alter a card. Create
it with `scripts/track_pose_rtmpose.py`; its schema records source SHA-256,
official-model cache hashes, 15/30 fps sampling, and raw confidence-gated joint
points. Validate it against the associated card tracking before using it:

```bash
python3 scripts/validate_pose_tracking.py --pose pose-tracking.json \
  --tracking tracking.json --view oblique_side
```

Only `status: available` may support a joint-timing statement, and even then only
for a permitted side/oblique view and together with trusted bar evidence. A
failure means “当前机位无法判断” for that joint-specific finding—not an invitation to
insert, smooth, or manually guess a point. Full contract and benchmark rollout
criteria: `references/pose-tracking.md`.

```json
{
  "exercise": "squat",
  "view": "side",
  "source_video": {
    "filename": "source.mp4",
    "sha256": "64-character SHA-256 digest",
    "detected_view": "side",
    "classification_confidence": 0.91
  },
  "image_size": [1920, 1080],
  "plate_diameter_px": 280,
  "privacy": {
    "face_box": [900, 120, 1030, 280],
    "face_boxes": {"40": [900, 120, 1030, 280]}
  },
  "render": {
    "crop": [420, 0, 1500, 1080],
    "analysis_mode": "full",
    "page_one_photo_fit": "contain",
    "anatomy_indices": [{
      "number": "①",
      "muscle": "股四头肌群",
      "view": "正面",
      "scope": "view_one",
      "target": [420, 630],
      "label": [82, 620]
    }]
  },
  "reference": {"midfoot_x": 965},
  "repetitions": [{
    "rep": 1,
    "bar_path": [{"frame": 40, "time": 1.33, "x": 960, "y": 250, "phase": "start"}],
    "landmarks": {
      "hip": [{"frame": 40, "time": 1.33, "x": 1030, "y": 480}],
      "knee": [],
      "ankle": []
    },
    "assessment": {}
  }],
  "findings": {
    "report_status": "actionable_issue",
    "evidence": [
      {"id": "view_one.bar_forward_drift", "title": "下降时杠铃轻微屏幕前移", "view": "view_one", "page": 1, "training_target": "下降控制＋全脚掌压力＋底部控制"}
    ],
    "primary": {
      "title": "主问题",
      "detail": "直接可见的二维证据",
      "muscle_problem": "需要在第3页解释的可见问题",
      "muscle_targets": [{"name": "精确肌肉名称", "role": "在本动作中提供什么稳定或驱动力"}],
      "capacity_summary": "相关肌群如何服务于该问题的简短说明",
      "optimization": "一句和证据对应的动作优化提示",
      "no_muscle_direction": false
    },
    "improve": [{"title": "次要待改善", "detail": "直接可见的二维证据"}],
    "good": [{"title": "做得好", "detail": "直接可见的二维证据"}],
    "unavailable": [{"title": "无法判断", "detail": "需要什么机位才可确认"}]
  },
  "plan": {
    "cue": "一句可执行动作口令",
    "main_drill": {"name": "主练", "dose": "组数×次数或强度"},
    "assist_drill": {"name": "辅助练", "dose": "组数×次数或强度"},
    "technical": {"name": "技术主项", "dose": "组数×次数或强度", "cue": "一句短口令", "source_ids": ["view_one.bar_forward_drift"], "target_label": "针对：下降时杠铃轻微前移"},
    "correction": {"name": "机位一纠正", "dose": "组数×次数或强度", "cue": "一句短口令", "source_ids": ["view_one.bar_forward_drift"], "target_label": "针对：底部控制"},
    "assistance": {"name": "机位二辅助", "dose": "组数×次数或强度", "cue": "一句短口令", "label": "可选的第三项卡片标签", "source_ids": ["view_one.bar_forward_drift"], "target_label": "针对：下降控制"},
    "checks": []
  }
}
```

## Required

- `exercise`: `deadlift`, `squat`, or `bench_press`. Missing means legacy `deadlift`.
- For every newly created dual-camera report, `source_video` is required and is copied from the matched `frame-manifest.json`. `tracking.view` must equal `source_video.detected_view`; a source with confidence below `0.85` is not eligible for paired rendering. Legacy single-camera JSON remains readable, but cannot be used for a new dual-camera render until bound to a manifest.
- Positive `image_size`, `plate_diameter_px`, and at least one repetition.
- At least six ordered `bar_path` points per repetition when
  `render.analysis_mode` is not `bar_path_unavailable`. Each point needs
  source-frame `frame`, `time`, `x`, `y`. A `bar_path_unavailable` report may
  retain legacy timing points only for selecting screenshots; the renderer must
  not draw or interpret them.
- Detailed/last repetition landmarks: deadlift `hip, shoulder`; squat `hip, knee, ankle`; bench `wrist, elbow, shoulder`.
- A bench foot-end view may additionally store `wrist_screen_left`, `wrist_screen_right`, `elbow_screen_left`, and `elbow_screen_right`. These screen-side names describe the viewer's image, not anatomical left/right.
- Squat: `reference.midfoot_x` in source pixels.
- Bench phases include `start`, `touch`, `lockout`; use `descent` and `press` between them.

## View and optional dual-view reports

- `view` should be one of `side`, `oblique_side`, `front`, `rear`, `foot_end`, or `head_end`.
- Store each camera in a separate JSON with its own image size, crop, privacy boxes, repetitions, and landmarks.
- Standard pairs: deadlift `side/oblique_side + front/rear`; bench press `side/oblique_side + foot_end`; squat `side/oblique_side + rear`.
- Combine files only at render time with `--secondary-tracking` and `--secondary-frames-dir`.
- A non-standard pair is valid only as supplementary screen evidence; the report must state the view limitation.

## Optional report data

- `privacy.face_box` and `render.crop` use source-frame `[x1,y1,x2,y2]`. `privacy.face_boxes` may map frame numbers to boxes when the head moves substantially. A confirmed global or per-frame face box is required for public cards when a face is visible; do not guess a fallback region. Set `render.video_photo_fit: "contain"` when Page 1 and/or Page 2 must retain the complete source frame; overlays then map only to the actual contained image area. `page_one_photo_fit` remains a legacy Page-1-only fallback. `render.analysis_mode` is `full` by default; use `bar_path_only` for a side video with no usable joint landmarks, `symmetry_only` for a front/rear video that only supports left-right evidence, and `bar_path_unavailable` only when a strict companion result has rejected the path.
- `findings.evidence`: V3's visible Page 1/2 findings. Each item has unique `id`, short `title`, `view` (`view_one` or `view_two`), `page` (1 or 2), and concise `training_target`. It is the only source list that Page 4 may cite. `training_target` is a conservative training focus, not a hidden diagnosis; it becomes the Page-4 `target_label`.
- `findings.report_status`: use `actionable_issue` (default for legacy data) when at least one displayed finding needs action; its evidence requires `training_target` and Page 4 requires linked drills. Use `stable` only when every analysed camera has no `improve` finding. A stable report requires `primary.no_muscle_direction: true`, forbids `muscle_targets` and all training items, and may omit `training_target`; Page 4 becomes a positive closing card rather than a prescription.
- `findings.primary`: one `{title, detail}` object; V3 additionally accepts optional `muscle_problem`, `muscle_targets: [{name, role}]`, `capacity_summary`, and `optimization`. `muscle_problem` is the exact Page 3 issue text; `capacity_summary` explains how the named targets relate to it. They are training directions, not a muscle-strength or injury diagnosis. `findings.improve/good/unavailable` are arrays of `{title, detail}`. Legacy `improve/good` remains valid.
- `plan.cue`: one plain-language action cue. `plan.main_drill` and `plan.assist_drill` each use `{name, dose}`. V3 `technical`, `correction`, and `assistance` each require `{name, dose, cue, source_ids, target_label}`: every `source_ids` value must exist in the combined report evidence, and `target_label` must exactly equal `针对：` plus its source `training_target` values in source order. Action names must identify the variation/equipment; the combined name, dose, and cue must state pause location/duration or tempo phase where relevant. `assistance.label` optionally replaces the default third-card label. `plan.checks` contains concise acceptance criteria. Legacy `plan.drills` remains valid.
- `render.bench_sync_frames`: optional `{touch, press}` source-frame override for a matched foot-end evidence card.
- `render.rear_bar_level_evidence`: required new format for rear squat/deadlift level review: `{reference, ascent}`. Each object contains `frame`, `time`, `screen_left: {x, y}`, `screen_right: {x, y}`, and `label`. `reference` means bottom for squat and immediately before lift-off for deadlift; `ascent` means early ascent/early lift-off. The two endpoints are manually reviewed shaft/collar points near the plates. Render them as two-dot level evidence with a low-opacity grey-blue horizontal dashed reference, and upward arrows at `ascent`; never render a one-point rear bar trajectory. `render.rear_bar_evidence` remains a legacy rear-squat-only `{bottom, press}` compatibility input.
- `render.anatomy_indices`: required whenever either report finding includes `muscle_targets`. Each item uses one precise `muscle` name, `view` of `正面` or `背面`, `scope` of `view_one` / `view_two` / `shared`, and 1080×1440 page-space `[x, y]` `target` and `label` points. Every described muscle must have a same-scope index or the V3 render fails. The renderer maps each target onto the canonical bundled mannequin and requires the ring to be inside that muscle's reviewed central-belly mask; being merely inside the panel is not sufficient. A muscle without a bundled mask must not be used until its mask and a pass/fail test are added.

## Legacy deadlift compatibility

Top-level repetition arrays `hip_path` and `shoulder_path` are accepted in place of `landmarks`. Keep raw coordinates separate from derived `assessment` values so validation can recalculate metrics.

## Annotation protocol

Track the same physical point in every frame. Use the visible bar hub, not rotating lettering or the plate rim. Include phase transitions and visually inspect overlays at start/lift-off, bottom/touch, sticking region, and lockout.

Every screenshot overlay—point, arrow, dashed reference, leader line, label frame, and measured text bounds—must stay completely inside the actual displayed video content box. This is especially strict in `contain` mode: dark side margins are not usable annotation space. Wrap a long label before moving it, preserve a minimum 20px font, and fail rendering if it still cannot fit safely. A leader line must meet the nearest edge of its label frame rather than ending in open space.

## Deadlift path-to-capability protocol

For side or oblique deadlift footage, calculate maximum horizontal displacement from lift-off against the visible plate diameter. Above 10%, add a `漂移` finding and never call the bar path stable or continuous. Page 1 must show the start vertical reference, trace direction, endpoint callout, and a two-dimensional-view limitation.

If a capability recommendation is supplied for this drift, Page 3 must use exact, same-colour anatomy indexes and Page 4 must include a matching drill. Default pair: `背阔肌` (keep the bar close) plus `竖脊肌群` (isometric trunk position), with `直臂下拉｜3组×10–12次` as the path-control assistance drill. Do not use generic labels such as `上背` or `躯干稳定`, and do not state that a muscle is weak.

## All-lift closure rule

For any bar path, timing, or left/right difference that is visible enough to report, include the evidence, a 2D-camera limitation, a possible movement strategy, a matching short cue, and a matching training drill. A stable second view must set `no_muscle_direction: true` and omit `muscle_targets`; it must not create a corrective target merely to fill Page 3.

For every visible Page 4 training item, store one or more `source_ids` from `findings.evidence` and a short `target_label` starting with `针对：`. The renderer refuses an item without both. This makes the reader able to trace each drill back to an already shown video finding; generic training templates are not allowed.

Each `muscle_targets[].name` and `render.anatomy_indices[].muscle` must be one precise anatomical structure. Combined names (`与`、`、`、`/`、`／`) and generic regions (`胸肌`、`臀肌`、`前臂`、`上背`、`核心`、`肩胛稳定肌`) are rejected. A precise group such as `前臂屈肌群` is allowed. Every supplied muscle target requires one exact same-name, same-scope, same-colour Page 3 index ring and lead line.

For bench foot-end review, a left/right height difference is a setup/synchrony observation, never evidence that one pectoral is weak. For oblique squat review, screen-forward drift is not proof of real three-dimensional midfoot deviation.
