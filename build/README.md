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

Release artifacts (on tag `v*`):

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

- Triggers: push tag `v*`, or `workflow_dispatch` (build artifacts only; Release publish is tag-only)
- Runners: `windows-latest`, `macos-latest`, `ubuntu-latest` (official hosted only)
- Jobs: `package-windows`, `package-linux`, `package-macos` (all blocking) → `publish-release` (tags only)

Create a release:

```bash
git tag v0.1.0
git push origin v0.1.0
```

## Notes

- Prefer onedir over onefile for ExifTool/Qt reliability.
- Do not rely on user PATH for ExifTool/ImageMagick.
- Non-Windows ExifTool bundling is best-effort and must not fail packaging.
- `remove-ai-watermarks` is optional and can significantly increase size; enable deliberately.
- No Apple codesign/notarization in this pipeline.
