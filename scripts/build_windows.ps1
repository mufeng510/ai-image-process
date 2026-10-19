# Build Windows onedir portable package.
# Run in PowerShell from repo root with Python 3.10+ available.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$py = "python"
if (Test-Path ".venv\Scripts\python.exe") { $py = ".venv\Scripts\python.exe" }

& $py -m pip install -U pip wheel
& $py -m pip install -r requirements.txt pyinstaller

# ExifTool lives in-repo at Tools/exiftool and is bundled by the PyInstaller spec.
$dest = Join-Path $Root "Tools\exiftool\exiftool.exe"
if (-not (Test-Path $dest)) {
  Write-Host "[build] WARNING: Tools\exiftool\exiftool.exe missing; device metadata step will be limited"
}

# FFmpeg is required for Live Photo (headline feature): fetch the pinned
# binary before packaging. Fail fast instead of shipping without it.
& (Join-Path $Root "scripts\fetch_ffmpeg.ps1")
$ffmpeg = Join-Path $Root "Tools\ffmpeg\ffmpeg.exe"
if (-not (Test-Path $ffmpeg)) {
  throw "[build] Tools\ffmpeg\ffmpeg.exe missing after fetch; refusing to package without FFmpeg"
}
Write-Host "[build] bundled FFmpeg: $ffmpeg"

if (Test-Path "dist\AI-Image-Process") { Remove-Item -Recurse -Force "dist\AI-Image-Process" }
if (Test-Path "build\pyinstaller") { Remove-Item -Recurse -Force "build\pyinstaller" }

& $py -m PyInstaller --noconfirm --clean --distpath dist --workpath build/pyinstaller build/ai-image-process.spec

Copy-Item -Force LICENSE dist\AI-Image-Process\ -ErrorAction SilentlyContinue
Copy-Item -Force README.md dist\AI-Image-Process\ -ErrorAction SilentlyContinue

# Ship the agent skill, mirroring scripts/build_portable.sh. Without this the
# Windows artifact is the only one whose CLI exists but that no agent can be
# taught to drive -- and the release assertions check all three platforms, so a
# gap here fails the build instead of shipping.
$agentSkill = Join-Path $Root ".opencode\skills\ai-image-process\SKILL.md"
if (Test-Path $agentSkill) {
  New-Item -ItemType Directory -Force -Path "dist\AI-Image-Process\.opencode\skills" | Out-Null
  Copy-Item -Recurse -Force (Split-Path -Parent $agentSkill) "dist\AI-Image-Process\.opencode\skills\"
  New-Item -ItemType Directory -Force -Path "dist\AI-Image-Process\docs" | Out-Null
  Copy-Item -Force "docs\agent-cli.md" "dist\AI-Image-Process\docs\"
  New-Item -ItemType Directory -Force -Path "dist\AI-Image-Process\scripts" | Out-Null
  Copy-Item -Force "scripts\install_agent_skill.sh" "dist\AI-Image-Process\scripts\"
  Write-Host "[build] bundled agent skill"
} else {
  Write-Host "[build] WARNING: .opencode\skills\ai-image-process\SKILL.md not found;" `
            "the artifact will ship without the agent skill"
}

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
