
"""Output filename template rendering."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path


ALLOWED_VARS = {
    "original_name", "original_ext", "date", "time", "datetime", "number",
    "year", "month", "day", "hour", "minute", "second",
}


def render_filename(
    template: str,
    *,
    original_name: str,
    original_ext: str,
    when: datetime,
    number: int,
    number_width: int = 3,
) -> str:
    values = {
        "original_name": original_name,
        "original_ext": original_ext.lstrip("."),
        "date": when.strftime("%Y%m%d"),
        "time": when.strftime("%H%M%S"),
        "datetime": when.strftime("%Y%m%d_%H%M%S"),
        "number": str(number).zfill(max(1, number_width)),
        "year": when.strftime("%Y"),
        "month": when.strftime("%m"),
        "day": when.strftime("%d"),
        "hour": when.strftime("%H"),
        "minute": when.strftime("%M"),
        "second": when.strftime("%S"),
    }
    out = template
    for key, val in values.items():
        out = out.replace("{" + key + "}", val)
    # reject path tricks
    if any(sep in out for sep in ("/", "\\", "..")) or out.startswith(("~",)):
        raise ValueError(f"unsafe filename template result: {out!r}")
    if not out.strip():
        raise ValueError("empty filename")
    return out


def stem_and_ext(path: Path) -> tuple[str, str]:
    return path.stem, path.suffix.lstrip(".")
