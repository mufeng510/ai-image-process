# Copy reference Windows ExifTool into the packaging location Tools/exiftool
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$src = Join-Path $Root "DoubaoProcessor\Tools\exiftool-13.59_64"
$dest = Join-Path $Root "Tools\exiftool"
if (-not (Test-Path $src)) { throw "Missing $src" }
New-Item -ItemType Directory -Force -Path $dest | Out-Null
Copy-Item -Recurse -Force (Join-Path $src "*") $dest
Write-Host "Prepared $dest"
