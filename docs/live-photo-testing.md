# Live Photo 测试手册（Stage 1 本地 / Stage 2 Apple 生态）

> 原则：Windows 单元测试**不能**证明 Apple Photos 兼容。只有真实设备验证才算“支持”；
> 其余一律标记为“理论支持 / 未验证”。

## 1. 参考样本准备（真实 iPhone Live Photo）

1. 用 iPhone 拍摄一张 Live Photo（设置 → 相机 → Live Photo 开启）。
2. 通过数据线 + Apple Devices（Windows）或 macOS 访达导出**原文件**：
   - `IMG_XXXX.jpg`（静态图）
   - `IMG_XXXX.mov`（配对视频）
3. 将样本放到**仓库外**的目录（不要提交个人照片进 Git），例如：
   - `E:\lp-reference\IMG_0001.jpg`
   - `E:\lp-reference\IMG_0001.mov`
4. 用以下命令查看参考结构（需要 ExifTool / ffprobe）：
   ```powershell
   Tools\exiftool\exiftool.exe -G -s IMG_0001.jpg | Select-String "Identifier|Unique"
   Tools\exiftool\exiftool.exe -G -s IMG_0001.mov | Select-String "Identifier|StillImage"
   ffprobe -v error -show_entries stream=width,height,codec_name -show_entries format=duration -of default=noprint_wrappers=1 IMG_0001.mov
   ```

## 2. Stage 1：本地文件验证（自动化）

每个 Live Photo 构建后自动执行 `LivePhotoValidator`：

- Photo：文件存在、可解码、Asset Identifier 存在
- Movie：可解析、有 video track、`content.identifier` 存在、`still-image-time` 存在
- Pair：`photo identifier == movie identifier`
- Movie：`duration > 0`、尺寸 `> 0`、宽高比与静态图一致（Δ < 0.05）

手动运行：

```powershell
python -m pytest tests/core/test_live_photo.py -q            # 单元（含 mock provider）
python -m pytest tests/integration/live_photo -q -m "manual" # 真实样本（需 AIP_LP_REF_DIR）
```

真实样本校验脚本：

```powershell
$env:AIP_LP_REF_DIR="E:\lp-reference"
python -m pytest tests/integration/live_photo -q
```

## 3. Stage 2：Apple 生态实际验证（手工）

1. 用本项目生成一对 Live Photo（本地动态模式即可）：
   ```powershell
   python -m app <输入> -o E:\lp-out --enable-live-photo --json-summary
   ```
2. 打开 GUI → 选择输出目录 → **导入 iPhone**（或 CLI `--prepare-iphone-import E:\lp-sync`），
   优先按爱思助手实况导入指引操作（我的设备 → 照片 → 相机胶卷 → 导入实况照片 → 批量导入，
   选择同步目录；JPG 与 MOV 同名配对，手机端打开照片处理工具确认）；
   无爱思助手时才回退 Apple Devices 文件夹同步。
3. 在 iPhone 照片中确认：
   - [ ] 显示为**一张** Live Photo（左上角 LIVE 标记）
   - [ ] 长按可以播放动态
   - [ ] 没有分裂成两个独立媒体（1 张照片 + 1 个视频 = 失败）

## 4. 验证矩阵（维护者填写）

| 日期 | iPhone 机型 | iOS | Windows | Apple Devices | 本项目版本 | 本地动态 | AI 视频 | 结果 |
|------|-------------|-----|---------|---------------|------------|----------|---------|------|
| —    | —           | —   | —       | —             | —          | 未验证   | 未验证  | —    |

当前状态：**Stage 1 已自动化；Stage 2 尚未在真实设备上验证**。
在矩阵填写之前，README 与 GUI 中的 iPhone 导入能力一律显示为“需用户确认同步（未验证自动导入）”。

## 5. 实现说明（供排查）

- Content Identifier：每次构建新生成 UUID（`metadata.new_asset_identifier`），
  写入照片 EXIF/ImageUniqueID 系标签 + MOV `content.identifier`；
  模板 UUID 永不复用。
- `still-image-time`：写入 MOV（ExifTool QuickTime 键 + 追加的顶层 `uuid` box，
  payload `{"content_identifier": …, "still_image_time_ms": 0}`，播放器可安全忽略）。
  当前 still 点为视频第 0 帧（即最终静态图本身），保证静态/动态首帧一致。
- 本地动态：ffmpeg `zoompan` 轻微推镜（默认强度 0.06，3 秒，H.264/yuv420p/MOV，
  无音频，长边 ≤ 1920 不改变宽高比）。
