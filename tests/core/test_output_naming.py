"""Committed output naming contract.

i4Tools (爱思助手) matches a Live Photo pair with a CASE-SENSITIVE extension
check. A bundle whose bytes are perfect but whose names are written lowercase
("x.jpg" + "x.mov") is skipped before it ever reaches the pairing stage, while
the same bundle named "x.JPG" + "x.MOV" imports as a Live Photo. These tests
pin the casing so a refactor cannot quietly reintroduce the silent rejection.
"""
from pathlib import Path

import pytest

from app.core.output_format import OUTPUT_JPG_EXT, OUTPUT_MOV_EXT, strip_jpg_ext, strip_mov_ext


def test_extensions_are_uppercase():
    # Verified on device: 爱思助手 imports ".JPG"/".MOV" and skips the rest.
    assert OUTPUT_JPG_EXT == ".JPG"
    assert OUTPUT_MOV_EXT == ".MOV"


def test_live_photo_bundle_is_written_uppercase(tmp_path):
    from PIL import Image

    from app.config.schema import default_config
    from app.core.pipeline import run_job

    src, out = tmp_path / "in", tmp_path / "out"
    src.mkdir()
    Image.new("RGB", (64, 64), (200, 30, 30)).save(src / "a.jpg", "JPEG")
    cfg = default_config()
    cfg.output.subfolder_per_run = False
    cfg.steps.live_photo.enabled = True
    cfg.steps.hidden_image.enabled = False

    result = run_job(cfg, [src], output_dir=out, seed=1,
                     temp_base=tmp_path / "tmp", dry_run=False)

    jpgs = sorted(out.glob(f"*{OUTPUT_JPG_EXT}"))
    movs = sorted(out.glob(f"*{OUTPUT_MOV_EXT}"))
    assert (result.success_count, result.failure_count) == (1, 0)
    assert len(jpgs) == 1 and len(movs) == 1
    # the pair shares one stem - that is how 爱思助手 pairs them
    assert jpgs[0].stem == movs[0].stem
    # and nothing was left behind in the other casing
    assert list(out.glob("*.jpg")) == [] and list(out.glob("*.mov")) == []


def test_non_live_photo_output_is_uppercase(tmp_path):
    from PIL import Image

    from app.config.schema import default_config
    from app.core.pipeline import run_job

    src, out = tmp_path / "in", tmp_path / "out"
    src.mkdir()
    Image.new("RGB", (64, 64), (200, 30, 30)).save(src / "a.jpg", "JPEG")
    cfg = default_config()
    cfg.output.subfolder_per_run = False
    cfg.steps.live_photo.enabled = False
    cfg.steps.hidden_image.enabled = False

    run_job(cfg, [src], output_dir=out, seed=1,
            temp_base=tmp_path / "tmp", dry_run=False)

    assert len(list(out.glob(f"*{OUTPUT_JPG_EXT}"))) == 1
    assert list(out.glob("*.jpg")) == []


def test_rename_off_still_normalizes_extension(tmp_path):
    """With rename disabled the original stem is kept, but the extension is
    still the committed one."""
    from PIL import Image

    from app.config.schema import default_config
    from app.core.pipeline import run_job

    src, out = tmp_path / "in", tmp_path / "out"
    src.mkdir()
    Image.new("RGB", (64, 64), (200, 30, 30)).save(src / "keepme.jpg", "JPEG")
    cfg = default_config()
    cfg.output.subfolder_per_run = False
    cfg.steps.rename.enabled = False
    cfg.steps.device_metadata.enabled = False
    cfg.steps.hidden_image.enabled = False

    run_job(cfg, [src], output_dir=out, seed=1,
            temp_base=tmp_path / "tmp", dry_run=False)

    assert (out / f"keepme{OUTPUT_JPG_EXT}").exists()


@pytest.mark.parametrize("name,expected", [
    ("001.jpg", "001"),
    ("001.JPG", "001"),
    ("001.Jpg", "001"),
    ("001", "001"),
    ("a.b.jpg", "a.b"),
    ("001.mov", "001.mov"),
])
def test_strip_jpg_ext(name, expected):
    assert strip_jpg_ext(name) == expected


@pytest.mark.parametrize("name,expected", [
    ("001.MOV", "001"),
    ("001.mov", "001"),
    ("001", "001"),
    ("001.JPG", "001.JPG"),
])
def test_strip_mov_ext(name, expected):
    assert strip_mov_ext(name) == expected


def test_output_name_survives_a_round_trip(tmp_path):
    """rename -> live_photo -> output_write must not accumulate extensions."""
    from app.core.output_format import OUTPUT_JPG_EXT as EXT

    stem = strip_jpg_ext(f"photo{EXT}")           # rename produced "photo.JPG"
    assert strip_mov_ext(stem) == "photo"
    assert f"{stem}{EXT}" == f"photo{EXT}"        # output_write re-adds once


def test_conflict_rename_keeps_bundle_casing(tmp_path):
    """The rename-on-conflict path must stay a pair, in the same casing."""
    from app.core.conflicts import ConflictPolicy
    from app.core.steps.output_write import _resolve_bundle

    jpg = tmp_path / f"001{OUTPUT_JPG_EXT}"
    mov = tmp_path / f"001{OUTPUT_MOV_EXT}"
    jpg.write_bytes(b"x")
    mov.write_bytes(b"x")

    c_jpg, c_mov = _resolve_bundle(jpg, mov, ConflictPolicy.RENAME)

    assert c_jpg.suffix == OUTPUT_JPG_EXT
    assert c_mov.suffix == OUTPUT_MOV_EXT
    assert c_jpg.stem == c_mov.stem
    assert Path(c_jpg).parent == tmp_path
