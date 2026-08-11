"""OS and portable path helpers."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


APP_NAME = "AI-Image-Process"


def is_frozen() -> bool:
    return getattr(sys, "frozen", False) is True


def app_root() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def resource_path(*parts: str) -> Path:
    base = app_root()
    candidate = base.joinpath(*parts)
    if candidate.exists():
        return candidate
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        p = Path(meipass).joinpath(*parts)
        if p.exists():
            return p
    return candidate


def _ensure_dir(path: Path) -> Path:
    try:
        path.mkdir(parents=True, exist_ok=True)
        return path
    except OSError:
        fallback = Path(tempfile.gettempdir()) / APP_NAME / path.name
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def user_config_dir(portable_mode: bool = False) -> Path:
    if portable_mode:
        return _ensure_dir(app_root() / "config")
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return _ensure_dir(base / APP_NAME)


def user_data_dir(portable_mode: bool = False) -> Path:
    if portable_mode:
        return _ensure_dir(app_root() / "data")
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return _ensure_dir(base / APP_NAME)


def default_temp_dir(portable_mode: bool = False) -> Path:
    return _ensure_dir(user_data_dir(portable_mode) / "temp")


def default_log_dir(portable_mode: bool = False) -> Path:
    return _ensure_dir(user_data_dir(portable_mode) / "logs")


def phones_json_path() -> Path:
    return resource_path("assets", "devices", "phones.json")


def icc_profile_path() -> Path:
    return resource_path("assets", "icc", "sRGB-IEC61966-2.1.icc")


def exiftool_candidates() -> list[Path]:
    root = app_root()
    unix = [
        root / "Tools" / "exiftool" / "exiftool",
        resource_path("Tools", "exiftool", "exiftool"),
    ]
    windows = [
        root / "Tools" / "exiftool" / "exiftool.exe",
        root / "DoubaoProcessor" / "Tools" / "exiftool-13.59_64" / "exiftool.exe",
        resource_path("Tools", "exiftool", "exiftool.exe"),
    ]
    if sys.platform.startswith("win"):
        return windows + unix
    return unix + windows  # prefer native first; runner will validate executability
