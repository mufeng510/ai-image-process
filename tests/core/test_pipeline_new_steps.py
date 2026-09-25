"""Pipeline combos: independence, bundle atomicity, defaults-off regression."""
from pathlib import Path

import pytest
from PIL import Image

from app.config.schema import default_config
from app.core.pipeline import DEFAULT_STEP_ORDER, build_default_registry, run_job
from app.core.ffmpeg_resolver import resolve_ffmpeg


def _img(p: Path, size=(160, 120), color=(30, 60, 90)):
    Image.new("RGB", size, color).save(p)


def _base_cfg(tmp_path, lib=None):
    src = tmp_path / "in"; out = tmp_path / "out"
    src.mkdir(exist_ok=True); out.mkdir(exist_ok=True)
    cfg = default_config()
    cfg.steps.provenance_cleanup.enabled = False
    cfg.steps.visible_watermark.enabled = False
    cfg.paths.temp_dir = str(tmp_path / "tmp")
    return cfg, src, out


def test_registry_order_and_titles():
    reg = build_default_registry()
    assert DEFAULT_STEP_ORDER == ["deduplicate", "rename", "provenance_cleanup",
                                  "visible_watermark", "reencode", "device_metadata",
                                  "rotate_crop", "hidden_image", "live_photo", "output_write"]
    ids = [s.id for s in reg.ordered(DEFAULT_STEP_ORDER)]
    assert ids == DEFAULT_STEP_ORDER
    assert reg.get("hidden_image").title == "隐藏图片"
    assert reg.get("rotate_crop").title == "图片旋转与裁剪"
    assert reg.get("live_photo").title == "生成 Apple Live Photo"


@pytest.mark.parametrize("rotate,hidden", [(False, False), (True, False), (True, True), (False, True)])
def test_step_combos_without_livephoto(tmp_path, rotate, hidden):
    cfg, src, out = _base_cfg(tmp_path)
    cfg.steps.device_metadata.enabled = False
    _img(src / "a.jpg")
    lib = tmp_path / "lib"; lib.mkdir()
    _img(lib / "h.jpg")
    cfg.steps.rotate_crop.enabled = rotate
    cfg.steps.hidden_image.enabled = hidden
    cfg.steps.hidden_image.library_dir = str(lib)
    r = run_job(cfg, [src], output_dir=out, seed=5, temp_base=tmp_path / "tmp")
    assert r.preflight_failed is False and r.failure_count == 0
    assert len(list(out.glob("*.jpg"))) == 1
    assert list(out.glob("*.mov")) == []


def test_defaults_off_regression_matches_legacy(tmp_path):
    cfg, src, out = _base_cfg(tmp_path)
    cfg.steps.device_metadata.enabled = False
    _img(src / "a.png")
    r = run_job(cfg, [src], output_dir=out, seed=42, temp_base=tmp_path / "tmp")
    assert r.success_count == 1 and r.preflight_failed is False
    assert len(list(out.glob("*.jpg"))) == 1 and len(list(out.glob("*.mov"))) == 0


@pytest.mark.skipif(resolve_ffmpeg() is None, reason="ffmpeg not available")
def test_live_photo_bundle_atomic_and_shared_basename(tmp_path):
    cfg, src, out = _base_cfg(tmp_path)
    cfg.steps.device_metadata.enabled = False
    cfg.steps.live_photo.enabled = True
    cfg.naming.template = "IMG_{number}"
    _img(src / "a.jpg", size=(320, 240))
    r = run_job(cfg, [src], output_dir=out, seed=5, temp_base=tmp_path / "tmp")
    assert r.failure_count == 0
    jpgs = sorted(out.glob("*.jpg")); movs = sorted(out.glob("*.mov"))
    assert len(jpgs) == 1 and len(movs) == 1
    assert jpgs[0].stem == movs[0].stem  # 001.jpg + 001.mov share basename


def test_livephoto_off_produces_no_mov(tmp_path):
    cfg, src, out = _base_cfg(tmp_path)
    cfg.steps.device_metadata.enabled = False
    _img(src / "a.jpg")
    r = run_job(cfg, [src], output_dir=out, seed=5, temp_base=tmp_path / "tmp")
    assert list(out.glob("*.mov")) == []


def test_output_off_keeps_staging_semantics(tmp_path):
    cfg, src, out = _base_cfg(tmp_path)
    cfg.steps.device_metadata.enabled = False
    cfg.steps.output_write.enabled = False
    _img(src / "a.jpg")
    r = run_job(cfg, [src], output_dir=out, seed=5, temp_base=tmp_path / "tmp")
    assert r.success_count == 1
    assert list(out.glob("*.jpg")) == []


def test_output_off_retains_hidden_images(tmp_path):
    cfg, src, out = _base_cfg(tmp_path)
    cfg.steps.device_metadata.enabled = False
    cfg.steps.output_write.enabled = False
    cfg.steps.hidden_image.enabled = True
    lib = tmp_path / "lib"; lib.mkdir()
    _img(src / "a.jpg", color=(30, 60, 90))
    _img(lib / "h.jpg", color=(31, 61, 91))
    cfg.steps.hidden_image.library_dir = str(lib)
    r = run_job(cfg, [src], output_dir=out, seed=5, temp_base=tmp_path / "tmp")
    assert r.success_count == 1  # steps ok, nothing committed
    assert (lib / "h.jpg").exists()  # retained: no committed output
    assert list(out.glob("*.jpg")) == []


def test_rename_off_uses_original_names(tmp_path):
    cfg, src, out = _base_cfg(tmp_path)
    cfg.steps.device_metadata.enabled = False
    cfg.steps.rename.enabled = False
    cfg.naming.template = "SHOULD_NOT_APPLY_{number}"
    _img(src / "keepme.jpg", color=(30, 60, 90))
    r = run_job(cfg, [src], output_dir=out, seed=5, temp_base=tmp_path / "tmp")
    assert r.success_count == 1
    assert (out / "keepme.jpg").exists()


def test_rename_after_dedup_shared_stem(tmp_path):
    cfg, src, out = _base_cfg(tmp_path)
    cfg.steps.device_metadata.enabled = False
    cfg.naming.template = "P_{number}"
    data = b"\x00" * 100
    _img(src / "a.jpg", color=(30, 60, 90)); _img(src / "b.jpg", color=(31, 61, 91))  # distinct
    r = run_job(cfg, [src], output_dir=out, seed=5, temp_base=tmp_path / "tmp")
    assert r.success_count == 2
    assert {p.stem for p in out.glob("*.jpg")} == {"P_001", "P_002"}


def test_cli_summary_flags(tmp_path):
    from app.main_cli import main

    src = tmp_path / "in"; out = tmp_path / "out"
    src.mkdir(); out.mkdir()
    _img(src / "a.jpg")
    rc = main([str(src), "-o", str(out), "--json-summary"])
    assert rc == 0
