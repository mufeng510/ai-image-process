#Requires -Version 5.1
<#
.SYNOPSIS
  Download a pinned FFmpeg Windows build into Tools/ffmpeg (gitignored binaries).

  Binaries are intentionally NOT committed to git (~80MB). Run this before
  local dev or packaging so app/core/ffmpeg_resolver finds the bundled copy.
  Version + license are recorded to Tools/ffmpeg/SOURCE.txt by this script.

  License notice: Gyan builds are GPL. Bundling them into a distributed
  installer has GPL obligations (notably a source offer). See build/README.md
  "FFmpeg" section before release; prefer an LGPL build if GPL is an issue.
#>
[CmdletBinding()]
param(
  [string]$Version = "9.0.2",
  [string]$Url = "",
  [string]$ExpectedSha256 = ""
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$dest = Join-Path $repo "Tools\ffmpeg"
New-Item -ItemType Directory -Path $dest -Force | Out-Null

if (-not $Url) {
  $Url = "https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-$Version-essentials_build.zip"
}
$zip = Join-Path ([IO.Path]::GetTempPath()) "ffmpeg-essentials-$Version.zip"
Write-Host "Downloading $Url ..."
Invoke-WebRequest -Uri $Url -OutFile $zip
if ($ExpectedSha256) {
  $actual = (Get-FileHash -Path $zip -Algorithm SHA256).Hash.ToLower()
  if ($actual -ne $ExpectedSha256.ToLower()) {
    throw "SHA256 mismatch: expected $ExpectedSha256, got $actual"
  }
  Write-Host "SHA256 verified."
} else {
  Write-Host "WARNING: no --ExpectedSha256 given; skipping checksum verification."
}
$tmp = Join-Path ([IO.Path]::GetTempPath()) ("ffmpeg-x-" + [Guid]::NewGuid().ToString("N"))
Expand-Archive -Path $zip -DestinationPath $tmp -Force
$inner = Get-ChildItem -Path $tmp -Directory | Select-Object -First 1
Copy-Item (Join-Path $inner.FullName "bin\ffmpeg.exe") (Join-Path $dest "ffmpeg.exe") -Force
Copy-Item (Join-Path $inner.FullName "bin\ffprobe.exe") (Join-Path $dest "ffprobe.exe") -Force
Remove-Item -Recurse -Force $tmp, $zip
$ver = (& (Join-Path $dest "ffmpeg.exe") -version | Select-Object -First 1)
@(
  "source: Gyan FFmpeg Windows essentials build ($Url)",
  "pinned_version: $Version",
  "ffmpeg_version_line: $ver",
  "license: GPL (see https://www.gyan.dev/ffmpeg/builds/ for build licenses; release obligations in build/README.md)",
  "fetched_utc: $([DateTime]::UtcNow.ToString('o'))"
) | Set-Content (Join-Path $dest "SOURCE.txt") -Encoding UTF8
Write-Host "Done: $dest (ffmpeg.exe + ffprobe.exe). Binaries are gitignored; SOURCE.txt is tracked."
