# HOMO Sport Space｜三大项动作复盘 Skill

面向深蹲、卧推与硬拉视频的二维动作复盘 Skill。它生成面向新手与健身爱好者的中文街机风知识卡，并将“视频证据 → 保守判断 → 训练方向 → 可执行练习”串成闭环。

## 能力

- 自动识别侧面、斜侧面、前方、后方、卧推脚端与头端机位。
- 以源视频 SHA-256 将视频、抽帧目录、tracking 与卡片页面唯一绑定；双机位参数写反时自动修正，无法唯一匹配时直接停止渲染。
- 按动作与机位分别判断：杠铃路径、起拉/推起时序、触胸/底部稳定及左右端同步。
- 输出 4 张 `1080×1440` 中文街机知识卡：机位一、机位二、相关肌群、一次训练计划。
- 所有肌肉索引使用内置像素人体与精确肌腹安全区校验，不使用泛化色块。
- 可选 RTMPose 内部姿态追踪：官方模型首次下载到本机缓存，以置信度门禁辅助关键帧与时序判断；不在卡片叠加骨架，也不会单独给动作打分。

## 使用

将本目录安装到 Codex 的 skills 目录后，在对话中引用：

```text
[$analyze-powerlifting-video](SKILL.md) 分析我的深蹲双机位视频
```

双机位视频的预检示例：

```bash
swift scripts/extract_video_frames.swift side.mp4 side-frames
python3 scripts/create_frame_manifest.py --video side.mp4 --frames-dir side-frames --exercise squat
```

完整流程、tracking 格式、机位约束、隐私处理和渲染规则见 [SKILL.md](SKILL.md)。

## 限制

这是一套二维屏幕视频复盘工具，不是三维动作捕捉、医疗诊断或肌力诊断。出现尖锐疼痛、麻木、放射痛或力量骤降时，应停止重负荷训练并寻求专业评估。

## 验证

```bash
python3 scripts/test_camera_binding.py
python3 scripts/test_camera_view_detection.py
python3 scripts/test_pose_gates.py
python3 scripts/test_pose_benchmark.py
```

## License

MIT
