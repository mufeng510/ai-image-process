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
# GUI extra (upper bound mirrors requirements.txt: 6.12.0 crashes at shutdown)
"$PYTHON" -m pip install "PySide6-Essentials>=6.6.0,<6.12" || "$PYTHON" -m pip install "PySide6>=6.6.0,<6.12"

# Optional provenance package (can bloat; leave commented by default)
# "$PYTHON" -m pip install "remove-ai-watermarks>=0.26.0"

# FFmpeg is required for Live Photo: fetch the pinned binary before
# packaging. Fail fast instead of shipping without it.
bash "$ROOT/scripts/fetch_ffmpeg.sh"
test -x "$ROOT/Tools/ffmpeg/ffmpeg" || {
  echo "[build] Tools/ffmpeg/ffmpeg missing after fetch; refusing to package without FFmpeg" >&2
  exit 1
}

# ExifTool is required for device EXIF and Live Photo pairing. On unix the
# repo only ships the Windows distribution, so fetch the native one -- and,
# because that distribution is a perl script, the interpreter too: a host
# without perl would otherwise pass every ExifTool probe we run at build time
# and then fail at the user's machine with "asset identifier missing".
if [[ "$(uname -s)" != MINGW* && "$(uname -s)" != MSYS* && "$(uname -s)" != CYGWIN* && "$(uname -s)" != Windows* ]]; then
  bash "$ROOT/scripts/fetch_perl.sh"
  test -x "$ROOT/Tools/perl/bin/perl" || {
    echo "[build] Tools/perl/bin/perl missing after fetch; refusing to package without a bundled interpreter" >&2
    exit 1
  }
  bash "$ROOT/scripts/fetch_exiftool.sh"
  test -x "$ROOT/Tools/exiftool/exiftool" || {
    echo "[build] Tools/exiftool/exiftool missing after fetch; refusing to package without ExifTool" >&2
    exit 1
  }
  # The wrapper prefers Tools/perl/bin/perl; prove that path end to end before
  # shipping, with nothing on PATH to fall back to.
  if ! env -i PATH=/nonexistent "$ROOT/Tools/exiftool/exiftool" -ver >/dev/null 2>&1; then
    echo "[build] bundled ExifTool cannot run with an empty PATH; perl is not really bundled" >&2
    exit 1
  fi
fi

rm -rf build/pyinstaller dist/AI-Image-Process
"$PYTHON" -m PyInstaller --noconfirm --clean --distpath dist --workpath build/pyinstaller \
  build/ai-image-process.spec

# Copy licenses / notices
mkdir -p dist/AI-Image-Process
cp -f LICENSE dist/AI-Image-Process/ 2>/dev/null || true
cp -f README.md dist/AI-Image-Process/ 2>/dev/null || true

# Ship the agent skill with the artifact. A user who downloaded the zip has no
# repository, so without this the CLI is scriptable but the Agent-facing entry
# point exists only for people who cloned the project -- and the README we just
# copied tells them to run a script that would not be there.
#
# Layout mirrors the repo so the very same installer works from both places, and
# so opening OpenCode inside the unzipped bundle discovers the skill directly.
agent_skill_dir="$ROOT/.opencode/skills/ai-image-process"
if [ -f "$agent_skill_dir/SKILL.md" ]; then
  mkdir -p "$ROOT/dist/AI-Image-Process/.opencode/skills"
  cp -R "$agent_skill_dir" "$ROOT/dist/AI-Image-Process/.opencode/skills/"
  mkdir -p "$ROOT/dist/AI-Image-Process/docs" "$ROOT/dist/AI-Image-Process/scripts"
  cp -f "$ROOT/docs/agent-cli.md" "$ROOT/dist/AI-Image-Process/docs/" 2>/dev/null || true
  cp -f "$ROOT/scripts/install_agent_skill.sh" "$ROOT/dist/AI-Image-Process/scripts/"
  chmod +x "$ROOT/dist/AI-Image-Process/scripts/install_agent_skill.sh" 2>/dev/null || true
else
  echo "[build] WARNING: .opencode/skills/ai-image-process/SKILL.md not found;" >&2
  echo "[build]          the portable artifact will ship without the agent skill" >&2
fi

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
note: ExifTool and FFmpeg are bundled; on unix ExifTool is a perl script, so a
note: self-contained perl ships alongside it (Tools/perl) and Tools/exiftool/exiftool is a
note: wrapper that prefers it. No host perl required.
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
