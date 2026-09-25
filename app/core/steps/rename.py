"""Filename template step (pure)."""
from __future__ import annotations

from datetime import datetime

from app.config.schema import AppConfig
from app.core.models import StepResult
from app.core.naming import render_filename
from app.core.steps.base import Step, StepContext


class RenameStep(Step):
    id = "rename"
    title = "文件命名"

    def enabled(self, config: AppConfig) -> bool:
        return bool(config.steps.rename.enabled)

    def run(self, ctx: StepContext) -> StepResult:
        try:
            # Preflight is the single source of truth for basenames (computed
            # once after dedup, shared by JPG+MOV). Reuse it for determinism;
            # compute only when preflight did not run (e.g. direct step use).
            if ctx.record.output_stem:
                ctx.record.output_name = f"{ctx.record.output_stem}.jpg"
                return StepResult(self.id, True, message=ctx.record.output_name)
            when = ctx.record.capture_dt or datetime.now()
            number = ctx.config.naming.number_start + ctx.record.index - 1
            name = render_filename(
                ctx.config.naming.template,
                original_name=ctx.record.original_name,
                original_ext=ctx.record.original_ext,
                when=when,
                number=number,
                number_width=ctx.config.naming.number_width,
            )
            # force jpg extension after reencode path; keep computed stem
            stem = name
            if "." in name:
                # if template included ext, strip for consistency with jpg output
                from pathlib import Path as P
                stem = P(name).stem
            ctx.record.output_name = f"{stem}.jpg"
            ctx.record.output_stem = stem
            return StepResult(self.id, True, message=ctx.record.output_name)
        except Exception as exc:  # noqa: BLE001
            return StepResult(self.id, False, error=str(exc))
