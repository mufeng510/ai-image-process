"""Rotate/crop: aspect preserved, no borders, angle coverage."""
import math

import pytest
from PIL import Image, ImageStat

from app.config.schema import default_config
from app.core.pipeline import run_job
from app.core.steps.base import StepContext
from app.core.steps.rotate_crop import RotateCropStep, largest_axis_aligned_rect
from app.core.models import JobWorkspace


@pytest.mark.parametrize("size", [(200, 200), (400, 300), (300, 400), (640, 360),
                                  (360, 640), (800, 200), (200, 800)])
@pytest.mark.parametrize("angle", [0.0, 1.37, -1.5, 0.3, -0.2])
def test_aspect_preserved(tmp_path, size, angle):
    from app.core.temp_manager import TempManager

    src = tmp_path / "in.jpg"
    Image.new("RGB", size, (120, 130, 140)).save(src)
    cfg = default_config()
    cfg.steps.rotate_crop.enabled = True
    cfg.steps.rotate_crop.min_angle = angle
    cfg.steps.rotate_crop.max_angle = angle
    step = RotateCropStep()
    mgr = TempManager(tmp_path / "t")
    ws = mgr.create_job_workspace("r")
    from app.core.models import FileRecord

    rec = FileRecord(source_path=src, current_path=src, original_name="in",
                     original_ext="jpg", index=1)
    import random

    res = step.run(StepContext(config=cfg, workspace=ws, record=rec,
                               resources={"rng": random.Random(0)}))
    assert res.ok, res.error
    with Image.open(rec.current_path) as out:
        ow, oh = out.size
        # no transparency / borders: corners must be non-black content-ish
        px = out.getpixel((2, 2))
        assert sum(px) > 0
    orig_ratio = size[0] / size[1]
    assert abs((ow / oh) - orig_ratio) / orig_ratio < 0.06


def test_largest_rect_degenerate():
    assert largest_axis_aligned_rect(100, 100, 0.0) == (100, 100)


# --- landscape crop must never reach past the rotated canvas ---------------
# `fits()` used to take the y extreme as `-x*sin + y*cos`, i.e. it validated
# one arbitrary corner instead of all four.  That only bites when w > h: the
# crop box came out wider than the rotated canvas and the result had black bars
# top and bottom.  Portrait sizes were untouched, which is why the old
# single-corner pixel probe in `test_aspect_preserved` never caught it.

LANDSCAPE_ANGLES = [2.0, -2.0, 1.7, 1.0]


def _run_rotate_at(tmp_path, size, angle):
    """Rotate/crop a flat mid-gray image at one fixed angle; returns output path."""
    from app.core.temp_manager import TempManager
    from app.core.models import FileRecord
    import random

    src = tmp_path / f"in_{size[0]}x{size[1]}_{angle}.jpg"
    Image.new("RGB", size, (128, 128, 128)).save(src)
    cfg = default_config()
    cfg.steps.rotate_crop.enabled = True
    cfg.steps.rotate_crop.min_angle = angle
    cfg.steps.rotate_crop.max_angle = angle
    ws = TempManager(tmp_path / f"t_{size[0]}x{size[1]}_{angle}").create_job_workspace("r")
    rec = FileRecord(source_path=src, current_path=src, original_name="in",
                     original_ext="jpg", index=1)
    res = RotateCropStep().run(StepContext(config=cfg, workspace=ws, record=rec,
                                           resources={"rng": random.Random(0)}))
    assert res.ok, res.error
    return rec.current_path


def _border_min_gray(img, bands=40):
    """Min luminance on a thin frame hugging all four edges of the image."""
    g = img.convert("L")
    w, h = g.size
    s = max(1, min(w, h) // bands)
    edges = (g.crop((0, 0, w, s)), g.crop((0, h - s, w, h)),
             g.crop((0, 0, s, h)), g.crop((w - s, 0, w, h)))
    return min(ImageStat.Stat(e).extrema[0][0] for e in edges)


@pytest.mark.parametrize("size,angle",
                         [(s, a) for s in [(900, 600), (1920, 1080)]
                          for a in LANDSCAPE_ANGLES]
                         + [((4032, 3024), 2.0)])
def test_landscape_no_black_border(tmp_path, size, angle):
    out = _run_rotate_at(tmp_path, size, angle)
    with Image.open(out) as im:
        ow, oh = im.size
        # Content is flat gray 128, so anything near 0 is a black border.
        # Probe a frame on all four sides -- the old probe looked at one corner.
        assert _border_min_gray(im) >= 100
    assert ow <= size[0] and oh <= size[1]
    assert (ow, oh) != size, "a non-zero angle must still crop something"
    r0, r1 = size[0] / size[1], ow / oh
    assert abs(r1 - r0) / r0 < 0.02


def _half_extents(cw, ch, angle_deg):
    """Half-extents of a centered cw x ch rect inverse-rotated by -theta."""
    t = math.radians(abs(angle_deg) % 90.0)
    x, y = cw / 2.0, ch / 2.0
    return x * math.cos(t) + y * math.sin(t), x * math.sin(t) + y * math.cos(t)


@pytest.mark.parametrize("angle", [2.0, -2.0, 1.7, 1.0])
def test_largest_rect_landscape_corners_inside(angle):
    w, h = 900, 600
    cw, ch = largest_axis_aligned_rect(w, h, angle)
    assert cw < w and ch < h, "a non-zero angle must still crop something"
    xr, yr = _half_extents(cw, ch, angle)
    assert xr <= w / 2.0 + 1e-9, f"{cw}x{ch} reaches past {w}x{h} sideways"
    assert yr <= h / 2.0 + 1e-9, f"{cw}x{ch} reaches past {w}x{h} vertically"


def test_largest_rect_portrait_not_over_cropped():
    w, h = 600, 900
    cw, ch = largest_axis_aligned_rect(w, h, 2.0)
    # The sign fix only ever changed the w > h branch, so portrait must still
    # land on the pre-fix rect -- not a smaller one.
    assert (cw, ch) == (566, 849)
    xr, yr = _half_extents(cw, ch, 2.0)
    assert xr <= w / 2.0 + 1e-9 and yr <= h / 2.0 + 1e-9
    # Same 2:3 shape as (900, 600), so both must keep the same area fraction.
    # Before the fix landscape came out strictly larger in area than portrait,
    # i.e. the crop box ran outside the rotated canvas.
    lw, lh = largest_axis_aligned_rect(900, 600, 2.0)
    assert abs((cw * ch) / (w * h) - (lw * lh) / (900 * 600)) < 0.005


@pytest.mark.parametrize("angle", [0.0, -0.0])
def test_largest_rect_zero_angle_landscape(angle):
    assert largest_axis_aligned_rect(900, 600, angle) == (900, 600)


def test_step_independent_off(tmp_path):
    src = tmp_path / "in"; out = tmp_path / "out"
    src.mkdir(); out.mkdir()
    Image.new("RGB", (64, 64), (1, 2, 3)).save(src / "a.png")
    cfg = default_config()
    cfg.steps.provenance_cleanup.enabled = False
    cfg.steps.device_metadata.enabled = False
    cfg.steps.rotate_crop.enabled = False
    cfg.paths.temp_dir = str(tmp_path / "tmp")
    r = run_job(cfg, [src], output_dir=out, seed=1, temp_base=tmp_path / "tmp")
    assert r.failure_count == 0 and r.success_count == 1
