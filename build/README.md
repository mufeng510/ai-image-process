# Packaging

## Goal

Cross-platform **onedir portable** distribution built on official GitHub-hosted runners, plus a Windows Inno Setup installer.

```text
dist/AI-Image-Process/
  AI-Image-Process(.exe)   # platform binary
  assets/...
  Tools/exiftool/...       # Windows when bundled
  LICENSE
  README.md
  BUILD_INFO.txt
```

Release artifacts (on tag `v*` or each `main` push):

- `AI-Image-Process-windows-x64-portable.zip`
- `AI-Image-Process-windows-x64-setup.exe` (Inno Setup)
- `AI-Image-Process-macos-<arch>-portable.zip` (arch from runner, often `arm64`)
- `AI-Image-Process-linux-x64-portable.zip`

All three OS package jobs are **release-blocking**. Artifacts are **unsigned**; macOS Gatekeeper and Windows SmartScreen may warn.

## Local builds

### Windows portable

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
./scripts/build_windows.ps1
```

### Windows installer (after portable)

Install [Inno Setup 6](https://jrsoftware.org/isinfo.php), then:

```powershell
./scripts/build_windows_installer.ps1
# or: $env:ISCC_PATH = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
```

### Linux / macOS portable

```bash
python3 -m venv .venv
source .venv/bin/activate
bash scripts/build_portable.sh
```

## GitHub Actions release

Workflow: `.github/workflows/release.yml`

- Triggers: push to `main` (auto prerelease `v<version>-build.<run_number>`), push tag `v*` (stable release), or `workflow_dispatch`
- Runners: `windows-latest`, `macos-latest`, `ubuntu-latest` (official hosted only)
- Jobs: `package-windows`, `package-linux`, `package-macos` (all blocking) → `publish-release`
- Branch-push builds publish as **prerelease** and never take over the "Latest" stable release; tag builds publish as full releases

Create a release:

```bash
git tag v0.1.0
git push origin v0.1.0
```

## Notes

- Prefer onedir over onefile for ExifTool/Qt reliability.
- Do not rely on user PATH for ExifTool/ImageMagick.
- Non-Windows ExifTool bundling is best-effort and must not fail packaging.
- `remove-ai-watermarks` is optional and not bundled; end users install it from
  within the app (Settings → Processing) via the built-in **pure-Python wheel
  installer** (no system pip / no bundled pip required in frozen builds).
- No Apple codesign/notarization in this pipeline.

## FFmpeg（Live Photo 本地动态所需）

- 运行时解析顺序：`Tools/ffmpeg/`（随包）→ 用户 PATH；找不到时仅 Live Photo
  在 Preflight 报错，普通图片处理不受影响。
- 打包前请自行将已确认许可证的构建放入 `Tools/ffmpeg/`（`ffmpeg` + `ffprobe`）：
  - 检查构建版本许可证（GPL/LGPL 区分）、H.264 encoder（x264/openh264）组件许可，
    确认与本项目 MIT 发行方式兼容后再发布；
  - 记录来源/版本/许可证到发布说明，保证 release 构建可重复或版本锁定；
  - 不要提交无法确定许可的第三方二进制进仓库。
- AI 视频模式不需要 FFmpeg 额外编解码器之外的依赖；下载的 AI 视频统一经
  `MovieNormalizer` 转为 MOV/H.264/yuv420p/无音频标准形态。
