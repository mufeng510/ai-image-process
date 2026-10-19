"""Output format invariant: committed files are always JPEG.

The product promise is that a finished job hands the user JPEGs. Several
steps already guarantee that by re-encoding (reencode, rotate_crop,
hidden_image, live_photo), but when all of them are switched off the pipeline
copies the source bytes straight through — which used to write a TIFF or PNG
payload into a file named `*.jpg`.

This module keeps the promise checkable in two places:
- `pipeline_produces_jpeg()` lets Preflight refuse an impossible request
  before any work starts (no outputs, nothing deleted).
- `is_jpeg_file()` lets output_write verify the bytes it is about to publish,
  so no future step can reintroduce a mislabeled output.
"""
from __future__ import annotations

from pathlib import Path

from app.config.schema import AppConfig

# Committed output extensions.
#
# i4Tools (爱思助手) matches a Live Photo pair with a CASE-SENSITIVE extension
# check and silently skips anything it does not recognise - a bundle that is
# byte-for-byte valid but written as "x.jpg + x.mov" never reaches the pairing
# stage at all. Device exports are ".JPG" + ".MOV"; confirmed by an otherwise
# identical 4-way import test where only this casing decided the outcome.
# Everything that names a committed output must use these constants.
OUTPUT_JPG_EXT = ".JPG"
OUTPUT_MOV_EXT = ".MOV"

# Steps that unconditionally re-encode the current file as JPEG.
# live_photo is deliberately NOT here: its builder only copies the still into
# a file named .jpg (app/core/live_photo/builder.py), so it inherits whatever
# format the still had.
JPEG_PRODUCING_STEPS = ("reencode", "rotate_crop", "hidden_image")


def strip_jpg_ext(name: str) -> str:
    """Drop a trailing .jpg/.JPG from a name, case-insensitively.

    `naming` may include an extension and steps downstream may hand back an
    output name; the stem has to be recovered before the Live Photo bundle
    appends OUTPUT_JPG_EXT again.
    """
    if name.lower().endswith(OUTPUT_JPG_EXT.lower()):
        return name[: -len(OUTPUT_JPG_EXT)]
    return name


def strip_mov_ext(name: str) -> str:
    """Drop a trailing .mov/.MOV from a name, case-insensitively."""
    if name.lower().endswith(OUTPUT_MOV_EXT.lower()):
        return name[: -len(OUTPUT_MOV_EXT)]
    return name


def pipeline_produces_jpeg(config: AppConfig) -> bool:
    """True when at least one enabled step guarantees JPEG output bytes."""
    steps = config.steps
    return bool(
        steps.reencode.enabled
        or steps.rotate_crop.enabled
        or steps.hidden_image.enabled
    )


def non_jpeg_records(records, config: AppConfig) -> list[Path]:
    """Records whose source is not a JPEG and would pass through untouched."""
    if pipeline_produces_jpeg(config):
        return []
    return [r.source_path for r in records
            if str(getattr(r, "original_ext", "")).lower().lstrip(".") not in ("jpg", "jpeg")]


def is_jpeg_file(path: Path | str) -> bool:
    """True only if the file starts with the JPEG SOI marker.

    Extension is deliberately ignored: the whole point is to catch a payload
    that does not match the `.jpg` name it is about to be written under.
    """
    try:
        with open(path, "rb") as fh:
            return fh.read(3) == b"\xff\xd8\xff"
    except OSError:
        return False
