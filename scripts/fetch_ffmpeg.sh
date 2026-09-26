#!/usr/bin/env bash
# Fetch a pinned FFmpeg binary into Tools/ffmpeg (gitignored) for packaging.
# Default source: pinned imageio-ffmpeg wheel from PyPI (contains a static
# ffmpeg; no ffprobe — the app runs without ffprobe). Linux/macOS only;
# Windows uses scripts/fetch_ffmpeg.ps1.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PACKAGE_VERSION="${PACKAGE_VERSION:-0.6.0}"
PYTHON="${PYTHON:-python3}"
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON="$ROOT/.venv/bin/python"
fi

mkdir -p Tools/ffmpeg
TMPD="$(mktemp -d)"
trap 'rm -rf "$TMPD"' EXIT
"$PYTHON" -m pip download "imageio-ffmpeg==${PACKAGE_VERSION}" --no-deps -d "$TMPD"
WHL="$(ls "$TMPD"/*.whl | head -n 1)"
# Probe the wheel for the actual binary name (version-proof: v7.1 vs v7.0.2,
# aarch64 vs arm64 all vary by platform/release).
WHEEL_BIN="$("$PYTHON" - "$WHL" <<'PY'
import sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as zf:
    cands = [n for n in zf.namelist()
             if "/binaries/ffmpeg-" in n and not n.endswith("/")]
    assert len(cands) == 1, cands
    print(cands[0].rsplit("/", 1)[-1])
PY
)"
"$PYTHON" - "$WHL" "$WHEEL_BIN" <<'PY'
import sys, zipfile
whl, member = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(whl) as zf:
    with zf.open("imageio_ffmpeg/binaries/" + member) as src, open("Tools/ffmpeg/ffmpeg", "wb") as dst:
        dst.write(src.read())
PY
chmod +x Tools/ffmpeg/ffmpeg
VER="$(./Tools/ffmpeg/ffmpeg -version 2>/dev/null | head -n 1)"
cat > Tools/ffmpeg/SOURCE.txt <<INFO
source: PyPI imageio-ffmpeg==${PACKAGE_VERSION} (${WHL##*/} -> imageio_ffmpeg/binaries/${WHEEL_BIN})
ffmpeg_version_line: ${VER}
ffprobe: not bundled by this source; app runs without ffprobe (validator BMFF fallback), prefers PATH ffprobe when present
license: GPL static build (--enable-gpl). Release obligations in build/README.md.
fetched_utc: $(date -u +%FT%TZ)
INFO
echo "[ffmpeg] done: Tools/ffmpeg/ffmpeg (${VER})"
