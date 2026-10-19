"""moov-after-mdat reorder tests (real iPhone Live Photos are laid out that way)."""
import struct
import subprocess
from pathlib import Path

import pytest

from app.core.live_photo import moov_order
from app.core.live_photo import timed_track as tt
from app.core.exiftool_runner import ExifToolRunner
from app.core.ffmpeg_resolver import resolve_ffmpeg
from app.platform import CREATE_NO_WINDOW


def _has_tools() -> bool:
    return resolve_ffmpeg() is not None and ExifToolRunner().available()


needs_tools = pytest.mark.skipif(not _has_tools(), reason="ffmpeg/exiftool not available")


def _top_boxes(path: Path) -> list[str]:
    raw = path.read_bytes()
    return [t.decode("latin1") for t, _o, _s, _h in tt._parse_boxes(raw)]


def _make_movie(path: Path, ffmpeg: Path, *, faststart: bool) -> Path:
    cmd = [str(ffmpeg), "-y", "-v", "error", "-f", "lavfi",
           "-i", "testsrc=size=160x120:rate=30:duration=1",
           "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-an"]
    if faststart:
        cmd += ["-movflags", "+faststart"]
    cmd.append(str(path))
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          creationflags=CREATE_NO_WINDOW)
    assert proc.returncode == 0 and path.exists(), proc.stderr
    return path


@needs_tools
def test_reorder_moves_moov_behind_mdat(tmp_path: Path):
    ffmpeg = resolve_ffmpeg()
    mov = _make_movie(tmp_path / "v.mov", ffmpeg, faststart=True)
    assert _top_boxes(mov).index("moov") < _top_boxes(mov).index("mdat")

    assert moov_order.move_moov_after_mdat(mov) is True

    boxes = _top_boxes(mov)
    assert boxes.index("moov") > boxes.index("mdat")


@needs_tools
def test_reorder_is_idempotent(tmp_path: Path):
    ffmpeg = resolve_ffmpeg()
    mov = _make_movie(tmp_path / "v.mov", ffmpeg, faststart=True)
    assert moov_order.move_moov_after_mdat(mov) is True
    before = mov.read_bytes()
    assert moov_order.move_moov_after_mdat(mov) is False
    assert mov.read_bytes() == before


@needs_tools
def test_reorder_keeps_video_decodable(tmp_path: Path):
    """Chunk offsets are rebased by moov's size; a wrong delta corrupts the
    video even though the boxes still parse."""
    ffmpeg = resolve_ffmpeg()
    mov = _make_movie(tmp_path / "v.mov", ffmpeg, faststart=True)
    moov_order.move_moov_after_mdat(mov)

    proc = subprocess.run([str(ffmpeg), "-v", "error", "-i", str(mov), "-f", "null", "-"],
                          capture_output=True, text=True,
                          creationflags=CREATE_NO_WINDOW)
    assert proc.returncode == 0, proc.stderr


@needs_tools
def test_reorder_then_splice_matches_movie_order(tmp_path: Path):
    """The reason the reorder exists: with moov behind mdat the timed-track
    splice can append to mdat without moving any existing chunk."""
    ffmpeg = resolve_ffmpeg()
    mov = _make_movie(tmp_path / "v.mov", ffmpeg, faststart=True)
    moov_order.move_moov_after_mdat(mov)
    assert tt.add_still_image_time_track(mov, 0) is True

    assert _top_boxes(mov).index("moov") > _top_boxes(mov).index("mdat")
    proc = subprocess.run([str(ffmpeg), "-v", "error", "-i", str(mov), "-f", "null", "-"],
                          capture_output=True, text=True,
                          creationflags=CREATE_NO_WINDOW)
    assert proc.returncode == 0, proc.stderr
    exif = ExifToolRunner()
    proc = subprocess.run([str(exif.binary), "-G", "-s", "-ee", str(mov)],
                          capture_output=True, text=True,
                          creationflags=CREATE_NO_WINDOW)
    assert "StillImageTime" in proc.stdout


def test_reorder_rejects_non_bmff(tmp_path: Path):
    p = tmp_path / "x.mov"
    p.write_bytes(b"hello world, not a movie")
    assert moov_order.move_moov_after_mdat(p) is False


def test_reorder_rejects_missing_moov(tmp_path: Path):
    p = tmp_path / "x.mov"
    p.write_bytes(struct.pack(">I", 8) + b"ftyp" + b"\x00" * 8)
    assert moov_order.move_moov_after_mdat(p) is False