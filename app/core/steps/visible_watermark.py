"""Visible AI watermark removal step (remove-ai-watermarks `visible`)."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from app.config.schema import AppConfig
from app.core.models import StepResult
from app.core.steps.base import Step, StepContext
from app.platform import CREATE_NO_WINDOW

# CLI `visible` exit code when the image carries no registered visible mark.
_EXIT_NO_VISIBLE_MARK = 2


class VisibleWatermarkStep(Step):
    id = "visible_watermark"
    title = "去除可见水印"

    def enabled(self, config: AppConfig) -> bool:
        return bool(config.steps.visible_watermark.enabled)

    def validate(self, config: AppConfig) -> list[str]:
        issues: list[str] = []
        try:
            import remove_ai_watermarks  # noqa: F401
        except Exception:  # noqa: BLE001
            issues.append(
                "remove-ai-watermarks 未安装，可见水印去除将失败；"
                "可在「设置 → 处理 → 去除可见水印」点击“安装依赖”在线安装，"
                '或执行: pip install "remove-ai-watermarks[visible]"'
            )
        return issues

    def run(self, ctx: StepContext) -> StepResult:
        src = ctx.record.current_path
        dest = ctx.workspace.work / f"{ctx.record.index:04d}_vis{src.suffix}"
        backend = ctx.config.steps.visible_watermark.backend
        try:
            removed = _remove_visible(src, dest, backend=backend)
            if not dest.exists():
                # No registered mark (or backend wrote nothing): pass through
                # so downstream steps keep a valid file.
                shutil.copy2(src, dest)
            ctx.record.current_path = dest
            if removed:
                return StepResult(self.id, True, message=f"已去除可见水印: {', '.join(str(r) for r in removed)}")
            return StepResult(self.id, True, message="未检测到已注册的可见水印")
        except Exception as exc:  # noqa: BLE001
            return StepResult(self.id, False, error=str(exc))


def _remove_visible(src: Path, dest: Path, *, backend: str) -> list[str]:
    """Run visible removal via library API, falling back to the CLI.

    Returns the list of removed mark labels ([] when no registered mark was
    found); the caller guarantees a file at dest afterwards.
    """
    try:
        import remove_ai_watermarks as raiw
    except Exception:  # noqa: BLE001
        raiw = None

    if raiw is not None:
        _, removed = raiw.remove_visible(str(src), str(dest), backend=backend)
        return list(removed or [])

    from app.config.paths import is_frozen

    if is_frozen():
        raise RuntimeError(
            "remove-ai-watermarks CLI 子进程在打包模式下不可用；"
            "请通过库 API 安装并确保其可正常工作，"
            '或在非打包环境运行: pip install "remove-ai-watermarks[visible]"'
        )

    cmd = [
        sys.executable,
        "-m",
        "remove_ai_watermarks",
        "visible",
        str(src),
        "-o",
        str(dest),
        "--backend",
        backend,
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        creationflags=CREATE_NO_WINDOW,
    )
    if proc.returncode not in (0, _EXIT_NO_VISIBLE_MARK):
        detail = (proc.stderr or proc.stdout or "").strip() or "exit " + str(proc.returncode)
        hint = 'pip install "remove-ai-watermarks[visible]"'
        raise RuntimeError(f"remove-ai-watermarks visible 失败：{detail}（安装提示：{hint}）")
    return [] if proc.returncode == _EXIT_NO_VISIBLE_MARK else ["(cli)"]
