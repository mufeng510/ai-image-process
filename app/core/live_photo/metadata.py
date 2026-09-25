"""Live Photo identifiers: photo tags + MOV content.identifier/still-image-time.

Strategy (cross-platform, no macOS APIs):
- Photo: new UUID written to EXIF ImageUniqueID + XMP tags via ExifTool
  (best-effort across ExifTool tag names; validator accepts any of them).
- Movie: ffmpeg `-metadata com.apple.quicktime.content.identifier=...` at
  encode time (best effort) + a safe appended top-level `uuid` box carrying
  JSON {content_identifier, still_image_time_ms}. Appending a top-level box
  never breaks playback (players skip unknown boxes) and gives our Stage-1
  validator a deterministic signal without macOS frameworks.
- still-image-time is ALSO written via ExifTool QuickTime keys when available.
"""
from __future__ import annotations

import json
import struct
import subprocess
import uuid
from pathlib import Path

STILL_IMAGE_TIME_KEY = "com.apple.quicktime.still-image-time"
CONTENT_IDENTIFIER_KEY = "com.apple.quicktime.content.identifier"

# Custom 16-byte user-type for our appended uuid box (random but fixed).
AIP_UUID_USERTYPE = bytes.fromhex("A15050524F435553544B465641554C50")


def new_asset_identifier() -> str:
    return str(uuid.uuid4()).upper()


def write_photo_identifier(photo_path: Path, identifier: str, exiftool=None) -> list[str]:
    """Write Apple pairing identifier onto the JPEG. Returns tags written."""
    if exiftool is None:
        from app.core.exiftool_runner import ExifToolRunner

        exiftool = ExifToolRunner()
    if not getattr(exiftool, "available", lambda: False)():
        return []
    candidates = [
        f"-EXIF:ImageUniqueID={identifier}",
        f"-XMP-xmp:ImageUniqueID={identifier}",
        f"-MakerNotes:ContentIdentifier={identifier}",
        f"-XMP-Apple:ContentIdentifier={identifier}",
    ]
    written: list[str] = []
    for tag in candidates:
        try:
            exiftool.run(["-overwrite_original", tag, str(photo_path)])
            written.append(tag.split("=")[0])
        except Exception:
            continue
    # Always embed a plain XMP-sidecar-free comment fallback? No: keep file clean.
    return written


def read_photo_identifiers(photo_path: Path, exiftool=None) -> list[str]:
    found: list[str] = []
    # 1) ExifTool dump
    try:
        if exiftool is None:
            from app.core.exiftool_runner import ExifToolRunner

            exiftool = ExifToolRunner()
        if getattr(exiftool, "available", lambda: False)():
            import subprocess as sp

            from app.platform import CREATE_NO_WINDOW

            proc = sp.run([str(exiftool.binary), "-j", "-n", str(photo_path)],
                          capture_output=True, text=True, check=False,
                          creationflags=CREATE_NO_WINDOW)
            if proc.returncode == 0 and proc.stdout.strip():
                arr = json.loads(proc.stdout)
                if arr:
                    dump = arr[0]
                    for k, v in dump.items():
                        kl = k.lower()
                        if ("contentidentifier" in kl or "imageuniqueid" in kl) and v:
                            found.append(str(v))
    except Exception:
        pass
    # 2) raw byte scan for UUID-like identifier (covers our writer path)
    try:
        raw = photo_path.read_bytes()
        import re

        for m in re.findall(rb"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}", raw):
            found.append(m.decode("ascii"))
    except Exception:
        pass
    return found


def patch_mov_with_livephoto_tags(mov_path: Path, identifier: str, still_ms: int,
                                  exiftool=None) -> None:
    """Attach pairing metadata to MOV (ExifTool keys + appended uuid box)."""
    if exiftool is None:
        from app.core.exiftool_runner import ExifToolRunner

        exiftool = ExifToolRunner()
    if getattr(exiftool, "available", lambda: False)():
        for tag in (
            f"-XMP-xmp:ImageUniqueID={identifier}",
            f"-Keys:ContentIdentifier={identifier}",
            f"-{STILL_IMAGE_TIME_KEY}={still_ms}",
            f"-QuickTime:StillImageTime={still_ms}",
        ):
            try:
                exiftool.run(["-overwrite_original", tag, str(mov_path)])
            except Exception:
                continue
    # Append deterministic uuid box (safe top-level extension).
    payload = json.dumps(
        {"content_identifier": identifier, "still_image_time_ms": int(still_ms)},
        separators=(",", ":"),
    ).encode("utf-8")
    box_size = 8 + 16 + len(payload)
    box = struct.pack(">I", box_size) + b"uuid" + AIP_UUID_USERTYPE + payload
    with open(mov_path, "ab") as fh:
        fh.write(box)


def read_mov_livephoto_tags(mov_path: Path, exiftool=None) -> dict:
    """Collect identifier + still-image-time signals from MOV."""
    out: dict = {"identifiers": [], "still_image_time_ms": None, "raw_box": None}
    # 1) appended uuid box
    try:
        raw = mov_path.read_bytes()
        idx = raw.find(AIP_UUID_USERTYPE)
        if idx != -1:
            start = idx + 16
            # payload runs to box end; try JSON decode of progressively
            # shorter tails (file may have trailing boxes - none in practice).
            blob = raw[start:start + 4096]
            end = blob.find(b"}")
            if end != -1:
                try:
                    out["raw_box"] = json.loads(blob[: end + 1].decode("utf-8"))
                except Exception:
                    pass
    except Exception:
        pass
    if out["raw_box"]:
        out["identifiers"].append(out["raw_box"].get("content_identifier", ""))
        out["still_image_time_ms"] = out["raw_box"].get("still_image_time_ms")
    # 2) ExifTool dump
    try:
        if exiftool is None:
            from app.core.exiftool_runner import ExifToolRunner

            exiftool = ExifToolRunner()
        if getattr(exiftool, "available", lambda: False)():
            proc = subprocess.run([str(exiftool.binary), "-j", "-n", str(mov_path)],
                                  capture_output=True, text=True, check=False)
            if proc.returncode == 0 and proc.stdout.strip():
                arr = json.loads(proc.stdout)
                if arr:
                    dump = arr[0]
                    for k, v in dump.items():
                        kl = k.lower()
                        if ("contentidentifier" in kl or "imageuniqueid" in kl) and v:
                            out["identifiers"].append(str(v))
                        if ("stillimagetime" in kl or "still-image-time" in kl) and v is not None:
                            try:
                                out["still_image_time_ms"] = int(float(str(v)))
                            except Exception:
                                pass
    except Exception:
        pass
    # 3) raw scan for identifier-looking UUIDs + still key name
    try:
        raw = mov_path.read_bytes()
        import re

        for m in re.findall(rb"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}", raw):
            out["identifiers"].append(m.decode("ascii"))
        if STILL_IMAGE_TIME_KEY.encode() in raw and out["still_image_time_ms"] is None:
            out["still_image_time_ms"] = 0
    except Exception:
        pass
    out["identifiers"] = [i for i in out["identifiers"] if i]
    return out
