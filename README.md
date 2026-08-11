# AI Image Process

跨平台 AI 图片处理桌面客户端（重构中）。

## 现状

- **Phase 2**：Python 核心处理层 + CLI 已落地
- **Phase 4**：PySide6 GUI 主界面 / 设置 / 后台线程已落地
- 遗留 Windows 脚本仍保留在 `DoubaoProcessor/` 作为参考
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
- 处理步骤开关
- 后台线程处理、进度、日志、取消
- 设置（常规 / 处理 / 高级 / 关于）

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
- 触发：推送 tag `v*` → `.github/workflows/release.yml` 构建并上传到 GitHub Release

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
