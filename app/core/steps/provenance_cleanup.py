"""AI provenance/metadata cleanup step."""
from __future__ import annotations

import shutil
from pathlib import Path

from app.config.schema import AppConfig
from app.core.models import StepResult
from app.core.steps.base import Step, StepContext
from app.platform import CREATE_NO_WINDOW


_MISSING_PACKAGE_MESSAGE = (
    "remove-ai-watermarks 无法导入，无法清理 AI Metadata。\n\n"
    "该功能已随发行包内置；若这是开发环境，请执行: pip install \"remove-ai-watermarks\"。\n"
    "若使用的是发行包却看到此错误，说明内置依赖损坏：请重新下载安装，或向作者反馈。\n"
    "或关闭该步骤后重试。"
)


def _missing_package_error(detail: str | None = None) -> RuntimeError:
    """The environment is missing the optional dependency: fail, never degrade.

    ``detail`` carries the original exception text when one is available so the
    user does not get a flat "not installed" message when it is really a broken
    import (e.g. a missing stdlib module inside the frozen bundle).
    """
    message = _MISSING_PACKAGE_MESSAGE
    if detail:
        message = f"{message}\n底层错误：{detail}"
    return RuntimeError(message)


class ProvenanceCleanupStep(Step):
    id = "provenance_cleanup"
    title = "清理 AI Metadata"

    def enabled(self, config: AppConfig) -> bool:
        return bool(config.steps.provenance_cleanup.enabled)

    def run(self, ctx: StepContext) -> StepResult:
        src = ctx.record.current_path
        dest = ctx.workspace.work / f"{ctx.record.index:04d}_clean{src.suffix}"
        try:
            cleaned = _try_remove_ai_watermarks(src, dest, mode=ctx.config.steps.provenance_cleanup.mode)
            if cleaned is None:
                # The upstream ran but produced no output because the format is
                # unsupported (remove-ai-watermarks skips TIFF/BMP silently,
                # reporting failed=0 with an empty output directory). That is
                # not a missing environment, so the file passes through with a
                # copy; a *missing* package raises and fails the file instead.
                shutil.copy2(src, dest)
                ctx.record.current_path = dest
                return StepResult(self.id, True,
                                  message="provenance cleanup: format unsupported by remove-ai-watermarks; "
                                          "copied original")
            ctx.record.current_path = cleaned
            return StepResult(self.id, True, message="provenance cleanup done")
        except Exception as exc:  # noqa: BLE001
            return StepResult(self.id, False, error=str(exc))


def _try_remove_ai_watermarks(src: Path, dest: Path, mode: str = "metadata") -> Path | None:
    """Attempt metadata cleanup via remove-ai-watermarks if installed.

    Returns the cleaned path on success. Returns None only when the upstream
    ran but produced no output because the format is unsupported
    (remove-ai-watermarks 0.46.x filters TIFF/BMP out of the batch without
    reporting a failure); callers treat None as "copy the original through".
    A *missing* package raises RuntimeError — the environment is broken, so
    the file must fail loudly instead of silently shipping an uncleaned copy.
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
            raise _missing_package_error(detail="remove_ai_watermarks（含 cli）均无法导入")

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
        # Match the library path below: files only, so a stray subdirectory in
        # the output tree can never be handed to shutil.copy2 (IsADirectoryError).
        outputs = [p for p in isolated_out.glob("*") if p.is_file()]
        if not outputs:
            # Same "upstream skipped this format" contract as the library API
            # path below: no output and no reported failure means unsupported,
            # not broken. Fall through to the caller's copy-through.
            return None
        shutil.copy2(outputs[0], dest)
        return dest
    except ImportError as exc:
        raise _missing_package_error(f"{type(exc).__name__}: {exc}") from None


def _run_remove_batch(api, src: Path, dest: Path, mode: str) -> Path | None:
    """Clean one file via the library batch API (no subprocess needed).

    Returns the cleaned path, or None when the upstream ran without failures
    but produced no output (unsupported format).
    """
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
    if getattr(summary, "failed", 0):
        errors = "; ".join(str(e) for e in list(getattr(summary, "errors", []) or [])[:3])
        raise RuntimeError(f"remove-ai-watermarks 清理失败：{errors or 'no output'}")
    if not outputs:
        # Upstream reported no failures but wrote nothing: the cleaner does
        # not support this format (verified against remove-ai-watermarks
        # 0.46.x for TIFF/BMP). Return None so the caller copies the original
        # through instead of failing the whole file.
        return None
    out = outputs[0]
    if out != dest:
        shutil.copy2(out, dest)
    return dest
