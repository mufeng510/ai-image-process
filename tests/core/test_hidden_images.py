"""Hidden library: scan, assignment, safety, composite, precheck."""
import random
from pathlib import Path

from PIL import Image

from app.config.schema import default_config
from app.core.hidden_images import (
    assign_hidden_images,
    check_hidden_library_path_safety,
    delete_hidden_image,
    scan_hidden_library,
)
from app.core.pipeline import run_job
from app.core.steps.hidden_image import composite_cover


def _img(p: Path, size=(100, 100), color=(10, 20, 30)):
    Image.new("RGB", size, color).save(p)


_COLORS = [(10, 20, 30), (40, 50, 60), (70, 80, 90), (100, 110, 120)]


def test_scan_counts_only_usable(tmp_path):
    lib = tmp_path / "lib"; lib.mkdir()
    _img(lib / "a.jpg")
    _img(lib / "b.png")
    (lib / "note.txt").write_text("x")
    (lib / "sub").mkdir()
    _img(lib / "sub" / "nested.jpg")  # direct-only: must NOT count
    (lib / "bad.jpg").write_bytes(b"not an image")
    pool = scan_hidden_library(lib, {"jpg", "jpeg", "png", "webp"})
    assert {p.name for p in pool} == {"a.jpg", "b.png"}


def test_scan_webp_png_jpeg(tmp_path):
    lib = tmp_path / "lib"; lib.mkdir()
    _img(lib / "a.jpg")
    Image.new("RGB", (40, 40), (1, 1, 1)).save(lib / "b.png")
    Image.new("RGB", (40, 40), (2, 2, 2)).save(lib / "c.webp")
    pool = scan_hidden_library(lib, {"jpg", "jpeg", "png", "webp"})
    assert len(pool) == 3


def test_assignment_no_reuse_reproducible(tmp_path):
    srcs = [tmp_path / f"{c}.jpg" for c in "ABCD"]
    pool = [tmp_path / f"h{i}.jpg" for i in range(4)]
    m1 = assign_hidden_images(srcs, pool, random.Random(7)).mapping
    m2 = assign_hidden_images(srcs, pool, random.Random(7)).mapping
    assert m1 == m2
    assert len(set(map(str, m1.values()))) == 4


def test_path_safety(tmp_path):
    inp = tmp_path / "in"; out = tmp_path / "out"; lib = tmp_path / "lib"
    for d in (inp, out, lib):
        d.mkdir()
    assert check_hidden_library_path_safety(lib, [inp], out) is None
    assert check_hidden_library_path_safety(inp, [inp], out) is not None
    assert check_hidden_library_path_safety(out, [inp], out) is not None
    assert check_hidden_library_path_safety(inp / "sub", [inp], out) is not None
    assert check_hidden_library_path_safety(lib, [lib], out) is not None


def test_composite_cover_no_stretch(tmp_path):
    main = tmp_path / "main.jpg"; hid = tmp_path / "hid.jpg"; dest = tmp_path / "o.jpg"
    _img(main, size=(300, 200), color=(200, 0, 0))
    _img(hid, size=(100, 400), color=(0, 0, 200))
    composite_cover(main, hid, dest, 0.02)
    with Image.open(dest) as im:
        assert im.size == (300, 200)
        # opacity applied: pixel differs slightly from pure red
        px = im.getpixel((150, 100))
        assert px[0] > 150 and px[2] > 0


def test_precheck_blocks_and_never_partial(tmp_path):
    src = tmp_path / "in"; out = tmp_path / "out"; lib = tmp_path / "lib"
    src.mkdir(); out.mkdir(); lib.mkdir()
    for i in range(3):
        _img(src / f"s{i}.jpg", color=_COLORS[i])
    _img(lib / "h0.jpg")
    _img(lib / "h1.jpg")  # need 3, have 2
    cfg = default_config()
    cfg.steps.provenance_cleanup.enabled = False
    cfg.steps.device_metadata.enabled = False
    cfg.steps.hidden_image.enabled = True
    cfg.steps.hidden_image.library_dir = str(lib)
    cfg.paths.temp_dir = str(tmp_path / "tmp")
    r = run_job(cfg, [src], output_dir=out, seed=3, temp_base=tmp_path / "tmp")
    assert r.preflight_failed is True
    assert "数量不足" in (r.preflight_error or "")
    assert list(out.glob("*")) == []
    assert (lib / "h0.jpg").exists() and (lib / "h1.jpg").exists()


def test_exact_count_passes_and_deletes_on_success(tmp_path):
    src = tmp_path / "in"; out = tmp_path / "out"; lib = tmp_path / "lib"
    src.mkdir(); out.mkdir(); lib.mkdir()
    for i in range(2):
        _img(src / f"s{i}.jpg", color=_COLORS[i])
        _img(lib / f"h{i}.jpg", color=_COLORS[i + 2])
    cfg = default_config()
    cfg.steps.provenance_cleanup.enabled = False
    cfg.steps.device_metadata.enabled = False
    cfg.steps.hidden_image.enabled = True
    cfg.steps.hidden_image.library_dir = str(lib)
    cfg.paths.temp_dir = str(tmp_path / "tmp")
    r = run_job(cfg, [src], output_dir=out, seed=3, temp_base=tmp_path / "tmp")
    assert r.preflight_failed is False and r.failure_count == 0
    assert list(lib.glob("*")) == []  # consumed permanently


def test_failed_file_retains_hidden(tmp_path):
    from app.core.hidden_images import scan_hidden_library

    src = tmp_path / "in"; out = tmp_path / "out"; lib = tmp_path / "lib"
    src.mkdir(); out.mkdir(); lib.mkdir()
    _img(src / "good.jpg")
    (src / "bad.jpg").write_bytes(b"corrupt!")
    _img(lib / "h0.jpg"); _img(lib / "h1.jpg")
    cfg = default_config()
    cfg.steps.provenance_cleanup.enabled = False
    cfg.steps.device_metadata.enabled = False
    cfg.steps.hidden_image.enabled = True
    cfg.steps.hidden_image.library_dir = str(lib)
    cfg.paths.temp_dir = str(tmp_path / "tmp")
    r = run_job(cfg, [src], output_dir=out, seed=3, temp_base=tmp_path / "tmp")
    # good file consumed exactly one hidden image; failed file's hidden retained
    assert len(list(lib.glob("*"))) == 1


def test_delete_boundary(tmp_path):
    lib = tmp_path / "lib"; lib.mkdir()
    other = tmp_path / "other"; other.mkdir()
    h = lib / "h.jpg"; _img(h)
    o = other / "o.jpg"; _img(o)
    import pytest

    delete_hidden_image(h, lib)
    assert not h.exists()
    with pytest.raises(PermissionError):
        delete_hidden_image(o, lib)
