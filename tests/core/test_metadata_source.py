"""Metadata source priority + regression (EXIF/ICC survive transforms)."""
from pathlib import Path

from PIL import Image

from app.config.schema import default_config
from app.core.image_metadata import build_device_tags, extract_hidden_metadata_source
from app.core.pipeline import run_job


def _img(p: Path, size=(120, 90)):
    Image.new("RGB", size, (50, 60, 70)).save(p)


def test_hidden_source_allowlist_no_gps(tmp_path):
    from PIL import Image as I
    from PIL.ExifTags import TAGS

    hid = tmp_path / "hid.jpg"
    exif = I.Exif()
    exif[271] = "Apple"
    exif[272] = "iPhone 15"
    exif[34855] = 200
    im = I.new("RGB", (80, 60), (1, 2, 3))
    im.save(hid, exif=exif)
    src = extract_hidden_metadata_source(hid)
    assert src.get("Make") == "Apple"
    assert "GPSLatitude" not in src and "GPSInfo" not in src


def test_fallback_without_hidden_exif(tmp_path):
    hid = tmp_path / "plain.jpg"
    _img(hid)
    src = extract_hidden_metadata_source(hid)
    tags = build_device_tags(make="Apple", model="iPhone 14", lens="Test",
                             when=__import__("datetime").datetime(2024, 1, 2, 3, 4, 5),
                             software="iOS Camera", hidden_src=src)
    assert tags["Model"] == "iPhone 14"  # fallback intact


def test_randomize_off_never_copies_hidden_time():
    import random
    from datetime import datetime

    from app.core.image_metadata import resolve_capture_datetime

    before = datetime.now()
    got = resolve_capture_datetime({"HiddenDateTime": "2020:01:01 00:00:00"},
                                   False, 10, 10000, random.Random(0))
    after = datetime.now()
    assert before <= got <= after  # now(), not the hidden 2020 time


def test_metadata_survives_rotate_and_hidden(tmp_path):
    src = tmp_path / "in"; out = tmp_path / "out"; lib = tmp_path / "lib"
    src.mkdir(); out.mkdir(); lib.mkdir()
    _img(src / "s.jpg", size=(200, 150))
    _img(lib / "h.jpg", size=(100, 100))
    cfg = default_config()
    cfg.steps.provenance_cleanup.enabled = False
    cfg.steps.visible_watermark.enabled = False
    cfg.steps.rotate_crop.enabled = True
    cfg.steps.rotate_crop.min_angle = 1.0
    cfg.steps.rotate_crop.max_angle = 1.0
    cfg.steps.hidden_image.enabled = True
    cfg.steps.hidden_image.library_dir = str(lib)
    cfg.paths.temp_dir = str(tmp_path / "tmp")
    r = run_job(cfg, [src], output_dir=out, seed=11, temp_base=tmp_path / "tmp")
    assert r.failure_count == 0
    outs = list(out.glob("*.jpg"))
    assert len(outs) == 1
    with Image.open(outs[0]) as im:
        assert abs((im.size[0] / im.size[1]) - (200 / 150)) / (200 / 150) < 0.02  # aspect kept
        exif = im.getexif()
        assert len(exif) > 0  # device tags survived Pillow transforms
