"""AI provenance/metadata cleanup step."""
from __future__ import annotations

import shutil
from pathlib import Path

from app.config.schema import AppConfig
from app.core.models import StepResult
from app.core.steps.base import Step, StepContext


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
        # Public package exposes CLI primarily; try common module entrypoints.
        import importlib

        mod = None
        for name in ("remove_ai_watermarks", "remove_ai_watermarks.cli", "remove_ai_watermarks.api"):
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

        dest.parent.mkdir(parents=True, exist_ok=True)
        # batch-like single file via CLI if present on module
        cmd = [sys.executable, "-m", "remove_ai_watermarks", "batch", str(src.parent), "-o", str(dest.parent), "--mode", mode]
        # For single-file safety, copy into isolated incoming then batch that dir.
        isolated_in = dest.parent / "_in"
        isolated_out = dest.parent / "_out"
        isolated_in.mkdir(exist_ok=True)
        isolated_out.mkdir(exist_ok=True)
        single = isolated_in / src.name
        shutil.copy2(src, single)
        cmd = [sys.executable, "-m", "remove_ai_watermarks", "batch", str(isolated_in), "-o", str(isolated_out), "--mode", mode]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr or proc.stdout or "remove-ai-watermarks failed")
        outputs = list(isolated_out.glob("*"))
        if not outputs:
            raise RuntimeError("remove-ai-watermarks produced no output")
        shutil.copy2(outputs[0], dest)
        return dest
    except ImportError:
        return None
