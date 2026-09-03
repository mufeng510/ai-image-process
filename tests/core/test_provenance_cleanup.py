"""Tests for the provenance cleanup step."""
import builtins
import subprocess
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app.config.schema import AppConfig, default_config
from app.core.models import FileRecord, JobWorkspace, StepResult
from app.core.steps.base import StepContext
from app.core.steps.provenance_cleanup import ProvenanceCleanupStep


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
