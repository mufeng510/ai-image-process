"""AI provenance/metadata cleanup step."""
from __future__ import annotations

import shutil
from pathlib import Path

from app.config.schema import AppConfig
from app.core.models import StepResult
from app.core.steps.base import Step, StepContext
from app.platform import CREATE_NO_WINDOW


class ProvenanceCleanupStep(Step):
    id = "provenance_cleanup"
    title = "清理 AI Metadata"

    def enabled(self, config: AppConfig) -> bool:
        return bool(config.steps.provenance_cleanup.enabled)

    def run(self, ctx: StepContext) -> StepResult:
        # Prefer library API when available; otherwise pass-through with warning.
        src = ctx.record.current_path
        dest = ctx.workspace.work / f"{ctx.record.index:04d}_clean{src.suffix}"
        try:
            cleaned = _try_remove_ai_watermarks(src, dest, mode=ctx.config.steps.provenance_cleanup.mode)
            if cleaned is None:
                # graceful degradation for environments without the package
                shutil.copy2(src, dest)
                ctx.record.current_path = dest
                return StepResult(self.id, True, message="provenance package unavailable; copied original")
            ctx.record.current_path = cleaned
            return StepResult(self.id, True, message="provenance cleanup done")
        except Exception as exc:  # noqa: BLE001
            return StepResult(self.id, False, error=str(exc))


def _try_remove_ai_watermarks(src: Path, dest: Path, mode: str = "metadata") -> Path | None:
    """Attempt metadata cleanup via remove-ai-watermarks if installed.

    Returns output path on success, None if package missing.
    """
    try:
        import importlib

        # Current versions expose a batch API (works in frozen apps too).
        try:
            api = importlib.import_module("remove_ai_watermarks.api")
        except ImportError:
            api = None
        if api is not None and hasattr(api, "remove_batch"):
            return _run_remove_batch(api, src, dest, mode)

        # Legacy versions exposed per-file helpers on the package modules.
        mod = None
        for name in ("remove_ai_watermarks", "remove_ai_watermarks.cli"):
            try:
                mod = importlib.import_module(name)
                break
            except ImportError:
                continue
        if mod is None:
            return None

        # If a callable process/clean API exists, use it; else subprocess module CLI.
        for attr in ("clean_file", "process_file", "remove_metadata"):
            fn = getattr(mod, attr, None)
            if callable(fn):
                result = fn(str(src), str(dest), mode=mode) if "mode" in getattr(fn, "__code__", type("c", (), {"co_varnames": ()})).co_varnames else fn(str(src), str(dest))
                out = Path(result) if result else dest
                if out.exists():
                    return out

        import subprocess
        import sys

        from app.config.paths import is_frozen

        # In a frozen (PyInstaller) app sys.executable is the app's own .exe;
        # re-launching it would pop a new GUI window instead of running the
        # CLI, so we must never use the subprocess fallback in that case.
        if is_frozen():
            raise RuntimeError(
                "remove-ai-watermarks CLI 子进程在打包模式下不可用；"
                "请通过库 API 安装并确保其可正常工作，"
                '或在非打包环境运行: pip install "remove-ai-watermarks[visible]"'
            )

        dest.parent.mkdir(parents=True, exist_ok=True)
        isolated_in = dest.parent / "_in"
        isolated_out = dest.parent / "_out"
        if isolated_in.exists():
            shutil.rmtree(isolated_in)
        if isolated_out.exists():
            shutil.rmtree(isolated_out)
        isolated_in.mkdir(parents=True, exist_ok=True)
        isolated_out.mkdir(parents=True, exist_ok=True)
        single = isolated_in / src.name
        shutil.copy2(src, single)
        cmd = [sys.executable, "-m", "remove_ai_watermarks", "batch", str(isolated_in), "-o", str(isolated_out), "--mode", mode]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            creationflags=CREATE_NO_WINDOW,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr or proc.stdout or "remove-ai-watermarks failed")
        outputs = list(isolated_out.glob("*"))
        if not outputs:
            raise RuntimeError("remove-ai-watermarks produced no output")
        shutil.copy2(outputs[0], dest)
        return dest
    except ImportError:
        return None


def _run_remove_batch(api, src: Path, dest: Path, mode: str) -> Path:
    """Clean one file via the library batch API (no subprocess needed)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    isolated_in = dest.parent / "_in"
    isolated_out = dest.parent / "_out"
    # Clean stale directories from previous iterations so outputs[0] is correct.
    if isolated_in.exists():
        shutil.rmtree(isolated_in)
    if isolated_out.exists():
        shutil.rmtree(isolated_out)
    isolated_in.mkdir(parents=True, exist_ok=True)
    isolated_out.mkdir(parents=True, exist_ok=True)
    single = isolated_in / src.name
    shutil.copy2(src, single)
    summary = api.remove_batch(str(isolated_in), str(isolated_out), mode=mode)
    outputs = [p for p in isolated_out.rglob("*") if p.is_file()]
    if getattr(summary, "failed", 0) or not outputs:
        errors = "; ".join(str(e) for e in list(getattr(summary, "errors", []) or [])[:3])
        raise RuntimeError(f"remove-ai-watermarks 清理失败：{errors or 'no output'}")
    out = outputs[0]
    if out != dest:
        shutil.copy2(out, dest)
    return dest
