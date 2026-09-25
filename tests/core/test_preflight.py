"""Preflight unit tests: basenames shared, empty task, disabled steps skip."""
import random
from pathlib import Path

from PIL import Image

from app.config.schema import default_config
from app.core.models import FileRecord
from app.core.preflight import run_preflight
from app.core.steps.input_normalize import collect_inputs, to_records
from app.core.steps.deduplicate import deduplicate_records


def _img(p: Path, color=(9, 9, 9)):
    Image.new("RGB", (32, 32), color).save(p)


def test_basenames_shared_and_unique(tmp_path):
    src = tmp_path / "in"; src.mkdir()
    _img(src / "a.jpg", color=(9, 9, 9)); _img(src / "b.jpg", color=(10, 11, 12))
    cfg = default_config()
    cfg.naming.template = "IMG_{number}"
    recs = to_records(collect_inputs([src], cfg))
    recs, _ = deduplicate_records(recs, "md5")
    pf = run_preflight(cfg, [src], recs, tmp_path / "out", random.Random(0))
    assert pf.ok
    assert set(pf.basenames.values()) == {"IMG_001", "IMG_002"}


def test_empty_task_not_blocked_by_empty_library(tmp_path):
    src = tmp_path / "in"; src.mkdir()
    cfg = default_config()
    cfg.steps.hidden_image.enabled = True
    cfg.steps.hidden_image.library_dir = str(tmp_path / "lib")
    pf = run_preflight(cfg, [src], [], tmp_path / "out", random.Random(0))
    assert pf.ok


def test_hidden_off_skips_library_checks(tmp_path):
    src = tmp_path / "in"; src.mkdir()
    _img(src / "a.jpg")
    cfg = default_config()
    cfg.steps.hidden_image.enabled = False
    cfg.steps.hidden_image.library_dir = "/nonexistent"
    recs = to_records(collect_inputs([src], cfg))
    pf = run_preflight(cfg, [src], recs, tmp_path / "out", random.Random(0))
    assert pf.ok


def test_live_photo_local_requires_ffmpeg_or_ok(tmp_path, monkeypatch):
    import app.core.ffmpeg_resolver as fr

    src = tmp_path / "in"; src.mkdir()
    _img(src / "a.jpg", color=(1, 2, 3))
    cfg = default_config()
    cfg.steps.live_photo.enabled = True
    cfg.steps.live_photo.video_source = "local_motion"
    recs = to_records(collect_inputs([src], cfg))

    monkeypatch.setattr(fr, "resolve_ffmpeg", lambda: None)
    pf = run_preflight(cfg, [src], recs, tmp_path / "out", random.Random(0))
    assert pf.ok is False and "FFmpeg" in pf.error

    monkeypatch.setattr(fr, "resolve_ffmpeg", lambda: tmp_path / "ffmpeg")
    pf = run_preflight(cfg, [src], recs, tmp_path / "out", random.Random(0))
    assert pf.ok is True


def test_symlinked_input_into_library_refused(tmp_path):
    import pytest

    lib = tmp_path / "lib"; lib.mkdir()
    real = lib / "real.jpg"
    Image.new("RGB", (32, 32), (1, 2, 3)).save(real)
    linkdir = tmp_path / "in"; linkdir.mkdir()
    link = linkdir / "link.jpg"
    try:
        link.symlink_to(real)
    except OSError:
        pytest.skip("symlinks unavailable")
    cfg = default_config()
    cfg.steps.hidden_image.enabled = True
    cfg.steps.hidden_image.library_dir = str(lib)
    recs = to_records(collect_inputs([linkdir], cfg))
    assert len(recs) == 1
    pf = run_preflight(cfg, [linkdir], recs, tmp_path / "out", random.Random(0))
    assert pf.ok is False and "符号链接" in pf.error


def test_rename_off_keeps_original_stems(tmp_path):
    src = tmp_path / "in"; src.mkdir()
    _img(src / "a_keep.jpg", color=(1, 2, 3))
    _img(src / "b_keep.jpg", color=(4, 5, 6))
    cfg = default_config()
    cfg.steps.rename.enabled = False
    cfg.naming.template = "SHOULD_NOT_APPLY_{number}"
    recs = to_records(collect_inputs([src], cfg))
    pf = run_preflight(cfg, [src], recs, tmp_path / "out", random.Random(0))
    assert pf.ok
    assert set(pf.basenames.values()) == {"a_keep", "b_keep"}


def test_ai_mode_requires_provider_config(tmp_path):
    src = tmp_path / "in"; src.mkdir()
    _img(src / "a.jpg")
    cfg = default_config()
    cfg.steps.live_photo.enabled = True
    cfg.steps.live_photo.video_source = "ai_video"
    recs = to_records(collect_inputs([src], cfg))
    pf = run_preflight(cfg, [src], recs, tmp_path / "out", random.Random(0))
    assert pf.ok is False
