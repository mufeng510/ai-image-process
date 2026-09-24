# AI Image Process

跨平台 AI 图片批量处理桌面客户端（Python / PySide6）。

当前版本：**0.2.0**（见 `app/version.py`）

## 功能

一条可配置的流水线按序处理图片，默认步骤：

| 步骤 | 说明 |
|------|------|
| 去重 | 按文件内容哈希（MD5 / SHA-1 / SHA-256）去重，重复文件仅保留第一张 |
| 清理 AI Metadata | 移除生成式 AI 痕迹元数据（可选依赖 [remove-ai-watermarks](https://github.com/wiltodelta/remove-ai-watermarks)） |
| 去除可见水印 | 移除 AI 生成角标（Gemini / 豆包 / 即梦等），后端：`auto` / `cv2` / `migan` / `lama` |
| 重编码 | JPEG 质量区间重编码，可嵌入 sRGB ICC 配置 |
| 写入设备 Metadata | 随机或固定机型 EXIF（内置 28 款 iPhone 机型库），随机化拍摄时间与 Software 标签 |
| 重命名 | 模板化命名（预设或自定义模板，支持日期/时间/序号变量） |
| 输出写入 | 冲突策略：自动重命名 / 跳过 / 覆盖；可保留原图 |

其他能力：

- 拖拽/批量选择图片与文件夹，后台线程处理，进度 / 日志 / 取消
- 版本化配置（导入 / 导出 / 重置），便携模式
- 内置 ExifTool（`Tools/exiftool/`），不依赖用户 PATH
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
--json-summary         输出任务摘要 JSON
--version              显示版本
```

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
  gui/           PySide6 主界面、设置、后台 worker
  config/        版本化配置 schema 与路径
  platform/      平台相关（Windows 静默子进程等）
assets/          设备机型库、ICC 配置
Tools/exiftool/  随仓库附带的 ExifTool
build/           PyInstaller spec 与打包说明
scripts/         本地构建脚本
tests/           pytest（core / config / gui）
```

## 计划

完整方案见 [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md)。

## 许可证

MIT
