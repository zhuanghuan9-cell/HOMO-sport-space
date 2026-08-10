---
name: analyze-powerlifting-video
description: Use when analyzing squat, bench press, or deadlift videos/MP4s for barbell path, joint timing, technique faults, annotated frames, Chinese reports, or Xiaohongshu knowledge cards.
---

# Analyze Powerlifting Video

## Purpose

Perform a repeatable 2D video review of 深蹲、卧推、硬拉. Use an exercise-specific reference model; never judge all three lifts by a single “straight bar path” rule.

## Workflow

1. Identify `squat`, `bench_press`, or `deadlift`. If the lift or analyzed repetition is ambiguous, inspect the video before choosing.
2. Check the view automatically before tracking. Extract frames, then create one source-bound manifest per upload:

```bash
swift scripts/extract_video_frames.swift source.mp4 frames
python3 scripts/create_frame_manifest.py --video source.mp4 --frames-dir frames --exercise squat
```

   The manifest uses sampled visual evidence to identify `side` / `oblique_side` / `front` / `rear` / `foot_end` / `head_end`, records the source SHA-256 and reports a confidence. At least `0.85` is required for a two-camera report. Below that, stop and request a clearer or standard second angle; never guess. Copy `source_video` from the manifest into the corresponding tracking JSON, and keep `tracking.view` exactly equal to `source_video.detected_view`.
3. 双机位可选：单机位仍可完成报告；有两个机位时分别追踪，不能用一个机位替另一个机位下结论。标准组合是硬拉侧面/斜侧面＋前/后方、卧推侧面/斜侧面＋脚端、深蹲侧面/斜侧面＋后方。The renderer binds each tracking file to its frames by SHA-256 and orders Page 1/2 by detected view, so swapped CLI arguments cannot swap the evidence.
4. Extract about 30 fps with `scripts/extract_video_frames.swift`. Segment each repetition and exclude unrelated movement.
5. Track the visible bar hub consistently. Track the exercise-specific landmarks in the table below. Manually inspect key frames; correct tracking drift before interpretation.
6. Save JSON using `references/tracking-schema.md`, then run:

```bash
python3 scripts/validate_tracking.py --input tracking.json
```

7. Read only the matching reference: `references/deadlift.md`, `references/squat.md`, or `references/bench-press.md`.
8. For every view, record four layers: 可见证据、动作判断、可能原因、改善方向。动作判断必须分为 `主问题`、`其他待改善`、`做得好`、`无法判断`；保留完整的**其他观察**清单，但只把一个主问题放在卡片主标题。不要由一个视觉模式推断某块肌肉一定弱。
9. For public knowledge cards, set `privacy.face_box` whenever a face is visible. Each view keeps an independent JSON. Render the view-first V3 report with one camera, or combine an optional second view:

```bash
python3 scripts/render_cards_v3.py --tracking tracking.json --frames-dir frames --output-dir cards

python3 scripts/render_cards_v3.py --tracking side.json --frames-dir side-frames \
  --secondary-tracking rear.json --secondary-frames-dir rear-frames --output-dir cards
```

   Both secondary arguments must be present together and both JSON files must describe the same lift. For dual-camera reports, manifests are mandatory: the renderer matches hash rather than argument order and fails before writing cards if a hash, view, confidence, or pair is invalid. Non-standard pairs are rejected rather than silently downgraded.
10. Render every lift as four dark arcade cards in this fixed order:
   - **机位一：这个角度看到的问题**：侧面／斜侧面优先；一句结论、两张带秒数的证据帧、该机位自己的方向轨迹，以及“看到了什么 → 这意味着什么”。
   - **机位二：另一个角度看到的问题**：只在双机位时读取第二份 JSON；没有第二机位时改为补拍指导（缺失判断、机位高度、60 帧/秒与拍摄阶段）。稳定表现必须写明“稳定”，不得为了凑内容制造问题。
   - **对应肌群：分别优先加强什么**：正面＋背面像素人偶与索引圆点，说明相关肌群、动作作用与一句优化提示。写“优先加强／相关肌群”，绝不把二维视频写成“某肌肉薄弱”诊断。
   - **一次训练计划**：仅当存在已展示的明确待改善项时，严格显示技术主项、机位一纠正、机位二辅助三项；单机位时第三项为同问题辅助。每项均包含明确动作名、变式/器械或执行条件、剂量、短口令与`针对：`证据标签。若所有机位均稳定，设置 `findings.report_status: "stable"`：不得硬塞训练、肌肉强化方向或`针对：`标签；第四关改为“本组保持即可”，以“动作控制稳定，继续保持这套节奏。”收尾。
11. Review every card at 1080×1440 and again in the 360×1920 mobile preview. Check face blur, landmark placement, arrow direction, Chinese text, overlap, cropping, and legibility.
12. Re-read each page as a beginner or recreational lifter: the topic must be clear within three seconds; every line, color, frame, and label must be understandable without another page; the reader must be able to restate what happened, what it means, and what to do next in one sentence. Revise and repeat the review before delivery when any check fails.

### Complete-source Video Frames

When the user asks not to crop the original video, set `render.video_photo_fit: "contain"` in every affected tracking JSON. V3 then renders every Page 1 and Page 2 evidence frame as the full source frame, proportionally scaled and centred inside the existing video card; the remaining side margins retain the dark arcade background. Map face blur, paths, pins, reference lines, and landmarks to the contained content box, never to those margins. Default remains `cover` for backward compatibility; `page_one_photo_fit` remains a legacy Page-1-only fallback.

### Screenshot Annotation Boundary Gate

Every screenshot annotation must be fully contained by the **actual displayed video content box**: dots, arrows, dashes, leader lines, label frames, and the measured text bounds. In `contain` mode, the side margins are card decoration, not video content; no annotation may enter them.

- Fit labels by wrapping at a short phrase first, then reposition them. Keep type at or above 20px. If the annotation still cannot fit, fail rendering and shorten the label; never shrink it into illegibility or let it cross the video border.
- The leader line must start at the verified point and terminate on the nearest edge of its label frame. Stage/time labels also remain inside their own photo card.

### Rear Bar-Level Protocol

For a rear **squat or deadlift** view, never draw a one-point full up/down bar path: one sleeve or plate hub cannot represent the level of the whole bar. Instead, manually review and record both visible bar ends in `render.rear_bar_level_evidence`:

- `reference`: squat bottom or deadlift immediately before lift-off. Draw the two endpoint dots and a low-opacity grey-blue horizontal dashed reference; state whether the ends are close in height or one is visibly lower.
- `ascent`: squat early ascent or deadlift early lift-off. Draw both endpoint dots, the same low-opacity horizontal reference, and one upward arrow at each end; state whether both ends rise together or whether a persistent height difference is visible.
- Endpoint dots must sit on the same physical bar feature (the shaft/collar near each plate), not on plate rims, a rack upright, a hand, or the background. Do not infer a side-view bar path, midfoot position, or muscle weakness from this rear-only evidence.
- If the rear view is stable, state that directly and set `no_muscle_direction: true`; do not create a corrective muscle target merely to fill Page 3.

`render.rear_bar_evidence` remains accepted only as a legacy rear-squat input. New rear squat and rear deadlift reports use `render.rear_bar_level_evidence`; they must never use a single-end `arcade_trace`, a return-path line, or a generic “推起回程” label.

### Deadlift Bar-Path Consistency Gate

For a side or oblique deadlift view, calculate the bar's maximum screen-space horizontal displacement from the lift-off point as a percentage of the visible plate diameter. Above 10%, the report must describe the visible drift in either the primary finding or `其他待改善`, and Page 1 must show the start vertical reference plus the direction of the endpoint offset. Never call that path “稳定／连续／接近垂直” in `做得好` unless manual review first corrects the tracked bar point. Describe it as a 2D screen trend, not a three-dimensional or midfoot diagnosis.

When a visible deadlift drift needs a capability recommendation, use exact, independently indexed anatomy names only: `背阔肌` for keeping the bar close and `竖脊肌群` for isometric trunk positioning. Explain them as training directions, not weakness diagnoses. Page 3 must use matching pink `机位一` indexes, and Page 4 must include one direct path-control drill (default: `绳索直臂下拉｜3组×10–12次｜肘微弯但不屈肘，腋下夹紧，把杠锁在身体旁`).

### All-Lift Evidence → Capacity → Training Gate

Every visible path, timing, or left/right finding in all three lifts must form a closed loop: **visual evidence → stated 2D limit → possible movement strategy → one short cue → matching drill**. Never show a path or height difference without explaining what the viewer should take from it.

For V3 Page 4, make this link explicit: every Page 1/2 `findings.evidence` item carries a concise `training_target`; give every `technical`, `correction`, and `assistance` item one or more `source_ids` plus a visible `target_label` composed exactly as `针对：` + its source `training_target` values. The renderer must reject a training item that cannot cite shown evidence or introduces an unsupported target. A stable second view may still contribute a positive observation, but may not create an unrelated corrective drill.

- A capacity direction is optional, not mandatory. If a camera view is stable, say it is stable and set `no_muscle_direction: true`; do not invent a corrective muscle target to fill Page 3.
- 当所有机位均稳定时，`findings.report_status` 必须为 `stable`。稳定报告可以保留正向视频证据，但不需要 `training_target`，`plan` 不得包含技术主项、纠正、辅助、剂量或口令；第 3 页写明“本组未发现需要专项强化的可见问题”，第 4 页只给正向总结与固定专业鼓励语。
- When a capacity direction is supplied, each `muscle_targets` item must name exactly one anatomical structure. Page 3 must show a same-name, same-scope, same-colour index ring and lead line; Page 4 must contain at least one drill that serves that direction. Reject combined names and broad labels such as `胸肌`、`臀肌`、`前臂`、`上背`、`核心`、`肩胛稳定肌`.
- **Bench press:** a foot-end left/right bar-height difference is visual coordination evidence only. State the height difference and whether both ends leave the chest; do not diagnose one-side chest weakness. First check grip symmetry and bar centring, then use paused bench work and a forearm/wrist load-control drill where needed.
- **Squat:** an oblique-view forward screen drift is only a 2D trend, not proof of a three-dimensional midfoot deviation. Explain it through foot pressure, bottom control, and trunk-tension strategy; use the technical squat, pause squat, and slow-eccentric squat progression when those are the chosen directions.

### Beginner-safe Training Wording

Use actions that can be performed without guessing the variation or setup. Reject generic labels such as `技术硬拉`、`技术卧推`、`技术深蹲`、`直臂下拉`、`手腕承重控制练习`.

- **Hardlift drift / neck-neutral work:** `常规硬拉（每次落地重置）` → `暂停硬拉（离地3–5厘米停1秒）` → `绳索直臂下拉`.
- **Bench touch / bilateral-coordination work:** `常规卧推（每次触胸停稳）` → `暂停卧推（触胸停1秒）` → `双手哑铃农夫走`（两手同重量、掌根承重、手腕中立）. A foot-end height difference remains setup/coordination evidence, never a single-side chest-weakness diagnosis.
- **Squat screen-forward drift:** `常规深蹲（每次站稳重置）` → `暂停深蹲（底部停1–2秒）` → `3秒离心深蹲（自锁定起控制下降）`.

The action name, dose, and cue together must state the pause location/duration or tempo phase. Use a training target such as `离地路径控制`, not an unconfirmed inference such as “杠铃没有贴腿”, unless the video directly demonstrates it.

## Anatomy Index Protocol

Use **index-only** labels on Page 3. Never use a coloured rectangle, a broad scan area, or a generic body-region label as a muscle marker.

All three lifts use the same canonical cold blue-grey, front-and-back pixel scan mannequin at `assets/canonical-anatomy-front-back.png`. Do not substitute a different body proportion, clothing treatment, or anatomy asset for bench press; consistency lets the reader compare exact index locations across hardlift, bench press, and squat.

The renderer owns a reviewed central-belly pixel mask for every supported precise muscle. It transforms that mask with the actual Page-3 image layout, then rejects an index ring outside its named mask. A box-boundary check alone is insufficient. Do not approve an arbitrary coordinate by visual judgement: if the named muscle has no bundled mask, add its reviewed mask and automated pass/fail test first; otherwise omit that muscle direction.

- Whenever Page 1 or 2 describes a related muscle, Page 3 **must** render one same-colour index for that exact muscle and camera scope. The renderer must fail instead of creating a report with a missing index.
- Each index must state: number, one precise muscle name, `正面` or `背面`, ring target, external label point, and `机位一` / `机位二` / `两机位` scope. Place each ring at the named muscle's geometric centre; never place it on an adjacent muscle, joint, bone, clothing, or outside the mannequin.
- If the default front/back mannequin cannot show a described muscle accurately, add a dedicated local anatomy inset for that structure before rendering. Do not omit it, substitute a broad term, or add an unrelated visible muscle merely to fill the page.
- Do not use labels such as `臀腿后侧`、`躯干稳定`、`上背`、`核心`、`下肢`、`胸肌`、`臀肌`、`前臂` or `肩胛稳定肌` as an index name. Split structures that need separate points, e.g. 臀大肌 and 腘绳肌群. `前臂屈肌群` is acceptable because it is a named anatomical muscle group rather than the broad region `前臂`.
- Use pink for `机位一`, cyan for `机位二`, and a split pink/cyan ring for `两机位`; the same colour must appear on the matching analysis card below.
- After rendering, generate a local zoom review for traceability; it documents the automated mask gate and does not replace it:

```bash
python3 scripts/render_anatomy_audit.py --card cards/03-muscle-focus.png \
  --tracking tracking.json --output-dir cards/anatomy-audit
```

Use the crops to inspect the report, but do not use a manual pass/fail judgement for muscle placement: the canonical mask gate is authoritative.

## Card Frame Contract

Use one structural grid across all four pages: full-width boxes are `x=52–1028`; structural frames use an 18px radius and 4px outline; adjacent structural boxes use 24px vertical spacing. The header, conclusion, photo frame, muscle panel, analysis cards, filming guide, and training cards follow this contract. Transparent conclusion and muscle panels keep the grid visible but still use the same rounded outline. Screenshot-internal pins and progress bars are not structural frames.

**Page 3 prioritises anatomy at phone width.** Keep its HUD at `x=52–1028, y=44–152`, delete the generic conclusion/summary bar entirely, and use one transparent purple rounded muscle panel at `x=52–1028, y=176–782`. The two analysis cards begin at `y=806` and must not be compressed. Transform the canonical safe zones with the actual asset layout; do not mechanically scale arbitrary old points or use manual visual approval. A ring must remain in its named central-belly mask, and its complete label/leader must stay inside the new panel.

## Exercise Contract

| Lift | Primary reference | Detailed landmarks |
|---|---|---|
| 硬拉 | lift-off vertical line; shoulder–hip timing | hip, shoulder |
| 深蹲 | bar relative to midfoot; descent/ascent coordination | hip, knee, ankle |
| 卧推 | touch-and-return J/diagonal path, not verticality | wrist, elbow, shoulder |

For bench press, require `start`, `touch`, and `lockout` phases. For squat, require `reference.midfoot_x`. Old deadlift JSON with top-level `hip_path` and `shoulder_path` remains valid.

For bench cards, show the actual path plus the `start → touch → lockout` J-path phase reference. Use wrist rose, elbow purple, shoulder blue, and bar cyan/blue-green. Draw independent time traces and short labels only; do not connect them as a body skeleton.

For a **foot-end-only** bench video, do not draw or judge a J-path. In V3, Page 1 is the foot-end evidence and Page 2 is a bench-height side-view filming guide. State only whether the ends move together and whether a visible height difference persists.

For a foot-end bench timing card with bilateral wrist and elbow landmarks, prefer two matched frames—touch and early press—over center-point traces. Label screen-left and screen-right evidence directly, state whether both ends leave the chest, and keep any asymmetry conclusion separate from muscle-weakness claims.

Use the side/oblique view for bar path and sagittal timing. Use front/rear/foot-end views only for directly visible symmetry, stance, grip, bar-level, and left-right coordination. Never infer a side-view path from a front/rear view or bilateral symmetry from a side view.

## Safety and Reporting Limits

This is screen-space 2D coaching analysis, not motion capture or medical diagnosis. A single oblique view cannot establish joint forces, bilateral symmetry, valgus, or axial rotation. Stop heavy training and seek qualified assessment for sharp pain, numbness, radiating symptoms, or sudden strength loss.
