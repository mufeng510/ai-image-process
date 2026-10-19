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
2. 打开 GUI → 选择输出目录 → **导入 iPhone**（仅 GUI，CLI 无此功能）。
   这一步只会唤起爱思助手并显示指引，**不会复制或修改任何文件**：
   按指引操作（我的设备 → 照片 → 相机胶卷 → 导入实况照片 → 批量导入，
   选择本次任务的结果目录——里面已经是同名 `x.jpg` + `x.mov` 配对；
   手机端打开照片处理工具确认）。
3. 在 iPhone 照片中确认：
   - [ ] 显示为**一张** Live Photo（左上角 LIVE 标记）
   - [ ] 长按可以播放动态
   - [ ] 没有分裂成两个独立媒体（1 张照片 + 1 个视频 = 失败）

## 4. 验证矩阵（维护者填写）

| 日期 | iPhone 机型 | iOS | Windows | Apple Devices | 本项目版本 | 本地动态 | AI 视频 | 结果 |
|------|-------------|-----|---------|---------------|------------|----------|---------|------|
| 2026-10-19 | iPhone 15 | 27.0.1 | 爱思助手 (Windows) | 未使用 | 0.5.0 | **通过** | 未验证 | 导入成功，照片显示为一张 Live Photo |

当前状态：**Stage 1 已自动化；Stage 2 本地动态模式已在真实设备上验证通过**（2026-10-19，
iPhone 15 / iOS 27.0.1，经爱思助手「导入实况照片」导入后在手机上显示为单张 Live Photo）。
AI 视频模式仍未在真实设备上验证。

> 该次验证是在 Windows 侧的**爱思助手**上完成的，没有用到 Apple Devices；
> iCloud 照片开启时 Apple Devices 的同步不可用（见 `i4tools.py` 的研究结论）。
> 导入仍需用户在爱思助手里手动选择目录并按提示操作，本项目不提供自动导入。

### 定位过程（值得记住的一条）

前几次验证一直失败，症状是「爱思助手报错或直接跳过」，产物与真机导出的其余部分
逐字节对齐后仍然如此。用 2×2 对照实测才定位到：**爱思助手对扩展名做区分大小写的
检查**，小写 `x.jpg` + `x.mov` 会在扫描阶段被跳过，根本没走到配对；大写 `x.JPG` +
`x.MOV` 才被接受。音频轨格式（AAC 立体声 / PCM 单声道）在此不影响结果。

所以产物扩展名由 `output_format.OUTPUT_JPG_EXT` / `OUTPUT_MOV_EXT` 统一决定，
**必须是大写**；`tests/core/test_output_naming.py` 把这条钉死。

## 5. 实现说明（供排查）

- **产物扩展名必须大写**：`.JPG` + `.MOV`。爱思助手对扩展名做区分大小写的检查，
  小写会在扫描阶段被直接跳过。这是爱思助手导入失败的**首要**排查项——
  其余部分逐字节对齐仍失败时，先看文件名。
- Content Identifier：每次构建新生成 UUID（`metadata.new_asset_identifier`），
  写入照片 EXIF/ImageUniqueID 系标签 + MOV `content.identifier`；
  模板 UUID 永不复用。
- `still-image-time`：MOV 内一条 mebx 定时元数据轨，样本为
  `[size=9][localID=1][0xFF]`，与真机导出**逐字节相同**（值恒为 -1，
  静帧时刻由样本自身时间戳 0 表达）。
- MOV 结构对齐真机（参考文件：爱思助手从 iPhone 15 导出的一对）：
  - 顶层 box 顺序 `ftyp → mdat → moov`。`normalize_movie` 本就按此输出，
    但 `patch_mov_with_livephoto_tags` 里 ExifTool 会重写整个 MOV 并把 moov
    挪到 mdat 前面，`moov_order.move_moov_after_mdat` 负责改回来——这样后续
    拼接定时轨才真正走得到「无需改 stco」的那条路径（与设计意图一致）。
  - `moov/meta` 除 `content.identifier` 外还写
    `live-photo.auto=1`、`full-frame-rate-playback-intent=1`，
    以及从静态图回读的 `make` / `model` / `software` / `creationdate`。
  - QuickTime 电影头的 `CreateDate` / `ModifyDate` 取自静态图的
    `DateTimeOriginal`，不再是 `0000:00:00`。
- 有意**不**对齐的部分：真机另有 `location.ISO6709`、
  `live-photo.vitality-score`、`video-orientation` 与 `live-photo-info`
  两条 mebx 轨，JPEG 的 MakerNote 也带 51 项相机遥测（真机 1699 字节，
  本项目 1 项 70 字节）。这些全部来自拍摄管线的传感器数据，伪造它们
  只会让文件「像真的」而不会更对，且写错的风险高于收益——配对只依赖
  ContentIdentifier 与 still-image-time，两者已与真机一致。
- 本地动态：ffmpeg `zoompan` 轻微推镜（默认强度 0.06，3 秒，H.264/yuv420p/MOV，
  无音频，长边 ≤ 1920 不改变宽高比）。
