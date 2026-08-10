# RTMPose 内部姿态追踪

这是给分析流程使用的关节定位输入，不是“动作正确率”模型，也不会在知识卡上画全身骨架。

## 首次运行

```bash
python3 -m pip install rtmlib onnxruntime opencv-python numpy
python3 scripts/track_pose_rtmpose.py \
  --video source.mp4 --exercise deadlift --tracking bar-tracking.json \
  --output pose-tracking.json
```

RTMlib 首次构造轻量级 RTMPose Body 模型时，从 OpenMMLab 官方 URL 下载 detector 与 RTMPose ONNX，缓存于 `~/.cache/rtmlib/hub/checkpoints/`（或用户设定的 `XDG_CACHE_HOME` / `TORCH_HOME`）。输出 JSON 记录实际缓存模型的 SHA-256；模型不可提交到 Skill 或公开仓库。准确性不以“轻量”保证，仍必须通过下述基准门槛。

默认全程采样 15 帧/秒，并在已有杠铃 tracking 标出的起始、离地/触胸/底部、推起/上升和锁定附近 ±0.20 秒加密到 30 帧/秒。

## 可信门禁

- 只保存肩、肘、腕、髋、膝、踝的左右坐标和置信度；`confidence < 0.60` 即为不可用。
- 连续不可用超过 0.20 秒、关键阶段可用率低于 90%，或机位本来不能支持该判断时，`validate_pose_tracking.py` 返回不可用；不得从该姿态数据下结论或生成相应训练建议。
- 不插值、不人工补点、不猜测遮挡关节。仅允许在未来渲染前对连续高置信度点做视觉平滑，但结论只读取原始有效点。

## 机位边界

| 动作 | 可由姿态辅助的机位与内容 | 不使用姿态判定的机位 |
|---|---|---|
| 硬拉 | 侧面/斜侧面：肩—髋时序 | 后方只看杠铃两端高度与同步 |
| 深蹲 | 侧面/斜侧面：髋—膝—踝协同 | 后方只看杠铃两端高度与同步 |
| 卧推 | 侧面/斜侧面：肩—肘—腕配合 | 脚端只看两端高度与同步 |

## 基准测试

每种标准机位都必须有独立审核过的 `points` 参考 JSON：

```json
{"points":[{"frame":123,"joint":"left_hip","x":600,"y":520}]}
```

运行 `benchmark_pose_tracking.py`。该类别只有同时满足中位误差 ≤24px、90% 分位误差 ≤40px、关键点可用率 ≥90% 时，才可以将其姿态数据用于正式报告结论。未通过时仅继续使用现有杠铃/机位分析，并明确“当前机位无法判断”人体关节相关事项。
