"""Hidden-image metadata source + final JPEG metadata finalization.

Priority: hidden assigned image's real capture params (allow-list) ->
missing fields fall back to generated device metadata. Block-list
(GPS, UUIDs, Live Photo identifiers, filenames) is never inherited.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
import random

# EXIF tag ids we are willing to inherit from the hidden image.
ALLOW_EXIF = {
    271,  # Make
    272,  # Model
    42035,  # LensMake (often stored by ExifTool rather than raw id)
    42036,  # LensModel
    33437,  # FNumber
    33434,  # ExposureTime
    34855,  # ISOSpeedRatings
    37386,  # FocalLength
    41989,  # FocalLengthIn35mmFilm
    37385,  # Flash
    41987,  # WhiteBalance
}

ALLOW_NAMES = {
    "Make",
    "Model",
    "LensMake",
    "LensModel",
    "FNumber",
    "ExposureTime",
    "ISO",
    "ISOSpeedRatings",
    "FocalLength",
    "FocalLengthIn35mmFilm",
    "Flash",
    "WhiteBalance",
}


def read_image_exif(path: Path) -> dict[str, Any]:
    """Best-effort EXIF read via Pillow; returns {} when absent/unreadable."""
    try:
        from PIL import Image
        from PIL.ExifTags import TAGS

        with Image.open(path) as im:
            raw = im.getexif()
            if not raw:
                return {}
            out: dict[str, Any] = {}
            for tag_id, value in raw.items():
                name = TAGS.get(tag_id, str(tag_id))
                out[str(name)] = value
                out[f"exif:{tag_id}"] = value
            return out
    except Exception:
        return {}


def extract_hidden_metadata_source(hidden_path: Path) -> dict[str, Any]:
    """Extract inheritable capture params from an assigned hidden image."""
    exif = read_image_exif(hidden_path)
    src: dict[str, Any] = {}
    for key in ALLOW_NAMES:
        if key in exif:
            src[key] = exif[key]
    # Normalize ISO aliases
    if "ISOSpeedRatings" in exif and "ISO" not in src:
        src["ISO"] = exif["ISOSpeedRatings"]
    # Capture datetime basis (EXIF DateTimeOriginal family), used only as a
    # basis when randomize_datetime is on; never copied verbatim blindly.
    for key in ("DateTimeOriginal", "CreateDate", "DateTime", "36867", "36868", "306"):
        if key in exif and "HiddenDateTime" not in src:
            src["HiddenDateTime"] = str(exif[key])
    # ExifTool richer dump (optional, never fatal)
    try:
        from app.core.exiftool_runner import ExifToolRunner

        runner = ExifToolRunner()
        if runner.available():
            import json
            import subprocess

            from app.platform import CREATE_NO_WINDOW

            proc = subprocess.run(
                [str(runner.binary), "-j", "-n", str(hidden_path)],
                capture_output=True,
                text=True,
                check=False,
                creationflags=CREATE_NO_WINDOW,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                arr = json.loads(proc.stdout)
                if arr:
                    dump = arr[0]
                    for k in (
                        "Make",
                        "Model",
                        "LensMake",
                        "LensModel",
                        "FNumber",
                        "ExposureTime",
                        "ISO",
                        "FocalLength",
                        "FocalLengthIn35mmFilm",
                        "Flash",
                        "WhiteBalance",
                        "DateTimeOriginal",
                        "CreateDate",
                    ):
                        if k in dump and k not in src:
                            src[k] = dump[k]
    except Exception:
        pass
    return src


def resolve_capture_datetime(
    hidden_src: dict[str, Any],
    randomize: bool,
    lo_min: int,
    hi_min: int,
    rng: random.Random,
) -> datetime:
    """Capture datetime for the output image.

    - randomize=True: hidden capture time (if any) is only the *basis* the
      project random-offset rule applies to; without hidden time, now-offset.
      This preserves the legacy `randomize -> now - offset` semantics while
      letting real capture times seed the range.
    - randomize=False: always now (legacy semantics); hidden time is never
      copied verbatim.
    """
    if not randomize:
        return datetime.now()
    base: datetime | None = None
    raw = hidden_src.get("HiddenDateTime")
    if raw:
        try:
            base = datetime.strptime(str(raw).split(".")[0], "%Y:%m:%d %H:%M:%S")
        except Exception:
            try:
                base = datetime.strptime(str(raw).split(".")[0], "%Y-%m-%d %H:%M:%S")
            except Exception:
                base = None
    if base is None:
        return datetime.now() - timedelta(minutes=rng.randrange(lo_min, max(lo_min + 1, hi_min)))
    return base - timedelta(minutes=rng.randrange(lo_min, max(lo_min + 1, hi_min)))


def build_device_tags(
    *,
    make: str,
    model: str,
    lens: str,
    when: datetime,
    software: str,
    hidden_src: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Merge hidden source (allow-list) over generated device values."""
    tags = {
        "Make": make,
        "Model": model,
        "LensMake": make,
        "LensModel": lens,
        "FNumber": "1.78",
        "ExposureTime": "1/120",
        "ISO": "100",
        "FocalLength": "24 mm",
        "Flash": "Off, Did not fire",
        "Software": software,
        "DateTimeOriginal": when.strftime("%Y:%m:%d %H:%M:%S"),
        "CreateDate": when.strftime("%Y:%m:%d %H:%M:%S"),
    }
    if hidden_src:
        for k in ("Make", "Model", "LensMake", "LensModel", "FNumber", "ExposureTime",
                  "ISO", "FocalLength", "FocalLengthIn35mmFilm", "Flash", "WhiteBalance"):
            if k in hidden_src and hidden_src[k] not in (None, ""):
                tags[k] = str(hidden_src[k])
    return tags


def apply_final_metadata(
    jpeg_path: Path,
    tags: dict[str, str],
    exiftool=None,
    extra_args: list[str] | None = None,
) -> None:
    """Write final device tags via ExifTool (best effort, raises on failure)."""
    if exiftool is None:
        from app.core.exiftool_runner import ExifToolRunner

        exiftool = ExifToolRunner()
    if not getattr(exiftool, "available", lambda: False)():
        return
    args = ["-overwrite_original"]
    for k, v in tags.items():
        args.append(f"-{k}={v}")
    for a in extra_args or []:
        args.append(a)
    args.append(str(jpeg_path))
    exiftool.run(args)


def reembed_icc(jpeg_path: Path, icc_path: Path | None) -> None:
    """Ensure sRGB ICC survives Pillow transforms; best-effort, never fatal."""
    if not icc_path:
        return
    try:
        from PIL import Image

        p = Path(icc_path)
        if not p.exists():
            return
        icc_bytes = p.read_bytes()
        with Image.open(jpeg_path) as im:
            rgb = im.convert("RGB") if im.mode != "RGB" else im
            exif = rgb.info.get("exif")
            kw: dict = {"icc_profile": icc_bytes}
            if exif:
                kw["exif"] = exif
            tmp = jpeg_path.with_suffix(".iccfix.jpg")
            rgb.save(tmp, format="JPEG", quality=95, subsampling=0, **kw)
        tmp.replace(jpeg_path)
    except Exception:
        pass
