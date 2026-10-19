"""Output format invariant: a committed output is always real JPEG bytes.

The promise breaks when every re-encoding step is off: source bytes pass
through unchanged, so a TIFF/PNG payload lands in a file named `*.jpg`.
Preflight refuses up front; output_write refuses to publish what slips past.
"""
from pathlib import Path

import pytest
from PIL import Image

from app.config.schema import default_config
from app.core.models import FileRecord, JobWorkspace
from app.core.output_format import (
    OUTPUT_JPG_EXT,
    is_jpeg_file,
    non_jpeg_records,
    pipeline_produces_jpeg,
)
from app.core.pipeline import run_job
from app.core.steps.base import StepContext
from app.core.steps.output_write import OutputWriteStep


def _config(**flags):
    """default_config() with the four format-relevant steps set by keyword;
    provenance_cleanup / device_metadata stay off (neither re-encodes, and both
    would need an optional dependency)."""
    cfg = default_config()
    cfg.steps.reencode.enabled = flags.get("reencode", True)
    cfg.steps.rotate_crop.enabled = flags.get("rotate_crop", False)
    cfg.steps.hidden_image.enabled = flags.get("hidden_image", False)
    cfg.steps.live_photo.enabled = flags.get("live_photo", False)
    cfg.steps.output_write.enabled = flags.get("output_write", True)
    cfg.steps.provenance_cleanup.enabled = False
    cfg.steps.device_metadata.enabled = False
    return cfg


# --- is_jpeg_file: magic bytes only, extension deliberately ignored -------

@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "TIFF", "BMP"])
def test_is_jpeg_file_reads_magic_not_extension(tmp_path, fmt):
    """Every fixture is *named* .jpg: only the real JPEG may pass."""
    path = tmp_path / f"payload_{fmt}.jpg"
    Image.new("RGB", (16, 16), (5, 6, 7)).save(path, fmt)
    assert is_jpeg_file(path) is (fmt == "JPEG")


def test_is_jpeg_file_rejects_empty_missing_and_directory(tmp_path):
    empty = tmp_path / "empty.jpg"; empty.write_bytes(b"")
    assert is_jpeg_file(empty) is False          # too short for a SOI marker
    assert is_jpeg_file(str(tmp_path / "missing.jpg")) is False  # str input, OSError
    assert is_jpeg_file(tmp_path) is False       # a directory is not a JPEG either


# --- pipeline_produces_jpeg: which configurations guarantee the bytes ------

@pytest.mark.parametrize("flags,expected", [
    ({}, True),                                             # default: reencode on
    ({"reencode": False}, False),                           # nothing re-encodes
    ({"reencode": False, "rotate_crop": True}, True),
    ({"reencode": False, "hidden_image": True}, True),
    # live_photo does NOT re-encode: the builder only renames the still to
    # .jpg (app/core/live_photo/builder.py), so it must not count as
    # JPEG-producing — otherwise turning Live Photo on would silently allow a
    # TIFF/PNG input that preflight otherwise refuses.
    ({"reencode": False, "live_photo": True}, False),
    ({"reencode": False, "live_photo": True, "output_write": False}, False),
])
def test_pipeline_produces_jpeg_truth_table(flags, expected):
    assert pipeline_produces_jpeg(_config(**flags)) is expected


def _records(tmp_path: Path) -> list[FileRecord]:
    """Mixed extensions: note `tif` has no dot and `.JPEG` is dotted."""
    specs = [("a.jpg", "jpg"), ("b.JPG", ".JPEG"), ("c.png", "png"),
             ("d.tif", "tif"), ("e.bmp", "bmp"), ("f.webp", "webp")]
    records = []
    for index, (name, ext) in enumerate(specs, start=1):
        src = tmp_path / name; src.write_bytes(b"payload")
        records.append(FileRecord(source_path=src, current_path=src,
                                  original_name=Path(name).stem,
                                  original_ext=ext, index=index))
    return records


def test_non_jpeg_records_lists_pass_through_inputs_when_no_reencoding(tmp_path):
    """Everything but jpg/jpeg survives verbatim, in record order."""
    got = non_jpeg_records(_records(tmp_path), _config(reencode=False))
    assert [p.name for p in got] == ["c.png", "d.tif", "e.bmp", "f.webp"]


def test_non_jpeg_records_empty_when_a_step_guarantees_jpeg(tmp_path):
    assert non_jpeg_records(_records(tmp_path), _config(reencode=True)) == []


# --- End to end through run_job ------------------------------------------

def _mixed_inputs(d: Path) -> None:
    d.mkdir(parents=True, exist_ok=True)
    for name, fmt, color in [("a.jpg", "JPEG", (200, 30, 30)),
                             ("b.png", "PNG", (30, 200, 30)),
                             ("c.tif", "TIFF", (30, 30, 200))]:
        Image.new("RGB", (64, 64), color).save(d / name, fmt)


def _run(cfg, src, out, tmp_path):
    """run_job with the job's temp base pinned inside tmp_path, as tests do.

    Output stays flat: these tests are about file *format*, and the per-run
    timestamped folder is covered by tests/core/test_output_paths.py.
    """
    cfg.output.subfolder_per_run = False
    cfg.paths.temp_dir = str(tmp_path / "tmp")
    return run_job(cfg, [src], output_dir=out, seed=1, temp_base=tmp_path / "tmp")


def test_preflight_refuses_non_jpeg_inputs_when_nothing_reencodes(tmp_path):
    src, out = tmp_path / "in", tmp_path / "out"
    _mixed_inputs(src); out.mkdir()

    result = _run(_config(reencode=False), src, out, tmp_path)

    assert result.preflight_failed is True
    assert "本次产物要求为 JPG" in result.preflight_error
    # The message names what went wrong, not just that something did.
    assert "b.png" in result.preflight_error and "c.tif" in result.preflight_error
    assert sorted(Path(p).name for p in result.preflight_extra["non_jpeg"]) == ["b.png", "c.tif"]
    # Refused before any side effect: no outputs, no source deletion.
    assert list(out.iterdir()) == []
    assert result.success_count == 0 and result.failure_count == 0
    assert all((src / n).exists() for n in ("a.jpg", "b.png", "c.tif"))


def test_non_jpeg_inputs_become_real_jpegs_when_reencode_is_on(tmp_path):
    src, out = tmp_path / "in", tmp_path / "out"
    _mixed_inputs(src); out.mkdir()

    result = _run(_config(reencode=True), src, out, tmp_path)

    assert result.preflight_failed is False
    assert result.failure_count == 0 and result.success_count == 3
    outputs = sorted(out.glob(f"*{OUTPUT_JPG_EXT}")); assert len(outputs) == 3
    for path in outputs:
        assert is_jpeg_file(path), f"{path.name} does not start with the JPEG SOI marker"
        with Image.open(path) as im:
            assert im.format == "JPEG", f"{path.name} is {im.format}, not JPEG"
    assert (src / "b.png").exists()  # sources untouched


def test_jpeg_only_input_passes_through_with_every_step_off(tmp_path):
    """The guard must not fire on a batch that really is JPEG already."""
    src, out = tmp_path / "in", tmp_path / "out"
    src.mkdir(); out.mkdir()
    Image.new("RGB", (64, 64), (200, 30, 30)).save(src / "a.jpg", "JPEG")
    Image.new("RGB", (64, 64), (30, 200, 30)).save(src / "b.jpg", "JPEG")

    result = _run(_config(reencode=False), src, out, tmp_path)

    assert result.preflight_failed is False
    assert result.failure_count == 0 and result.success_count == 2
    outputs = sorted(out.glob(f"*{OUTPUT_JPG_EXT}")); assert len(outputs) == 2
    for path in outputs:
        with Image.open(path) as im:
            assert im.format == "JPEG"


# --- output_write refuses to publish non-JPEG bytes ----------------------

def _write_ctx(tmp_path: Path, out: Path, current: Path) -> StepContext:
    """Record at `current`, asked to publish itself as `x.jpg` in `out`."""
    root = tmp_path / "job"
    return StepContext(
        config=_config(reencode=False),
        workspace=JobWorkspace(job_id="t", temp_root=root, incoming=root / "incoming",
                              work=root / "work", staging=root / "staging"),
        record=FileRecord(source_path=current, current_path=current,
                          original_name=current.stem, original_ext="jpg",
                          index=1, output_name="x.jpg"),
        resources={"output_dir": out},
    )


def test_output_write_refuses_png_bytes_named_jpg(tmp_path):
    """A record that slipped past Preflight still must not be published."""
    out = tmp_path / "out"; out.mkdir()
    lying = tmp_path / "lying.jpg"
    Image.new("RGB", (16, 16), (9, 9, 9)).save(lying, "PNG")
    assert lying.read_bytes()[:4] == b"\x89PNG", "fixture must be PNG bytes under a .jpg name"
    ctx = _write_ctx(tmp_path, out, lying)

    result = OutputWriteStep().run(ctx)

    assert result.ok is False
    assert "拒绝输出非 JPEG" in (result.error or "")
    assert list(out.iterdir()) == []
    assert ctx.record.output_path is None
    assert ctx.record.output_paths == []


def test_output_write_accepts_real_jpeg(tmp_path):
    """Mirror of the case above: the guard must not block a valid write."""
    out = tmp_path / "out"; out.mkdir()
    src = tmp_path / "photo.jpg"
    Image.new("RGB", (16, 16), (9, 9, 9)).save(src, "JPEG")
    ctx = _write_ctx(tmp_path, out, src)

    result = OutputWriteStep().run(ctx)

    assert result.ok is True, result.error
    assert ctx.record.output_path == out / "x.jpg"
    with Image.open(ctx.record.output_path) as im:
        assert im.format == "JPEG"