# AI Image Process

跨平台 AI 图片处理桌面客户端（重构中）。

## 现状

- **Phase 2**：Python 核心处理层 + CLI 已落地
- **Phase 4**：PySide6 GUI 主界面 / 设置 / 后台线程已落地
- 旧的 `DoubaoProcessor/` Windows 脚本已移除；ExifTool 随仓库置于 `Tools/exiftool/`
- 安装包与多平台发布仍在后续阶段

## 启动 GUI

```bash
python3 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install Pillow pytest PySide6-Essentials
# 或: .venv/bin/pip install -e ".[gui,dev]"

.venv/bin/python -m app gui
```

主界面支持：
- 拖拽/选择图片与文件夹
- 输出目录选择
- 处理步骤开关（清理 AI Metadata / 去除可见水印 / 重编码 / 设备 Metadata / 命名 / 输出）
- 后台线程处理、进度、日志、取消
- 设置（常规 / 处理 / 高级 / 关于）

## 去除可见水印（可选）

基于 [remove-ai-watermarks](https://github.com/wiltodelta/remove-ai-watermarks) 的 `visible` 模式，可去除 Gemini、豆包、即梦等已注册的可见 AI 标记：

```bash
.venv/bin/pip install "remove-ai-watermarks[visible]"
```

- 默认 `cv2` 后端无需模型；步骤默认关闭，在主界面或设置中启用
- 可选 `migan` / `lama` 神经网络修复后端需要下载模型权重：**软件不预置模型**，
  可在「设置 → 处理 → 去除可见水印」页面手动下载（缓存于本机 Hugging Face 缓存目录），
  也可依赖首次使用时自动下载

## 核心 CLI

```bash
.venv/bin/python -m app path/to/images -o ./output --no-provenance --seed 1 --json-summary
```

## 测试

```bash
.venv/bin/python -m pytest -q
# GUI 离屏冒烟（需要已安装 PySide6）
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/gui
```

## 版本

见 `app/version.py`（当前 `0.1.0`）。

## 计划

完整方案见 `IMPLEMENTATION_PLAN.md` 与 `.omx/plans/IMPLEMENTATION_PLAN.md`。

## 许可证

MIT

## 打包 / 发布

详见 `build/README.md`。

多平台官方 runner 自动打包（**全部 release-blocking**）：

- Windows：便携 ZIP + Inno Setup 安装包
- macOS / Linux：便携 ZIP（未签名）
- 触发：
  - 推送到 `main` → 自动构建并发布 **prerelease**（tag 形如 `v0.1.0-build.<运行号>`）
  - 推送 tag `v*` → 构建并发布正式 Release
- 工作流：`.github/workflows/release.yml`

本地：

```powershell
# Windows portable
./scripts/build_windows.ps1
# Windows installer (needs Inno Setup)
./scripts/build_windows_installer.ps1
```

```bash
# Linux / macOS portable
bash scripts/build_portable.sh
```

GitHub Actions：
- `.github/workflows/ci.yml` — 测试
- `.github/workflows/release.yml` — tag `v*` 在 windows/macOS/ubuntu 官方 runner 打包并发布 Release
