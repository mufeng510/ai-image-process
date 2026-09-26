# AI Image Process

跨平台 AI 图片批量处理桌面客户端（Python / PySide6）。

当前版本：**0.2.0**（见 `app/version.py`）

## 功能

一条可配置的流水线按序处理图片，默认步骤（顺序固定，每步可独立开关）：

| 顺序 | 步骤 | 说明 |
|------|------|------|
| 1 | 去重 | 按文件内容哈希（MD5 / SHA-1 / SHA-256）去重，重复文件仅保留第一张 |
| 2 | 文件命名 | 模板化命名（预设或自定义模板，支持日期/时间/序号变量）；去重后立即确定 basename，后续 JPG/MOV 共享 |
| 3 | 清理 AI Metadata | 移除生成式 AI 痕迹元数据（可选依赖 [remove-ai-watermarks](https://github.com/wiltodelta/remove-ai-watermarks)） |
| 4 | 去除可见水印 | 移除 AI 生成角标（Gemini / 豆包 / 即梦等），后端：`auto` / `cv2` / `migan` / `lama` |
| 5 | 图片重编码 | JPEG 质量区间重编码，可嵌入 sRGB ICC 配置 |
| 6 | 写入设备 Metadata | 随机或固定机型 EXIF（内置 28 款 iPhone 机型库），随机化拍摄时间与 Software 标签；隐藏图片启用且有真实拍摄参数时可作为来源（缺字段回退原逻辑，GPS/UUID 永不继承） |
| 7 | 图片旋转与裁剪 | 每张图独立随机角度（默认 −2° ~ +2°），保持原宽高比的最大内接裁剪，无黑边不变形（默认关闭） |
| 8 | 隐藏图片 | 真实拍摄照片素材池 cover 覆盖合成（默认不透明度 2%）；数量不足时**禁止开始任务**，成功后**永久删除**对应素材（默认关闭） |
| 9 | 生成 Apple Live Photo | 最终静态图 + MOV（本地轻微动态 / AI Image-to-Video），统一 Content Identifier + still-image-time，Stage-1 本地校验通过才提交（默认关闭） |
| 10 | 输出处理结果 | 冲突策略：自动重命名 / 跳过 / 覆盖；Live Photo JPG+MOV 作为整体 Bundle 原子提交 |

任务开始前统一执行 Preflight 预检查（输入集合 → 去重后数量 → 隐藏图库数量/路径安全/分配 → Live Photo 资源检查），
失败时不产生任何输出、不删除任何隐藏图片，GUI 弹窗 / CLI 返回结构化错误。

其他能力：

- 拖拽/批量选择图片与文件夹，后台线程处理，进度 / 日志 / 取消
- 版本化配置（导入 / 导出 / 重置），便携模式（配置 v2，老配置自动迁移，新功能默认关闭）
- 内置 ExifTool（`Tools/exiftool/`），不依赖用户 PATH；Live Photo 本地动态需要 FFmpeg（按 `Tools/ffmpeg/` → PATH 顺序解析，未找到时仅禁用 Live Photo，不影响普通处理）
- iPhone 导入：独立工具（非 Pipeline 步骤），主界面「导入 iPhone…」按钮或 CLI `--prepare-iphone-import`；通过**爱思助手实况导入**（准备 JPG+MOV 同名配对目录，指引用户在爱思助手中批量导入并在手机端确认），无自动导入
- 冻结版（安装包/便携包）内置 **纯 Python wheel 安装器**，无需本机 pip 即可在线安装可选依赖

## 下载安装

从 [Releases](https://github.com/mufeng510/ai-image-process/releases) 下载：

| 平台 | 产物 |
|------|------|
| Windows | `AI-Image-Process-windows-x64-setup.exe`（Inno Setup 安装包）、`…-portable.zip`（便携） |
| macOS | `AI-Image-Process-macos-arm64-portable.zip` |
| Linux | `AI-Image-Process-linux-x64-portable.zip` |

产物未签名：Windows 可能弹 SmartScreen，macOS 可能弹 Gatekeeper，属预期行为。

## 从源码运行

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[gui,dev]"

# GUI
.venv/bin/python -m app gui

# CLI
.venv/bin/python -m app path/to/images -o ./output --no-provenance --seed 1 --json-summary
```

CLI 主要参数：

```text
inputs                 输入文件和/或文件夹（必填，多个）
-o, --output           输出目录（必填）
--config               可选配置 JSON 路径
--seed                 RNG 种子（机型/质量随机可复现）
--no-provenance        关闭「清理 AI Metadata」步骤
--enable-rotate-crop   启用旋转裁剪（可配 --min-angle/--max-angle）
--hidden-library DIR   启用隐藏图片并指定素材库（可配 --hidden-opacity）
--enable-live-photo    启用 Live Photo（可配 --video-source local_motion|ai_video）
--list-steps           按顺序列出 Registry 步骤
--prepare-iphone-import DIR  从本次输出准备 iPhone 同步目录并打印引导步骤
--json-summary         输出任务摘要 JSON（含 preflight_failed/preflight_error）
--version              显示版本
```

版本来源：`app/version.py` 为唯一真实来源（当前 **0.2.0**），`pyproject.toml` 已对齐；
请勿以 README 缓存版本为准。

## GUI

```bash
.venv/bin/python -m app gui
```

- 主界面：拖拽区、输出目录、步骤开关、后台处理进度与日志
- 设置：常规 / 处理 / 高级 / 关于（配置导入导出、依赖安装、模型下载）

## 可选依赖（remove-ai-watermarks）

「清理 AI Metadata」与「去除可见水印」基于 remove-ai-watermarks，**默认不打包**：

- **软件内安装（推荐）**：「设置 → 处理」中对应功能旁的 **安装依赖** 按钮
  - 清理 Metadata：基础包
  - 去除可见水印：`[visible]` extra（含 cv2 后端）
  - migan/lama 支持：`[migan]` extra（onnxruntime + 模型下载）
  - 安装到用户可写目录并注入 `sys.path`，**无需重启**
- 源码运行时也可手动：`.venv/bin/pip install "remove-ai-watermarks[visible]"`
- 默认 `cv2` 后端无需模型；`migan` / `lama` 模型权重不预置，可在设置页手动下载或首次使用时自动拉取（缓存于本机 Hugging Face 缓存目录）

## 设备机型库

`assets/devices/phones.json` 内置 **28 款 iPhone**（iPhone 11 ~ 17 全系、iPhone Air、iPhone SE 3），供「写入设备 Metadata」步骤随机或固定选用；`make` / `model` / `lens` 写入 EXIF。可直接编辑该 JSON 扩展机型（`id` 需唯一）。

## 测试

```bash
.venv/bin/python -m pytest -q

# GUI 离屏冒烟（需已安装 PySide6）
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/gui
```

## 打包 / 发布

详见 [`build/README.md`](build/README.md)。GitHub Actions 全平台 release-blocking：

- 推送到 `main` → 自动构建并发布 **prerelease**（tag 形如 `v0.2.0-build.<运行号>`）
- 推送 tag `v*` → 构建并发布**正式 Release**
- 工作流：`.github/workflows/release.yml`（Windows / macOS / Ubuntu）；测试：`.github/workflows/ci.yml`

本地打包：

```powershell
# Windows 便携包 / 安装包（后者需 Inno Setup）
./scripts/build_windows.ps1
./scripts/build_windows_installer.ps1
```

```bash
# Linux / macOS 便携包
bash scripts/build_portable.sh
```

## 项目结构

```text
app/
  core/          流水线、步骤实现、设备库、wheel 安装器、ExifTool 封装
    live_photo/  LivePhotoBuilder/Validator/MovieNormalizer/providers（local_motion/ai_video）
    iphone_import/  爱思助手实况导入（i4tools 后端；JPG+MOV 同名配对目录）
  gui/           PySide6 主界面、设置、后台 worker
  config/        版本化配置 schema 与路径（当前 v2）
  platform/      平台相关（Windows 静默子进程等）
assets/          设备机型库、ICC 配置
Tools/exiftool/  随仓库附带的 ExifTool
Tools/ffmpeg/    可选：自行放置 ffmpeg/ffprobe（注意许可证，见 build/README.md）
build/           PyInstaller spec 与打包说明
scripts/         本地构建脚本
tests/           pytest（core / config / gui / integration/live_photo）
docs/            live-photo-testing.md（Stage-1/Stage-2 验证手册）
```

## 计划

完整方案见 [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md)；
Live Photo / iPhone 导入验证状态见 [`docs/live-photo-testing.md`](docs/live-photo-testing.md)
（Stage-2 真实设备验证尚未完成，相关能力标记为“未验证”）。

## 许可证

MIT
