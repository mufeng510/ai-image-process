"""Rotate/crop: aspect preserved, no borders, angle coverage."""
import math

import pytest
from PIL import Image

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
