# Squat analysis rules

## Evidence model

- Track the visible bar hub plus hip, knee, and ankle/foot.
- In a usable side view, compare bar x with `reference.midfoot_x` throughout descent and ascent.
- Metric: `max(abs(bar_x - midfoot_x)) / plate_diameter * 100`. Report direction, phase, and whether the drift returns; do not turn the percentage into a universal injury threshold.

The bar-plus-lifter system is usually organized over the base of support, but body proportions, bar position, stance, footwear, and camera parallax change the visible path. “Perfectly vertical” is not required frame by frame.

若同一侧面画面中有停放杠片、架孔或背景圆形器械，先把工作杠片关联到运动者。可信肩／髋点只能排除远离运动者或躯干比例不合理的候选，不能替代杠铃点位。连续路径必须在准备、最低点、上升初段与锁定附近重新用真实轮毂／边缘候选锚定；短缺口可以用浅色线供阅读，但不得参与中足趋势、评分或训练方向。

## Timing and observations

Compare hip and knee descent, bottom reversal, chest/hip rise, heel and whole-foot stability, depth relative to the chosen standard, brace, and bar position. A hip rise that briefly outpaces the shoulders during a hard ascent is evidence to interpret, not automatic proof of weak quadriceps.

A side or oblique video cannot reliably determine frontal-plane knee valgus, left-right symmetry, foot pressure distribution, or rotation. Request front/rear footage when those questions matter.

## Automatic phase detection

Use screen coordinates (`Y` grows downward) and normalise all movement by the
setup hip–knee distance; never use a fixed pixel or centimetre threshold.

- `setup`: hip height, knee angle, and bar height remain stable for 0.5 seconds.
- `descent`: hip-Y increases and knee angle decreases for at least three samples.
- `bottom`: local maximum hip-Y followed by a verified ascent; do not use one-frame hip-vs-knee height as a universal depth judgement.
- `pause_bottom`: bottom remains stable at least 0.4 seconds; mark the variant, do not call it a fault.
- `ascent`: hip-Y decreases and knee angle increases for at least three samples.
- `lockout`: hip/knee return near setup extension and the bar/body remain stable for 0.5 seconds.

Reject a candidate repetition when ankle translation is large relative to the
visible hip–knee scale. Torso-angle change without concurrent hip descent and
knee flexion is not a squat. When hip, knee, or ankle is not reliable, report
that item as unavailable rather than inferring depth or timing.

## AI score V1

Score only a conventional squat from a usable side/oblique continuous bar path
plus rear bilateral bar-end evidence. The two camera recordings are independent
representative repetitions. Internally score bar trend (20), bottom control
(15), trunk stability (20), hip-knee coordination (20), rear stability (15),
and flow/lockout (10). Unknown pose-only components receive an 80% neutral
baseline; they cannot create a corrective finding or training direction.
