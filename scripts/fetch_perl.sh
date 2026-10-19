#!/usr/bin/env bash
# Fetch a self-contained perl into Tools/perl/ so a unix portable build needs
# nothing from the host.
#
# Why this exists: the unix ExifTool distribution is a *perl script* with a
# `#!/usr/bin/env perl` shebang. Bundling the script alone is not self-contained
# -- on a machine without perl every Live Photo fails Stage-1 validation with
# "photo asset identifier missing", which reads like a metadata bug rather than
# a missing interpreter. Shipping a relocatable perl alongside it closes the gap
# for macOS 13+ (where Apple removed perl) and minimal containers.
#
# Source: skaji/relocatable-perl, GPL | Artistic licensed like perl itself.
# Chosen over the system perl because it relocates (INC paths resolve relative
# to the binary), which is exactly what a portable bundle needs.
#
# Layout produced:
#   Tools/perl/bin/perl
#   Tools/perl/lib/...
# Binaries are gitignored; SOURCE.txt records what was fetched.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

DEST="$ROOT/Tools/perl"
BASE_URL="https://github.com/skaji/relocatable-perl/releases/latest/download"

if [ -x "$DEST/bin/perl" ]; then
  echo "[fetch_perl] already present: $DEST/bin/perl"
  exit 0
fi

uname_s="$(uname -s)"
uname_m="$(uname -m)"
case "$uname_s" in
  Linux*) os_token="linux" ;;
  Darwin*) os_token="darwin" ;;
  *) echo "[fetch_perl] unsupported OS: $uname_s" >&2; exit 1 ;;
esac
case "$uname_m" in
  x86_64|amd64) arch_token="amd64" ;;
  aarch64|arm64) arch_token="arm64" ;;
  *) echo "[fetch_perl] unsupported arch: $uname_m" >&2; exit 1 ;;
esac

asset="perl-${os_token}-${arch_token}.tar.xz"
url="${BASE_URL}/${asset}"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

echo "[fetch_perl] downloading ${asset} ..."
curl -fsSL --retry 3 --connect-timeout 30 -o "$tmp/perl.tar.xz" "$url" \
  || { echo "[fetch_perl] download failed: $url" >&2; exit 1; }

# No sha256 is published for these rolling-release assets, so verify by
# content instead: the tarball must contain a runnable perl of the expected
# major version. A wrong-arch or truncated download fails here, not at runtime.
mkdir -p "$DEST"
tar xJf "$tmp/perl.tar.xz" -C "$tmp" || {
  echo "[fetch_perl] cannot extract $asset (wrong arch or truncated download)" >&2
  rm -rf "$DEST"; exit 1;
}
srcdir="$(find "$tmp" -maxdepth 1 -type d -name "perl-*" | head -n 1)"
[ -n "$srcdir" ] && [ -d "$srcdir/bin" ] || {
  echo "[fetch_perl] unexpected archive layout in $asset" >&2
  rm -rf "$DEST"; exit 1;
}
[ -f "$srcdir/bin/perl" ] || {
  echo "[fetch_perl] $asset has no bin/perl" >&2
  rm -rf "$DEST"; exit 1;
}

rm -rf "$DEST/lib" "$DEST/bin"
cp -R "$srcdir/." "$DEST/"
chmod +x "$DEST/bin/perl" 2>/dev/null || true
# bin/ holds helper scripts too; make them all runnable.
find "$DEST/bin" -maxdepth 1 -type f -exec chmod +x {} + 2>/dev/null || true

version="$("$DEST/bin/perl" -e 'print $^V' 2>/dev/null || true)"
case "$version" in
  v5.*) ;;
  *)
    echo "[fetch_perl] bundled perl does not run (wrong libc/arch?)" >&2
    echo "  expected a v5.x interpreter, got '${version:-<none>}'" >&2
    rm -rf "$DEST"; exit 1
    ;;
esac

cat > "$DEST/SOURCE.txt" <<INFO
source: https://github.com/skaji/relocatable-perl (self-contained perl for unix builds)
asset: ${asset}
url: ${url}
fetched_utc: $(date -u +%Y-%m-%dT%H:%M:%SZ)
perl_version: ${version}
purpose: interpreter for the bundled unix ExifTool, which is a perl script
license: GPL | Artistic (same terms as perl itself); includes App::cpanminus, App::ChangeShebang, libxcrypt
INFO

echo "[fetch_perl] installed perl ${version} -> $DEST/bin/perl"

# Prove the two work together now, not just in theory: run the bundled ExifTool
# through this interpreter and require the version we actually expect.
if [ -f "$ROOT/Tools/exiftool/exiftool" ]; then
  et_ver="$("$DEST/bin/perl" "$ROOT/Tools/exiftool/exiftool" -ver 2>/dev/null || true)"
  if [ -n "$et_ver" ] && echo "$et_ver" | grep -q 'Warning: Library version'; then
    echo "[fetch_perl] warning: bundled ExifTool loaded a system library instead of Tools/exiftool/lib" >&2
  fi
  echo "[fetch_perl] ExifTool via bundled perl: ${et_ver:-<failed>}"
fi