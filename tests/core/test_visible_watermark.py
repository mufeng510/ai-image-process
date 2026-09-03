"""Tests for the visible watermark removal step and model helpers."""
import builtins
import subprocess
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app.config.schema import AppConfig, default_config
from app.core.pipeline import DEFAULT_STEP_ORDER, build_default_registry
from app.core.steps.base import StepContext
from app.core.steps.visible_watermark import VisibleWatermarkStep
from app.core.models import FileRecord, JobWorkspace, StepResult


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

    failed = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="ModuleNotFoundError: remove_ai_watermarks")
    return (
        patch.object(builtins, "__import__", side_effect=fake_import),
        patch("app.core.steps.visible_watermark.subprocess.run", return_value=failed),
    )


def test_visible_watermark_disabled_by_default():
    cfg = default_config()
    assert cfg.steps.visible_watermark.enabled is False
    assert cfg.steps.visible_watermark.backend == "auto"
    step = VisibleWatermarkStep()
    assert not step.enabled(cfg)


def test_visible_watermark_registered_after_provenance():
    assert "visible_watermark" in DEFAULT_STEP_ORDER
    assert DEFAULT_STEP_ORDER.index("visible_watermark") == DEFAULT_STEP_ORDER.index("provenance_cleanup") + 1
    reg = build_default_registry()
    assert reg.get("visible_watermark").title


def test_schema_roundtrip_keeps_visible_watermark():
    cfg = default_config()
    cfg.steps.visible_watermark.enabled = True
    cfg.steps.visible_watermark.backend = "migan"
    restored = AppConfig.from_dict(cfg.to_dict())
    assert restored.steps.visible_watermark.enabled is True
    assert restored.steps.visible_watermark.backend == "migan"


def test_validate_warns_when_package_missing():
    cfg = default_config()
    cfg.steps.visible_watermark.enabled = True
    step = VisibleWatermarkStep()
    import_patch, _ = _package_missing()
    with import_patch:
        issues = step.validate(cfg)
    assert issues and "remove-ai-watermarks" in issues[0]


def test_run_fails_with_hint_when_package_missing(tmp_path: Path):
    cfg = default_config()
    cfg.steps.visible_watermark.enabled = True
    step = VisibleWatermarkStep()
    ctx = _ctx(tmp_path, cfg)
    import_patch, subprocess_patch = _package_missing()
    with import_patch, subprocess_patch:
        result = step.run(ctx)
    assert isinstance(result, StepResult)
    assert not result.ok
    assert "remove-ai-watermarks" in (result.error or "")


def test_run_success_with_mocked_backend(tmp_path: Path):
    cfg = default_config()
    cfg.steps.visible_watermark.enabled = True
    cfg.steps.visible_watermark.backend = "cv2"
    step = VisibleWatermarkStep()
    ctx = _ctx(tmp_path, cfg)
    dest = ctx.workspace.work / "0001_vis.png"

    def fake_remove(src, dest, backend="auto"):
        Image.new("RGB", (32, 32), color=(99, 99, 99)).save(dest)
        return ["gemini"]

    with patch("app.core.steps.visible_watermark._remove_visible", side_effect=fake_remove) as m:
        result = step.run(ctx)
    assert result.ok
    assert "gemini" in result.message
    assert ctx.record.current_path == dest
    assert dest.exists()
    assert m.call_args.kwargs["backend"] == "cv2"


def test_run_no_mark_copies_through(tmp_path: Path):
    cfg = default_config()
    cfg.steps.visible_watermark.enabled = True
    step = VisibleWatermarkStep()
    ctx = _ctx(tmp_path, cfg)
    dest = ctx.workspace.work / "0001_vis.png"

    with patch("app.core.steps.visible_watermark._remove_visible", return_value=[]):
        result = step.run(ctx)
    assert result.ok
    assert "未检测到" in result.message
    assert ctx.record.current_path == dest
    assert dest.exists()


def test_subprocess_fallback_blocked_when_frozen(tmp_path: Path):
    """When app is frozen (PyInstaller), sys.executable is the app .exe.
    Running it would pop a new GUI window instead of invoking the CLI."""
    cfg = default_config()
    cfg.steps.visible_watermark.enabled = True
    step = VisibleWatermarkStep()
    ctx = _ctx(tmp_path, cfg)

    import_patch, _ = _package_missing()
    with import_patch:
        with patch("app.config.paths.is_frozen", return_value=True):
            result = step.run(ctx)

    assert isinstance(result, StepResult)
    assert not result.ok
    assert "打包模式" in (result.error or "")
