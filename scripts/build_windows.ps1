# Build Windows onedir portable package.
# Run in PowerShell from repo root with Python 3.10+ available.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$py = "python"
if (Test-Path ".venv\Scripts\python.exe") { $py = ".venv\Scripts\python.exe" }

& $py -m pip install -U pip wheel
& $py -m pip install -r requirements.txt pyinstaller "PySide6-Essentials>=6.6.0"

# Bundle ExifTool into Tools/exiftool if not present (Windows best-effort; non-blocking if missing)
$dest = Join-Path $Root "Tools\exiftool"
if (-not (Test-Path $dest)) {
  $src = Join-Path $Root "DoubaoProcessor\Tools\exiftool-13.59_64"
  if (Test-Path $src) {
    New-Item -ItemType Directory -Force -Path $dest | Out-Null
    Copy-Item -Recurse -Force (Join-Path $src "*") $dest
    Write-Host "[build] copied ExifTool from DoubaoProcessor reference tree"
  } else {
    Write-Host "[build] WARNING: no ExifTool tree found; device metadata step will be limited"
  }
}

if (Test-Path "dist\AI-Image-Process") { Remove-Item -Recurse -Force "dist\AI-Image-Process" }
if (Test-Path "build\pyinstaller") { Remove-Item -Recurse -Force "build\pyinstaller" }

& $py -m PyInstaller --noconfirm --clean --distpath dist --workpath build/pyinstaller build/ai-image-process.spec

Copy-Item -Force LICENSE dist\AI-Image-Process\ -ErrorAction SilentlyContinue
Copy-Item -Force README.md dist\AI-Image-Process\ -ErrorAction SilentlyContinue

$buildInfo = @"
AI Image Process portable build
platform: Windows
arch: x64
os_token: windows
arch_token: x64
generated_by: scripts/build_windows.ps1
note: Unsigned portable build. Windows SmartScreen may warn on first run.
"@
Set-Content -Path "dist\AI-Image-Process\BUILD_INFO.txt" -Value $buildInfo -Encoding UTF8

$zip = "dist\AI-Image-Process-windows-x64-portable.zip"
if (Test-Path $zip) { Remove-Item -Force $zip }
Compress-Archive -Path "dist\AI-Image-Process\*" -DestinationPath $zip
Write-Host "[build] portable zip: $zip"
