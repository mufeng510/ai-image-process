from pathlib import Path

from PIL import Image

from app.config.schema import default_config
from app.core.pipeline import run_job


def test_pipeline_smoke(tmp_path: Path):
    src = tmp_path / "in"
    out = tmp_path / "out"
    src.mkdir(); out.mkdir()
    img = src / "sample.png"
    Image.new("RGB", (64, 64), color=(20, 40, 60)).save(img)

    cfg = default_config()
    cfg.steps.provenance_cleanup.enabled = False  # optional dep
    cfg.steps.device_metadata.enabled = False  # may lack exiftool on linux CI
    cfg.runtime.cleanup_temp_on_success = True
    cfg.paths.temp_dir = str(tmp_path / "tmp")

    result = run_job(cfg, [src], output_dir=out, seed=42, temp_base=tmp_path / "tmp")
    assert result.failure_count == 0
    assert result.success_count == 1
    outputs = list(out.glob("*.jpg"))
    assert len(outputs) == 1
    assert outputs[0].stat().st_size > 0
    # source preserved
    assert img.exists()
