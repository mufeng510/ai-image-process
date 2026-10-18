"""FFmpeg/ffprobe runtime resolution (bundled, runtime-installed, or PATH).

Thin wrapper kept for call-site compatibility: all discovery now lives in
app.core.runtime_tools so the GUI status panel and the pipeline can never
disagree about whether FFmpeg is present.
"""
from __future__ import annotations

from pathlib import Path

from app.core.runtime_tools import FFMPEG_DIR, find_tool, user_install_dir  # noqa: F401


def _find(name: str) -> Path | None:
    return find_tool(FFMPEG_DIR, name).path


def resolve_ffmpeg() -> Path | None:
    return _find("ffmpeg")


def resolve_ffprobe() -> Path | None:
    return _find("ffprobe")


def ffmpeg_available() -> bool:
    return resolve_ffmpeg() is not None
