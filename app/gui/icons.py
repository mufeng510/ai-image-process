"""Application icon lookup (source + PyInstaller frozen)."""
from __future__ import annotations

import sys
from pathlib import Path


def _candidates() -> list[Path]:
    here = Path(__file__).resolve()
    # app/gui/icons.py -> repo root = parents[2]
    repo = here.parents[2]
    cands = [
        repo / "assets" / "icons" / "icon-256.png",
        repo / "assets" / "icons" / "icon.png",
    ]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        base = Path(str(meipass))
        # PyInstaller 6 onedir: _MEIPASS == _internal/ ; v5: _MEIPASS == exe dir
        cands.insert(0, base / "assets" / "icons" / "icon-256.png")
        cands.insert(1, base / "assets" / "icons" / "icon.png")
        cands.insert(2, base.parent / "assets" / "icons" / "icon-256.png")
    try:
        exe_dir = Path(sys.executable).resolve().parent
        cands.insert(0, exe_dir / "assets" / "icons" / "icon-256.png")
        cands.insert(1, exe_dir / "_internal" / "assets" / "icons" / "icon-256.png")
    except Exception:  # noqa: BLE001
        pass
    return cands


def get_app_icon_path() -> Path | None:
    for p in _candidates():
        if p.is_file():
            return p
    return None


def get_app_icon():
    """Return QIcon if available, else None (never raises)."""
    try:
        from PySide6.QtGui import QIcon
    except Exception:
        return None
    path = get_app_icon_path()
    if path is None:
        return None
    try:
        icon = QIcon(str(path))
        return icon if not icon.isNull() else None
    except Exception:
        return None
