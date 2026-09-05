"""Tests for the provenance cleanup step."""
import builtins
import shutil
import subprocess
import types
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from app.config.schema import AppConfig, default_config
from app.core.models import FileRecord, JobWorkspace, StepResult
from app.core.steps.base import StepContext
from app.core.steps.provenance_cleanup import ProvenanceCleanupStep, _run_remove_batch


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
