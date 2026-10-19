"""Live Photo identifiers: photo tags + MOV content.identifier/still-image-time.

Strategy (cross-platform, no macOS APIs):
- Photo: canonical Apple MakerNote ContentIdentifier (0x0011, what iOS /
  iTools pair against) via runtime template + TagsFromFile, plus EXIF
  ImageUniqueID fallback.
- Movie: moov/meta Keys content.identifier via ExifTool (writable) +
  hand-spliced mebx timed-metadata track carrying still-image-time
  (timed_track.add_still_image_time_track - neither ffmpeg nor ExifTool can
  author it). The reader additionally understands our legacy appended uuid
  box so previously generated files still validate.
"""
from __future__ import annotations

import json
import struct
import subprocess
import uuid
from pathlib import Path

STILL_IMAGE_TIME_KEY = "com.apple.quicktime.still-image-time"
CONTENT_IDENTIFIER_KEY = "com.apple.quicktime.content.identifier"

# EXIF tag id for MakerNote + Apple MakerNote tag id for ContentIdentifier.
MAKERNOTE_TAG_ID = 0x927C
APPLE_CONTENT_IDENTIFIER_TAG = 0x0011
_PLACEHOLDER_UUID = "00000000-0000-0000-0000-000000000000"

# A real iPhone capture's MOV carries these next to the content identifier; they
# are what marks the movie as a Live Photo rather than a plain clip. Verified
# against a device export (iPhone 15, iOS 27.0.1).
LIVE_PHOTO_KEY_TAGS = (
    "-Keys:LivePhotoAuto=1",
    "-Keys:FullFrameRatePlaybackIntent=1",
)

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
    written: list[str] = []
    # Canonical tag first: Apple MakerNote ContentIdentifier (0x0011) - this is
    # what iOS / iTools pair against. ExifTool cannot create MakerNotes, so it
    # goes through a runtime-generated template (see ensure_photo_makernote).
    try:
        if ensure_photo_makernote(photo_path, identifier, exiftool=exiftool):
            written.append("MakerNotes:ContentIdentifier")
    except Exception:
        pass
    candidates = [
        f"-EXIF:ImageUniqueID={identifier}",
        f"-XMP-xmp:ImageUniqueID={identifier}",
    ]
    for tag in candidates:
        try:
            exiftool.run(["-overwrite_original", tag, str(photo_path)])
            written.append(tag.split("=")[0])
        except Exception:
            continue
    # Always embed a plain XMP-sidecar-free comment fallback? No: keep file clean.
    return written


def build_apple_makernote(identifier: str) -> bytes:
    """Minimal Apple MakerNote blob holding ContentIdentifier (tag 0x0011).

    Layout verified against real iPhone captures (TIFF-style directory with
    its own byte order; value offsets are relative to the blob start):
    ``"Apple iOS\\0" + version + byte-order + entry-count + entries +
    next-IFD + value``.
    """
    value = identifier.encode("ascii", errors="replace") + b"\x00"
    blob = bytearray()
    blob += b"Apple iOS\x00"          # 0..10
    blob += struct.pack(">H", 1)      # version
    blob += b"MM"                     # big-endian
    blob += struct.pack(">H", 1)      # one entry
    value_offset = 16 + 12 + 4
    blob += struct.pack(">H", APPLE_CONTENT_IDENTIFIER_TAG)
    blob += struct.pack(">H", 2)      # ASCII
    blob += struct.pack(">I", len(value))
    blob += struct.pack(">I", value_offset)
    blob += struct.pack(">I", 0)      # next IFD offset
    assert len(blob) == value_offset
    blob += value
    return bytes(blob)


_makernote_template: Path | None = None


def _makernote_template_jpeg() -> Path | None:
    """Tiny JPEG carrying an Apple MakerNote with a placeholder UUID.

    ExifTool cannot create MakerNotes from scratch, but it CAN copy them via
    TagsFromFile and then rewrite the ContentIdentifier value (writable once
    the tag exists). The template is generated at runtime - no binary asset.
    """
    global _makernote_template
    if _makernote_template is not None and _makernote_template.exists():
        return _makernote_template
    try:
        from PIL import Image
        import tempfile

        blob = build_apple_makernote(_PLACEHOLDER_UUID)
        # Minimal big-endian TIFF: single IFD0 entry (MakerNote, UNDEFINED).
        ifd = struct.pack(">H", 1)
        ifd += struct.pack(">HHI", MAKERNOTE_TAG_ID, 7, len(blob))
        value_offset = 8 + 2 + 12 + 4
        ifd += struct.pack(">I", value_offset)
        ifd += struct.pack(">I", 0)
        tiff = b"MM\x00\x2a" + struct.pack(">I", 8) + ifd
        assert len(tiff) == value_offset
        tiff += blob
        exif_app1 = b"Exif\x00\x00" + tiff
        tmp = Path(tempfile.mkdtemp(prefix="aip_mn_")) / "mn_template.jpg"
        Image.new("RGB", (8, 8), (0, 0, 0)).save(tmp, format="JPEG")
        raw = bytearray(tmp.read_bytes())
        assert raw[0:2] == b"\xff\xd8"  # SOI
        seg = b"\xff\xe1" + struct.pack(">H", len(exif_app1) + 2) + exif_app1
        tmp.write_bytes(bytes(raw[0:2]) + seg + bytes(raw[2:]))
        _makernote_template = tmp
        return tmp
    except Exception:
        return None


def ensure_photo_makernote(photo_path: Path, identifier: str, exiftool=None) -> bool:
    """Attach canonical Apple MakerNote ContentIdentifier to the JPEG."""
    if exiftool is None:
        from app.core.exiftool_runner import ExifToolRunner

        exiftool = ExifToolRunner()
    if not getattr(exiftool, "available", lambda: False)():
        return False
    try:
        ref = _makernote_template_jpeg()
        if ref is None:
            return False
        exiftool.run(["-overwrite_original", "-TagsFromFile", str(ref),
                      "-MakerNotes", str(photo_path)])
        exiftool.run(["-overwrite_original",
                      f"-MakerNotes:ContentIdentifier={identifier}",
                      str(photo_path)])
    except Exception:
        return False
    # Verify the canonical tag actually stuck.
    try:
        return identifier in read_photo_identifiers(photo_path, exiftool=exiftool)
    except Exception:
        return False


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


def read_still_identity(photo_path: Path, exiftool=None) -> dict:
    """Device identity + capture time as written on the still JPEG.

    A real capture's MOV repeats its JPEG's make/model/software and carries a
    creation date. Reading them back off the still keeps the two resources
    self-consistent regardless of which steps ran before Live Photo.
    """
    out: dict = {}
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
                dump = json.loads(proc.stdout)[0]
                out = {
                    "make": dump.get("Make"),
                    "model": dump.get("Model") or dump.get("CameraModelName"),
                    "software": dump.get("Software"),
                    "captured": (dump.get("DateTimeOriginal")
                                 or dump.get("CreateDate")),
                }
    except Exception:
        pass
    return {k: str(v).strip() for k, v in out.items() if v and str(v).strip()}


def patch_mov_with_livephoto_tags(mov_path: Path, identifier: str, still_ms: int,
                                   exiftool=None, still_path: Path | None = None) -> None:
    """Attach pairing metadata to MOV (Keys + mebx timed track).

    Direct ExifTool writes of still-image-time are NOT attempted: the tag is
    non-writable and lives in a timed-metadata track, handled instead by
    timed_track.add_still_image_time_track() below.

    ExifTool rewrites the whole movie and puts moov in front of mdat - the one
    layout normalize_movie() was written to avoid - so move_moov_after_mdat
    puts it back before the timed track is spliced.

    NOTE: no custom top-level uuid box is appended anymore. Real iPhone
    captures carry none, and a non-standard trailing box is a needless
    strict-parser risk for iTools. AIP_UUID_USERTYPE + the raw_box reader
    branch stay for backward compatibility with previously generated files.
    """
    if exiftool is None:
        from app.core.exiftool_runner import ExifToolRunner

        exiftool = ExifToolRunner()
    if getattr(exiftool, "available", lambda: False)():
        identity = read_still_identity(still_path, exiftool) if still_path else {}
        tags = [f"-Keys:ContentIdentifier={identifier}", *LIVE_PHOTO_KEY_TAGS]
        for key, field in (("Make", "make"), ("Model", "model"),
                           ("Software", "software"), ("CreationDate", "captured")):
            if identity.get(field):
                tags.append(f"-Keys:{key}={identity[field]}")
        # QuickTime movie header: ffmpeg leaves these at 0000:00:00, a device
        # capture always stamps them.
        if identity.get("captured"):
            tags += [f"-QuickTime:CreateDate={identity['captured']}",
                     f"-QuickTime:ModifyDate={identity['captured']}"]
        try:
            exiftool.run(["-overwrite_original", *tags, str(mov_path)])
        except Exception:
            # One rejected tag must not cost the pairing identifier.
            for tag in tags:
                try:
                    exiftool.run(["-overwrite_original", tag, str(mov_path)])
                except Exception:
                    continue
    # Restore moov-after-mdat so the timed-track splice needs no stco patching.
    try:
        from app.core.live_photo.moov_order import move_moov_after_mdat

        move_moov_after_mdat(mov_path)
    except Exception:
        pass
    # Canonical still-image-time: splice a mebx timed-metadata track.
    # Best-effort and never fatal - validator flags a missing marker.
    try:
        from app.core.live_photo.timed_track import add_still_image_time_track

        add_still_image_time_track(mov_path, int(still_ms))
    except Exception:
        pass


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
    # 2) ExifTool dump (-ee: timed-metadata samples live in mdat and are
    # only extracted with ExtractEmbedded; without it StillImageTime stays
    # invisible even when the mebx track is present).
    try:
        if exiftool is None:
            from app.core.exiftool_runner import ExifToolRunner

            exiftool = ExifToolRunner()
        if getattr(exiftool, "available", lambda: False)():
            import subprocess as sp

            from app.platform import CREATE_NO_WINDOW

            proc = sp.run([str(exiftool.binary), "-ee", "-j", "-n", str(mov_path)],
                          capture_output=True, text=True, check=False,
                          creationflags=CREATE_NO_WINDOW)
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
