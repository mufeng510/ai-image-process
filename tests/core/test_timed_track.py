"""Timed metadata (mebx) track splice tests (pure layout + tool integration)."""
import struct
import subprocess
from pathlib import Path

import pytest

from app.core.live_photo import timed_track as tt
from app.core.exiftool_runner import ExifToolRunner
from app.core.ffmpeg_resolver import resolve_ffmpeg
from app.platform import CREATE_NO_WINDOW


def _has_tools() -> bool:
    return resolve_ffmpeg() is not None and ExifToolRunner().available()


needs_tools = pytest.mark.skipif(not _has_tools(), reason="ffmpeg/exiftool not available")


def test_keys_box_layout():
    keys = tt._build_keys_box()
    assert b"com.apple.quicktime.still-image-time" in keys
    assert b"keyd" in keys and b"dtyp" in keys
    # NO version/flags+count header - real captures carry entries immediately;
    # first entry (local ID 1) starts right after the box header.
    entry_size, local_id = struct.unpack(">II", keys[8:16])
    assert local_id == 1
    assert entry_size == len(keys) - 8


def test_sample_layout():
    s = tt._build_sample()
    assert len(s) == 9
    size, lid = struct.unpack(">II", s[:8])
    assert size == 9 and lid == 1
    assert s[8:] == b"\xff"  # int8s -1, Apple convention


def test_mebx_entry_children_at_24():
    entry = tt._build_mebx_entry()
    assert entry[4:8] == b"mebx"
    # children (keys, btrt, ...) start at offset 24 per exiftool MetaSampleDesc;
    # walk them structurally instead of hardcoding sizes.
    keys_size = struct.unpack(">I", entry[24:28])[0]
    assert entry[28:32] == b"keys"
    btrt_off = 24 + keys_size
    assert entry[btrt_off:btrt_off + 4] == struct.pack(">I", len(entry) - btrt_off)
    assert entry[btrt_off + 4:btrt_off + 8] == b"btrt"
    assert btrt_off + (len(entry) - btrt_off) == len(entry)


def test_splice_rejects_nonzero_still(tmp_path: Path):
    p = tmp_path / "x.mov"
    p.write_bytes(b"\x00" * 64)
    assert tt.add_still_image_time_track(p, 50) is False


def test_splice_rejects_non_bmff(tmp_path: Path):
    p = tmp_path / "x.mov"
    p.write_bytes(b"hello world, not a movie")
    assert tt.add_still_image_time_track(p, 0) is False


def test_patch_chunk_offsets():
    stco = tt._box(b"stco", struct.pack(">II", 0, 1) + struct.pack(">I", 100))
    stbl = tt._box(b"stbl", stco)
    minf = tt._box(b"minf", stbl)
    mdia = tt._box(b"mdia", minf)
    trak = tt._box(b"trak", mdia)
    moov = bytearray(tt._box(b"moov", trak))
    tt._patch_chunk_offsets(moov, 500)
    assert struct.pack(">I", 600) in bytes(moov)  # 100 + 500


@needs_tools
def test_splice_end_to_end(tmp_path: Path):
    ffmpeg = resolve_ffmpeg()
    assert ffmpeg is not None
    mov = tmp_path / "v.mov"
    cmd = [str(ffmpeg), "-y", "-v", "error", "-f", "lavfi",
           "-i", "testsrc=size=160x120:rate=30:duration=1",
           "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
           "-an", str(mov)]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          creationflags=CREATE_NO_WINDOW)
    assert proc.returncode == 0 and mov.exists()
    assert tt.add_still_image_time_track(mov, 0) is True
    # oracle: exiftool must report StillImageTime from the timed track
    exif = ExifToolRunner()
    proc = subprocess.run([str(exif.binary), "-G", "-s", "-ee", str(mov)],
                          capture_output=True, text=True,
                          creationflags=CREATE_NO_WINDOW)
    assert proc.returncode == 0
    assert "StillImageTime" in proc.stdout
    # video track still decodes cleanly
    proc = subprocess.run([str(ffmpeg), "-v", "error", "-i", str(mov),
                           "-f", "null", "-"],
                          capture_output=True, creationflags=CREATE_NO_WINDOW)
    assert proc.returncode == 0
