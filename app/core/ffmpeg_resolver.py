"""FFmpeg/ffprobe runtime resolution (bundled first, never require user PATH)."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from app.config.paths import app_root, resource_path


def _bundled_candidates(names: list[str]) -> list[Path]:
    root = app_root()
    cands: list[Path] = []
    for name in names:
        cands.append(root / "Tools" / "ffmpeg" / name)
        cands.append(resource_path("Tools", "ffmpeg", name))
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        for name in names:
            cands.append(Path(meipass) / "Tools" / "ffmpeg" / name)
    return cands


def _looks_runnable(p: Path) -> bool:
    return p.exists() and p.is_file()


def resolve_ffmpeg() -> Path | None:
    names = ["ffmpeg.exe", "ffmpeg"] if os.name == "nt" else ["ffmpeg", "ffmpeg.exe"]
    for c in _bundled_candidates(names):
        if _looks_runnable(c):
            return c
    found = shutil.which("ffmpeg")
    return Path(found) if found else None


def resolve_ffprobe() -> Path | None:
    names = ["ffprobe.exe", "ffprobe"] if os.name == "nt" else ["ffprobe", "ffprobe.exe"]
    for c in _bundled_candidates(names):
        if _looks_runnable(c):
            return c
    found = shutil.which("ffprobe")
    return Path(found) if found else None


def ffmpeg_available() -> bool:
    return resolve_ffmpeg() is not None
