#!/usr/bin/env bash
# Build onedir portable folder + platform archive with PyInstaller (current platform).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON="$ROOT/.venv/bin/python"
fi

echo "[build] python=$PYTHON"
"$PYTHON" -m pip install -U pip wheel
"$PYTHON" -m pip install -r requirements.txt pyinstaller
# GUI extra
"$PYTHON" -m pip install "PySide6-Essentials>=6.6.0" || "$PYTHON" -m pip install "PySide6>=6.6.0"

# Optional provenance package (can bloat; leave commented by default)
# "$PYTHON" -m pip install "remove-ai-watermarks>=0.26.0"

# FFmpeg is required for Live Photo: fetch the pinned binary before
# packaging. Fail fast instead of shipping without it.
bash "$ROOT/scripts/fetch_ffmpeg.sh"
test -x "$ROOT/Tools/ffmpeg/ffmpeg" || {
  echo "[build] Tools/ffmpeg/ffmpeg missing after fetch; refusing to package without FFmpeg" >&2
  exit 1
}

rm -rf build/pyinstaller dist/AI-Image-Process
"$PYTHON" -m PyInstaller --noconfirm --clean --distpath dist --workpath build/pyinstaller \
  build/ai-image-process.spec

# Copy licenses / notices
mkdir -p dist/AI-Image-Process
cp -f LICENSE dist/AI-Image-Process/ 2>/dev/null || true
cp -f README.md dist/AI-Image-Process/ 2>/dev/null || true

# Detect os/arch for artifact naming (runner-default only; no extra matrix)
uname_s="$(uname -s || echo unknown)"
uname_m="$(uname -m || echo unknown)"
case "${uname_s}" in
  Linux*) os_token="linux" ;;
  Darwin*) os_token="macos" ;;
  MINGW*|MSYS*|CYGWIN*|Windows*) os_token="windows" ;;
  *) os_token="$(echo "${uname_s}" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9')" ;;
esac
case "${uname_m}" in
  x86_64|amd64) arch_token="x64" ;;
  aarch64|arm64) arch_token="arm64" ;;
  i386|i686|x86) arch_token="x86" ;;
  *) arch_token="$(echo "${uname_m}" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9')" ;;
esac

# Platform note file
cat > dist/AI-Image-Process/BUILD_INFO.txt <<INFO
AI Image Process portable build
platform: ${uname_s}
arch: ${uname_m}
os_token: ${os_token}
arch_token: ${arch_token}
generated_by: scripts/build_portable.sh
note: Unsigned portable build. macOS Gatekeeper / Windows SmartScreen may warn.
note: Windows release CI may bundle Tools/exiftool; non-Windows ExifTool is best-effort.
INFO

archive="dist/AI-Image-Process-${os_token}-${arch_token}-portable.zip"
rm -f "${archive}"
# zip from inside folder so archive root contains app files
(
  cd dist
  if command -v zip >/dev/null 2>&1; then
    zip -r -q "$(basename "${archive}")" AI-Image-Process
  else
    python3 - <<PY
import pathlib, zipfile
root = pathlib.Path("AI-Image-Process")
out = pathlib.Path("$(basename "${archive}")")
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
    for path in root.rglob("*"):
        if path.is_file():
            zf.write(path, path.as_posix())
print(f"[build] wrote {out}")
PY
  fi
)

echo "[build] done: dist/AI-Image-Process"
echo "[build] archive: ${archive}"
