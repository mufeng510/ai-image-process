# Build Windows Inno Setup installer from dist\AI-Image-Process onedir.
# Requires portable build first (scripts/build_windows.ps1) and Inno Setup (ISCC.exe).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$onedir = Join-Path $Root "dist\AI-Image-Process"
$exe = Join-Path $onedir "AI-Image-Process.exe"
if (-not (Test-Path $exe)) {
  throw "[installer] missing $exe — run scripts/build_windows.ps1 first"
}

$iss = Join-Path $Root "build\installer\ai-image-process.iss"
if (-not (Test-Path $iss)) {
  throw "[installer] missing Inno script: $iss"
}

function Find-ISCC {
  $candidates = @(
    ${env:ISCC_PATH},
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe",
    "C:\Program Files (x86)\Inno Setup 5\ISCC.exe"
  ) | Where-Object { $_ -and $_.Trim() -ne "" }
  foreach ($c in $candidates) {
    if (Test-Path $c) { return $c }
  }
  $cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  return $null
}

$iscc = Find-ISCC
if (-not $iscc) {
  throw "[installer] ISCC.exe not found. Install Inno Setup 6 or set ISCC_PATH."
}

Write-Host "[installer] using ISCC: $iscc"
& $iscc $iss
if ($LASTEXITCODE -ne 0) {
  throw "[installer] ISCC failed with exit code $LASTEXITCODE"
}

$setup = Join-Path $Root "dist\AI-Image-Process-windows-x64-setup.exe"
if (-not (Test-Path $setup)) {
  throw "[installer] expected output missing: $setup"
}
Write-Host "[installer] setup exe: $setup"
