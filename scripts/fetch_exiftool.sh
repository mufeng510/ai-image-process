#!/usr/bin/env bash
# Fetch a native (unix) ExifTool into Tools/exiftool/ so a portable build is
# self-contained: without it, device EXIF silently writes nothing and every
# Live Photo fails Stage-1 validation with "photo asset identifier missing".
#
# Source: the official ExifTool GitHub mirror (same 13.x line as the Windows
# copy in Tools/exiftool/exiftool.exe). exiftool.org redirects downloads to
# SourceForge, which is not reachable from every build network; the GitHub
# codeload endpoint is, and the tarball is byte-identical in content.
#
# Layout produced (matches what exiftool expects at runtime):
#   Tools/exiftool/exiftool      (perl script, +x)
#   Tools/exiftool/lib/          (perl modules the script loads)
# Binaries are gitignored; SOURCE.txt (tracked) records what was fetched.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON="$ROOT/.venv/bin/python"
fi

EXIFTOOL_VERSION="${EXIFTOOL_VERSION:-13.59}"
EXIFTOOL_SHA256="${EXIFTOOL_SHA256:-87d3317882fdae9cb4dcfe57a96a378d0132ffc02c731315bf128b19ddcf7aac}"
DEST="$ROOT/Tools/exiftool"
URL="https://codeload.github.com/exiftool/exiftool/tar.gz/refs/tags/${EXIFTOOL_VERSION}"

if [ -x "$DEST/exiftool" ] && [ -d "$DEST/lib" ]; then
  echo "[fetch_exiftool] already present: $DEST/exiftool"
  exit 0
fi

command -v perl >/dev/null 2>&1 || {
  echo "[fetch_exiftool] perl is required to run ExifTool on unix" >&2
  exit 1
}

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

echo "[fetch_exiftool] downloading ExifTool ${EXIFTOOL_VERSION} ..."
curl -fsSL --retry 3 --connect-timeout 30 -o "$tmp/exiftool.tar.gz" "$URL" \
  || { echo "[fetch_exiftool] download failed: $URL" >&2; exit 1; }

if [ -n "$EXIFTOOL_SHA256" ]; then
  # Use the project's own interpreter (same convention as fetch_ffmpeg.sh):
  # stock macOS has shasum, not sha256sum.
  actual="$("$PYTHON" - "$tmp/exiftool.tar.gz" <<'PY'
import hashlib, sys
h = hashlib.sha256()
with open(sys.argv[1], "rb") as f:
    for chunk in iter(lambda: f.read(1 << 20), b""):
        h.update(chunk)
print(h.hexdigest())
PY
)"
  if [ "$actual" != "$EXIFTOOL_SHA256" ]; then
    echo "[fetch_exiftool] sha256 mismatch" >&2
    echo "  expected $EXIFTOOL_SHA256" >&2
    echo "  actual   $actual" >&2
    exit 1
  fi
  echo "[fetch_exiftool] sha256 ok"
fi

tar xzf "$tmp/exiftool.tar.gz" -C "$tmp"
srcdir="$tmp/exiftool-${EXIFTOOL_VERSION}"
[ -d "$srcdir" ] || { echo "[fetch_exiftool] unexpected archive layout" >&2; exit 1; }

mkdir -p "$DEST"
# The perl script loads modules from ./lib, so both must sit next to each other.
cp "$srcdir/exiftool" "$DEST/exiftool"
rm -rf "$DEST/lib"
cp -R "$srcdir/lib" "$DEST/lib"
chmod +x "$DEST/exiftool"

installed="$("$DEST/exiftool" -ver 2>/dev/null || true)"
# The codeload tarball is not guaranteed byte-stable across upstream gzip
# changes, so assert the version actually installed instead of trusting the
# sha256 pin alone.
if [ "$installed" != "$EXIFTOOL_VERSION" ]; then
  echo "[fetch_exiftool] installed version mismatch (perl missing, or lib/ incomplete)" >&2
  echo "  expected $EXIFTOOL_VERSION" >&2
  echo "  actual   ${installed:-<none>}" >&2
  exit 1
fi

cat > "$DEST/SOURCE-UNIX.txt" <<INFO
source: https://github.com/exiftool/exiftool (official mirror; exiftool.org redirects to SourceForge)
version: ${EXIFTOOL_VERSION}
archive: ${URL}
sha256: ${EXIFTOOL_SHA256}
fetched_utc: $(date -u +%Y-%m-%dT%H:%M:%SZ)
requires: perl on PATH
license: Artistic License 1.0 / GPL (same terms as exiftool itself)
INFO

echo "[fetch_exiftool] installed $installed -> $DEST/exiftool"
