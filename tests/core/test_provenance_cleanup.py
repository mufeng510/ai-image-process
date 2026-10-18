"""Tests for the provenance cleanup step."""
import builtins
import importlib
import shutil
import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image, PngImagePlugin

from app.config.schema import AppConfig, default_config
from app.core.models import FileRecord, JobWorkspace, StepResult
from app.core.steps.base import StepContext
from app.core.steps.provenance_cleanup import (
    ProvenanceCleanupStep,
    _run_remove_batch,
    _try_remove_ai_watermarks,
)


def _make_workspace(tmp_path: Path) -> JobWorkspace:
    root = tmp_path / "job"
    incoming = root / "incoming"
    work = root / "work"
    incoming.mkdir(parents=True)
    work.mkdir(parents=True)
    return JobWorkspace(job_id="t", temp_root=root, incoming=incoming, work=work, staging=root / "staging")


def _make_record(tmp_path: Path) -> FileRecord:
    src = tmp_path / "sample.png"
    Image.new("RGB", (32, 32), color=(10, 20, 30)).save(src)
    return FileRecord(
        source_path=src,
        current_path=src,
        original_name="sample",
        original_ext=".png",
        index=1,
    )


def _ctx(tmp_path: Path, cfg: AppConfig) -> StepContext:
    return StepContext(
        config=cfg,
        workspace=_make_workspace(tmp_path),
        record=_make_record(tmp_path),
        resources={},
    )


def _package_missing():
    """Patch imports so remove_ai_watermarks looks absent and its CLI subprocess fails."""

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "remove_ai_watermarks" or name.startswith("remove_ai_watermarks."):
            raise ImportError(f"No module named {name!r}")
        return real_import(name, *args, **kwargs)

    return patch.object(builtins, "__import__", side_effect=fake_import)


def test_provenance_cleanup_skips_when_package_missing(tmp_path: Path):
    cfg = default_config()
    cfg.steps.provenance_cleanup.enabled = True
    step = ProvenanceCleanupStep()
    ctx = _ctx(tmp_path, cfg)

    with _package_missing():
        result = step.run(ctx)

    assert isinstance(result, StepResult)
    assert result.ok
    assert "unavailable" in result.message


def test_provenance_cleanup_subprocess_fallback_blocked_when_frozen(tmp_path: Path):
    """When app is frozen, the library API fails and subprocess CLI is unavailable.
    Verify that the step raises a clear error instead of spawning the app .exe."""
    cfg = default_config()
    cfg.steps.provenance_cleanup.enabled = True
    step = ProvenanceCleanupStep()
    ctx = _ctx(tmp_path, cfg)

    with patch("app.config.paths.is_frozen", return_value=True):
        with patch(
            "app.core.steps.provenance_cleanup._try_remove_ai_watermarks",
            side_effect=RuntimeError("remove-ai-watermarks CLI 子进程在打包模式下不可用"),
        ):
            result = step.run(ctx)

    assert isinstance(result, StepResult)
    assert not result.ok
    assert "打包模式" in (result.error or "")


class _FakeSummary:
    def __init__(self, processed=1, failed=0, errors=None):
        self.processed = processed
        self.failed = failed
        self.errors = errors or []


def test_run_remove_batch_cleans_and_outputs(tmp_path: Path):
    """The current remove-ai-watermarks batch API is driven correctly."""
    src = tmp_path / "sample.png"
    Image.new("RGB", (32, 32), color=(10, 20, 30)).save(src)
    work = tmp_path / "work"
    work.mkdir()
    dest = work / "0001_clean.png"

    seen = {}

    def fake_remove_batch(indir, outdir, mode="metadata"):
        seen["mode"] = mode
        out = Path(outdir) / src.name
        shutil.copy2(src, out)
        return _FakeSummary()

    api = types.SimpleNamespace(remove_batch=fake_remove_batch)
    result = _run_remove_batch(api, src, dest, "metadata")
    assert seen["mode"] == "metadata"
    assert result == dest
    assert dest.exists()


def test_run_remove_batch_raises_on_failed_summary(tmp_path: Path):
    src = tmp_path / "sample.png"
    Image.new("RGB", (32, 32), color=(10, 20, 30)).save(src)
    work = tmp_path / "work"
    work.mkdir()
    dest = work / "0001_clean.png"

    def fake_remove_batch(indir, outdir, mode="metadata"):
        return _FakeSummary(processed=0, failed=1, errors=["boom"])

    api = types.SimpleNamespace(remove_batch=fake_remove_batch)
    with pytest.raises(RuntimeError) as excinfo:
        _run_remove_batch(api, src, dest, "metadata")
    assert "boom" in str(excinfo.value)


# --- Unsupported formats: the batch API reports success but writes nothing ---

def _install_fake_batch_api(monkeypatch, remove_batch):
    """Make ``_try_remove_ai_watermarks`` discover a fake batch API."""
    module = types.ModuleType("remove_ai_watermarks.api")
    module.remove_batch = remove_batch
    monkeypatch.setitem(sys.modules, "remove_ai_watermarks.api", module)
    return module


def _install_cli_only_package(monkeypatch):
    """Fake an old install: no batch API, no per-file helper -> CLI subprocess."""
    api = types.ModuleType("remove_ai_watermarks.api")
    monkeypatch.setitem(sys.modules, "remove_ai_watermarks.api", api)
    legacy = types.ModuleType("remove_ai_watermarks")
    monkeypatch.setitem(sys.modules, "remove_ai_watermarks", legacy)
    return legacy


def test_run_remove_batch_returns_none_when_no_output(tmp_path: Path):
    """No failures + no output means the cleaner skipped the format, not failure."""
    src = tmp_path / "sample.tiff"
    Image.new("RGB", (32, 32), color=(10, 20, 30)).save(src, "TIFF")
    work = tmp_path / "work"
    work.mkdir()
    dest = work / "0001_clean.tiff"

    def fake_remove_batch(indir, outdir, mode="metadata"):
        # Upstream contract: TIFF/BMP are filtered out before processing, so the
        # batch "succeeds" with an empty output directory.
        assert list(Path(outdir).iterdir()) == []
        return _FakeSummary(processed=0, failed=0, errors=[])

    api = types.SimpleNamespace(remove_batch=fake_remove_batch)
    result = _run_remove_batch(api, src, dest, "metadata")
    assert result is None
    assert not dest.exists()


def test_run_remove_batch_raises_when_reported_failure_has_no_errors(tmp_path: Path):
    """`failed > 0` must raise even when the upstream left `errors` empty.

    This is the guard the unsupported-format pass-through must not erode: the
    batch API's documented failure signal is `failed`, and `errors` may be
    empty (e.g. only the first few failures are recorded upstream).
    """
    src = tmp_path / "sample.jpg"
    Image.new("RGB", (32, 32), color=(10, 20, 30)).save(src)
    work = tmp_path / "work"
    work.mkdir()
    dest = work / "0001_clean.jpg"

    def fake_remove_batch(indir, outdir, mode="metadata"):
        return _FakeSummary(processed=0, failed=1, errors=[])

    api = types.SimpleNamespace(remove_batch=fake_remove_batch)
    with pytest.raises(RuntimeError):
        _run_remove_batch(api, src, dest, "metadata")
    assert not dest.exists()


def test_provenance_cleanup_copies_original_when_upstream_skips_format(tmp_path: Path, monkeypatch):
    """The step must degrade to a byte-identical copy instead of failing the file."""
    cfg = default_config()
    cfg.steps.provenance_cleanup.enabled = True
    ctx = _ctx(tmp_path, cfg)
    source = ctx.record.source_path
    source_bytes = source.read_bytes()

    calls = []

    def fake_remove_batch(indir, outdir, mode="metadata"):
        calls.append((indir, outdir, mode))
        return _FakeSummary(processed=0, failed=0, errors=[])

    _install_fake_batch_api(monkeypatch, fake_remove_batch)
    result = ProvenanceCleanupStep().run(ctx)

    assert calls == [(str(ctx.workspace.work / "_in"), str(ctx.workspace.work / "_out"), "metadata")]
    assert result.ok, result.error
    assert result.error is None
    assert "copied original" in result.message
    assert "provenance cleanup done" not in result.message

    out = ctx.record.current_path
    assert out == ctx.workspace.work / "0001_clean.png"
    assert out.exists()
    assert out.read_bytes() == source_bytes


def test_cli_fallback_returns_none_when_no_output(tmp_path: Path, monkeypatch):
    """CLI fallback with exit 0 and no output file is pass-through, not a failure."""
    src = tmp_path / "sample.tiff"
    Image.new("RGB", (32, 32), color=(10, 20, 30)).save(src, "TIFF")
    work = tmp_path / "work"
    work.mkdir()
    dest = work / "0001_clean.tiff"
    _install_cli_only_package(monkeypatch)

    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = list(cmd)
        outdir = Path(cmd[cmd.index("-o") + 1])
        assert list(outdir.iterdir()) == []  # upstream wrote nothing
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    with patch("app.config.paths.is_frozen", return_value=False):
        with patch("subprocess.run", side_effect=fake_run):
            result = _try_remove_ai_watermarks(src, dest, "metadata")

    assert result is None
    assert not dest.exists()
    assert seen["cmd"][:4] == [sys.executable, "-m", "remove_ai_watermarks", "batch"]
    # Reaching the subprocess branch means the isolated input dir was populated.
    assert (work / "_in" / src.name).exists()


def test_cli_fallback_returns_dest_when_output_written(tmp_path: Path, monkeypatch):
    """Guard the other side of the branch: a real CLI output is still returned."""
    src = tmp_path / "sample.png"
    Image.new("RGB", (32, 32), color=(10, 20, 30)).save(src)
    work = tmp_path / "work"
    work.mkdir()
    dest = work / "0001_clean.png"
    _install_cli_only_package(monkeypatch)

    def fake_run(cmd, **kwargs):
        outdir = Path(cmd[cmd.index("-o") + 1])
        shutil.copy2(src, outdir / src.name)
        return subprocess.CompletedProcess(cmd, 0, stdout="done", stderr="")

    with patch("app.config.paths.is_frozen", return_value=False):
        with patch("subprocess.run", side_effect=fake_run):
            result = _try_remove_ai_watermarks(src, dest, "metadata")

    assert result == dest
    assert dest.exists()


# --- Integration against the real remove-ai-watermarks (skipped if absent) ---

def _has_real_batch_api() -> bool:
    try:
        return hasattr(importlib.import_module("remove_ai_watermarks.api"), "remove_batch")
    except Exception:  # noqa: BLE001 - any import problem means "not available"
        return False


needs_real_package = pytest.mark.skipif(
    not _has_real_batch_api(), reason="remove-ai-watermarks is not installed"
)


def _ctx_for(tmp_path: Path, cfg: AppConfig, src: Path, index: int) -> StepContext:
    """Build a context for an arbitrary source file (each call needs its own root)."""
    return StepContext(
        config=cfg,
        workspace=_make_workspace(tmp_path),
        record=FileRecord(
            source_path=src,
            current_path=src,
            original_name=src.stem,
            original_ext=src.suffix,
            index=index,
        ),
        resources={},
    )


def _enabled_config() -> AppConfig:
    cfg = default_config()
    cfg.steps.provenance_cleanup.enabled = True
    return cfg


@needs_real_package
@pytest.mark.parametrize("suffix, pil_format", [(".tif", "TIFF"), (".bmp", "BMP")])
def test_real_package_silent_skip_passes_original_through(tmp_path: Path, suffix: str, pil_format: str):
    """Measured on remove-ai-watermarks 0.46.0: TIFF/BMP are not in
    SUPPORTED_FORMATS, so remove_batch filters them out and reports
    processed=0/failed=0 with an empty output dir. The file must survive."""
    src = tmp_path / f"sample{suffix}"
    Image.new("RGB", (32, 32), color=(10, 20, 30)).save(src, pil_format)
    original_bytes = src.read_bytes()
    ctx = _ctx_for(tmp_path, _enabled_config(), src, index=7)

    result = ProvenanceCleanupStep().run(ctx)

    assert result.ok, f"{result.error!r} (message={result.message!r})"
    assert result.error is None
    assert "copied original" in result.message
    out = ctx.record.current_path
    assert out == ctx.workspace.work / f"0007_clean{suffix}"
    assert out.exists()
    assert out.read_bytes() == original_bytes


@needs_real_package
def test_real_package_cleans_supported_png(tmp_path: Path):
    """PNG is supported: the AI text chunk is stripped, not copied through."""
    info = PngImagePlugin.PngInfo()
    info.add_text("parameters", "invokeai: 4.0.0 model sd15")
    info.add_text("Comment", "Generated by Stable Diffusion")
    src = tmp_path / "sample.png"
    Image.new("RGB", (32, 32), color=(10, 20, 30)).save(src, pnginfo=info)
    assert Image.open(src).info.get("parameters")  # fixture really is tagged
    ctx = _ctx_for(tmp_path, _enabled_config(), src, index=1)

    result = ProvenanceCleanupStep().run(ctx)

    assert result.ok, f"{result.error!r} (message={result.message!r})"
    assert result.message == "provenance cleanup done"
    out = ctx.record.current_path
    assert out == ctx.workspace.work / "0001_clean.png"
    assert out.exists()
    assert "parameters" not in Image.open(out).info
    assert "Comment" not in Image.open(out).info


@needs_real_package
def test_real_package_cleans_supported_jpeg(tmp_path: Path):
    """JPEG is supported too: it takes the cleanup branch, not the copy-through."""
    src = tmp_path / "sample.jpg"
    Image.new("RGB", (32, 32), color=(10, 20, 30)).save(src, "JPEG")
    ctx = _ctx_for(tmp_path, _enabled_config(), src, index=2)

    result = ProvenanceCleanupStep().run(ctx)

    assert result.ok, f"{result.error!r} (message={result.message!r})"
    assert result.message == "provenance cleanup done"
    out = ctx.record.current_path
    assert out == ctx.workspace.work / "0002_clean.jpg"
    assert out.exists()
    assert Image.open(out).size == (32, 32)


@needs_real_package
def test_real_package_batch_reports_success_while_skipping_formats(tmp_path: Path):
    """The upstream contract behind the fix: mixed batch, failed=0 and no errors
    even though the TIFF/BMP outputs never appear."""
    api = importlib.import_module("remove_ai_watermarks.api")
    src_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    src_dir.mkdir()
    for name, fmt in [("a.png", "PNG"), ("b.jpg", "JPEG"), ("c.tif", "TIFF"), ("d.bmp", "BMP")]:
        Image.new("RGB", (32, 32), color=(10, 20, 30)).save(src_dir / name, fmt)

    summary = api.remove_batch(str(src_dir), str(out_dir), mode="metadata")

    # The two unsupported files never reach the processing loop at all, so the
    # summary claims full success while their outputs simply do not exist.
    assert summary.processed == 2
    assert summary.failed == 0
    assert list(summary.errors) == []
    assert {item.source.name for item in summary.items} == {"a.png", "b.jpg"}
    assert sorted(p.name for p in out_dir.iterdir()) == ["a.png", "b.jpg"]
