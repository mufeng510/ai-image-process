"""Runtime tool discovery (ExifTool / FFmpeg / ffprobe) with one status shape.

Why this module exists: the release bundles a Windows-only ExifTool, and the
old resolver never looked at PATH, so on Linux/macOS the app could never find
one — device EXIF silently wrote nothing and every Live Photo failed Stage-1
validation with "photo asset identifier missing". Users should not have to
install a binary by hand for the tool they just downloaded.

Resolution order for each tool (first hit wins):
1. bundled: `Tools/<dir>/<name>` next to the app (portable / frozen bundle)
2. runtime-installed: `<user data>/tools/<dir>/<name>` (one-click install target)
3. system PATH (`shutil.which`)

On non-Windows a missing exec bit is repaired in place, because portable
archives and tarball extraction both lose it — same self-heal FFmpeg already
had.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from app.config.paths import app_root, resource_path, user_data_dir
from app.platform import CREATE_NO_WINDOW

EXIFTOOL_DIR = "exiftool"
FFMPEG_DIR = "ffmpeg"


@dataclass(frozen=True)
class ToolStatus:
    """What the app knows about one external tool right now."""

    name: str
    available: bool
    path: Path | None = None
    version: str = ""
    source: str = ""  # bundled | user-install | PATH | ""

    def display(self) -> str:
        if not self.available:
            return "未安装"
        where = {"bundled": "已内置", "user-install": "已安装", "PATH": "来自系统 PATH"}.get(
            self.source, "已就绪")
        ver = _short_version(self.version)
        return f"{where} · {ver}" if ver else where


def _names(base: str) -> list[str]:
    return [f"{base}.exe", base] if sys.platform.startswith("win") else [base, f"{base}.exe"]


def _looks_runnable(p: Path) -> bool:
    if not p.exists() or not p.is_file():
        return False
    # Keep the two distributions strictly apart: a Windows build must never
    # pick the unix perl script (os.access reports X_OK for everything on
    # Windows), and a unix build must never try to execute a PE binary.
    is_win = sys.platform.startswith("win")
    if p.suffix.lower() == ".exe" and not is_win:
        return False
    if p.suffix.lower() != ".exe" and is_win and p.suffix.lower() in ("", ".pl"):
        # extension-less or .pl script: unix distribution
        return False
    if os.name != "nt" and not os.access(p, os.X_OK):
        try:
            os.chmod(p, p.stat().st_mode | 0o755)
        except OSError:
            # Read-only media (Program Files, read-only USB stick): we cannot
            # repair the bit, so fall through and let os.access decide.
            pass
    return os.access(p, os.X_OK) or (p.suffix.lower() == ".exe" and os.name == "nt")


def _bundled_candidates(tool_dir: str, name: str) -> list[Path]:
    root = app_root()
    out: list[Path] = []
    for n in _names(name):
        out.append(root / "Tools" / tool_dir / n)
        out.append(resource_path("Tools", tool_dir, n))
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        for n in _names(name):
            out.append(Path(meipass) / "Tools" / tool_dir / n)
    return out


def user_install_dir(tool_dir: str, portable_mode: bool = False) -> Path:
    """Writable directory where a one-click install may place a tool."""
    return user_data_dir(portable_mode) / "tools" / tool_dir


def _user_candidates(tool_dir: str, name: str, portable_mode: bool = False) -> list[Path]:
    base = user_install_dir(tool_dir, portable_mode)
    return [base / n for n in _names(name)]


def _version_of(path: Path, args: list[str] | None = None) -> str:
    """Run the tool and return its version line, or "" if it did not work.

    A non-zero exit or an empty line means the candidate is broken (missing
    perl modules, wrong binary, unreadable file). Callers treat that as "not
    available" rather than surfacing the error text as a version.
    """
    try:
        proc = subprocess.run(
            [str(path), *(args or ["-ver"])],
            capture_output=True, text=True, timeout=20, check=False,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if proc.returncode != 0:
        return ""
    out = (proc.stdout or proc.stderr or "").strip()
    return out.splitlines()[0].strip() if out else ""


VERSION_ARGS = {
    # Each tool needs its own flag; ffmpeg rejects "-ver" but still prints a
    # banner, which used to make us depend on a stderr fallback.
    "exiftool": ["-ver"],
    "ffmpeg": ["-version"],
    "ffprobe": ["-version"],
}


def _short_version(version: str) -> str:
    """Reduce a tool's self-reported version to something a status row can show.

    ExifTool prints just `13.59`; ffmpeg prints a whole copyright line, so we
    keep the first token that actually looks like a version number. Anything
    that is not recognisably a version (e.g. a perl "Can't locate ..." error)
    yields "", never the first two words of an error message.
    """
    if not version:
        return ""
    if version[0].isdigit():
        return version.split()[0]
    for token in version.split():
        if token[:1].isdigit():
            return token
    return ""


def find_tool(tool_dir: str, name: str, *, portable_mode: bool = False,
              probe_version: bool = True) -> ToolStatus:
    """Locate one runtime tool and report where it came from.

    When version probing is on, a candidate that cannot report a recognisable
    version is treated as broken and skipped, so a half-installed ExifTool
    (script present, `lib/` missing) never shows up as ready.
    """
    args = VERSION_ARGS.get(name, ["-ver"])

    def accept(p: Path, source: str) -> ToolStatus | None:
        if not _looks_runnable(p):
            return None
        version = _version_of(p, args) if probe_version else ""
        if probe_version and not _short_version(version):
            return None
        return ToolStatus(name, True, p, version, source)

    for p in _bundled_candidates(tool_dir, name):
        st = accept(p, "bundled")
        if st:
            return st
    for p in _user_candidates(tool_dir, name, portable_mode):
        st = accept(p, "user-install")
        if st:
            return st
    found = shutil.which(name) or (shutil.which(f"{name}.exe") if sys.platform.startswith("win") else None)
    if found:
        st = accept(Path(found), "PATH")
        if st:
            return st
    return ToolStatus(name, False, None, "", "")


def exiftool_status(portable_mode: bool = False, probe_version: bool = True) -> ToolStatus:
    return find_tool(EXIFTOOL_DIR, "exiftool",
                     portable_mode=portable_mode, probe_version=probe_version)


def ffmpeg_status(portable_mode: bool = False, probe_version: bool = True) -> ToolStatus:
    return find_tool(FFMPEG_DIR, "ffmpeg",
                     portable_mode=portable_mode, probe_version=probe_version)


def ffprobe_status(portable_mode: bool = False, probe_version: bool = True) -> ToolStatus:
    return find_tool(FFMPEG_DIR, "ffprobe",
                     portable_mode=portable_mode, probe_version=probe_version)


def runtime_summary(portable_mode: bool = False) -> dict[str, ToolStatus]:
    return {
        "exiftool": exiftool_status(portable_mode, probe_version=False),
        "ffmpeg": ffmpeg_status(portable_mode, probe_version=False),
        "ffprobe": ffprobe_status(portable_mode, probe_version=False),
    }
