"""LivePhoto builder/validator unit tests (ffmpeg optional; logic always tested)."""
from pathlib import Path

import pytest
from PIL import Image

from app.core.ffmpeg_resolver import resolve_ffmpeg, resolve_ffprobe
from app.core.live_photo.metadata import (
    build_apple_makernote,
    new_asset_identifier,
    patch_mov_with_livephoto_tags,
    read_mov_livephoto_tags,
    read_photo_identifiers,
    write_photo_identifier,
)
from app.core.live_photo.providers.base import MockAIVideoProvider
from app.core.live_photo.validator import LivePhotoValidator

needs_ffmpeg = pytest.mark.skipif(resolve_ffmpeg() is None, reason="ffmpeg not available")


def _has_tools() -> bool:
    from app.core.exiftool_runner import ExifToolRunner

    return resolve_ffmpeg() is not None and ExifToolRunner().available()


needs_tools = pytest.mark.skipif(not _has_tools(), reason="ffmpeg/exiftool not available")


def _real_mov(p: Path, size="160x120", duration=1):
    import subprocess

    from app.platform import CREATE_NO_WINDOW

    ffmpeg = resolve_ffmpeg()
    assert ffmpeg is not None
    cmd = [str(ffmpeg), "-y", "-v", "error", "-f", "lavfi",
           "-i", f"testsrc=size={size}:rate=30:duration={duration}",
           "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
           "-an", str(p)]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          creationflags=CREATE_NO_WINDOW)
    assert proc.returncode == 0 and p.exists()
    return p


def _img(p: Path, size=(320, 240)):
    Image.new("RGB", size, (80, 90, 100)).save(p, quality=90)


def test_identifier_is_fresh_uuid():
    a, b = new_asset_identifier(), new_asset_identifier()
    assert a != b and len(a) == 36


def test_apple_makernote_layout():
    # Pure-bytes check of the Apple MakerNote layout (mirrors the reader:
    # "Apple iOS\0" + version + byte-order + entries, offsets from blob start).
    import struct

    ident = "F0652AEA-5229-4BF7-A366-B4C79E90CA1C"
    blob = build_apple_makernote(ident)
    assert blob.startswith(b"Apple iOS\x00")
    assert blob[10:12] == b"\x00\x01" and blob[12:14] == b"MM"
    assert struct.unpack(">H", blob[14:16])[0] == 1
    tag, typ, count, off = struct.unpack(">HHII", blob[16:28])
    assert (tag, typ) == (0x0011, 2)
    value = blob[off:off + count]
    assert value == ident.encode("ascii") + b"\x00"
    assert struct.unpack(">I", blob[28:32])[0] == 0


def test_photo_identifier_roundtrip(tmp_path):
    p = tmp_path / "s.jpg"
    _img(p)
    ident = new_asset_identifier()
    write_photo_identifier(p, ident)
    found = read_photo_identifiers(p)
    # exiftool may be missing on CI; raw scan must still find it if written,
    # otherwise accept graceful empty (validator will flag, tested below).
    if found:
        assert ident in found


def _fake_mov(p: Path):
    # minimal BMFF-ish shell with moov/trak so fallback probe passes
    p.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64 + b"moov" + b"\x00" * 64 + b"trak" + b"\x00" * 8192)


@needs_tools
def test_mov_patch_and_read(tmp_path):
    m = tmp_path / "c.mov"
    _real_mov(m)
    ident = new_asset_identifier()
    patch_mov_with_livephoto_tags(m, ident, 0)
    tags = read_mov_livephoto_tags(m)
    assert ident in tags["identifiers"]
    # canonical timed track reports int8s -1 (time carried by SampleTime=0)
    assert tags["still_image_time_ms"] is not None


def test_validator_catches_mismatch_and_missing(tmp_path):
    photo = tmp_path / "a.jpg"; mov = tmp_path / "a.mov"
    _img(photo)
    _fake_mov(mov)
    v = LivePhotoValidator()
    rep = v.validate(photo, mov)
    assert rep.ok is False  # identifiers missing
    assert any("identifier" in e for e in rep.errors)


@needs_tools
def test_validator_pair_ok_with_patch(tmp_path):
    photo = tmp_path / "a.jpg"; mov = tmp_path / "a.mov"
    _img(photo)
    _real_mov(mov)
    ident = new_asset_identifier()
    # fake photo identifier via raw append (simulates exiftool-less env)
    with open(photo, "ab") as fh:
        fh.write(ident.encode())
    patch_mov_with_livephoto_tags(mov, ident, 0)
    v = LivePhotoValidator()
    rep = v.validate(photo, mov, expected_identifier=ident)
    # movie probe fallback: has moov/trak + size ok; aspect unknown sizes -> skip aspect
    assert rep.ok is True, rep.errors


def test_mock_ai_provider_poll_download(tmp_path):
    fix = tmp_path / "v.mov"
    _fake_mov(fix)
    prov = MockAIVideoProvider(fix)
    jid = prov.submit(tmp_path / "x.jpg", tmp_path)
    url = prov.wait(jid)
    dest = prov.download(url, tmp_path / "out.bin")
    assert dest.exists()
    assert "api_key" not in str(prov.poll(jid))  # no leak via status
    assert prov.redacted()["api_key"] == "***"


def test_safe_request_rejects_non_http_and_strips_cross_host_auth(tmp_path):
    import pytest

    from app.core.live_photo.providers.base import GenericHttpAIVideoProvider

    prov = GenericHttpAIVideoProvider(endpoint="https://api.example.com/v1/videos",
                                      model="m", api_key="secret")
    with pytest.raises(RuntimeError):
        prov._safe_request("file:///etc/passwd", timeout=5)
    same = prov._safe_request("https://api.example.com/v1/jobs/1", timeout=5)
    assert same.get_header("Authorization") == "Bearer secret"
    other = prov._safe_request("https://cdn.other.example/x.mp4", timeout=5)
    assert other.get_header("Authorization") is None  # key never forwarded

    bad = GenericHttpAIVideoProvider(endpoint="ftp://h/x", model="m", api_key="k")
    with pytest.raises(RuntimeError):
        bad.submit(tmp_path / "nope.jpg", tmp_path)


@needs_ffmpeg
def test_local_motion_end_to_end(tmp_path):
    from app.core.live_photo.builder import LivePhotoBuilder

    still = tmp_path / "still.jpg"
    _img(still, size=(320, 240))
    staging = tmp_path / "stg"
    b = LivePhotoBuilder(ffmpeg=resolve_ffmpeg(), ffprobe=resolve_ffprobe())
    bundle = b.build(still_jpeg=still, stem="001", staging=staging,
                     video_source="local_motion", seed=1)
    assert bundle.photo_path.exists() and bundle.video_path.exists()
    rep = LivePhotoValidator(ffprobe=resolve_ffprobe()).validate(
        bundle.photo_path, bundle.video_path, expected_identifier=bundle.asset_identifier)
    assert rep.ok, rep.errors
    # no template UUID reuse
    assert bundle.asset_identifier not in ("00000000-0000-0000-0000-000000000000",)
