"""Write final output file with conflict policy."""
from __future__ import annotations

import shutil
from pathlib import Path

from app.config.schema import AppConfig
from app.core.conflicts import ConflictPolicy, resolve_output_path
from app.core.models import StepResult
from app.core.steps.base import Step, StepContext


class OutputWriteStep(Step):
    id = "output_write"
    title = "输出图片"

    def enabled(self, config: AppConfig) -> bool:
        return bool(config.steps.output_write.enabled)

    def run(self, ctx: StepContext) -> StepResult:
        try:
            out_dir = Path(ctx.resources["output_dir"]).expanduser().resolve()
            if ctx.config.output.auto_create_directory:
                out_dir.mkdir(parents=True, exist_ok=True)
            elif not out_dir.exists():
                return StepResult(self.id, False, error=f"output directory missing: {out_dir}")

            name = ctx.record.output_name or f"{ctx.record.original_name}.jpg"
            dest = out_dir / name
            policy = ConflictPolicy(ctx.config.output.conflict_policy)
            final = resolve_output_path(dest, policy)
            if final is None:
                return StepResult(self.id, True, message="skipped existing")

            # safety: never write onto source if preserve originals
            if ctx.config.output.preserve_originals and final.resolve() == ctx.record.source_path.resolve():
                return StepResult(self.id, False, error="refusing to overwrite source while preserve_originals=true")

            shutil.copy2(ctx.record.current_path, final)
            ctx.record.output_path = final
            created = ctx.resources.setdefault("created_outputs", [])
            created.append(final)
            return StepResult(self.id, True, message=str(final))
        except Exception as exc:  # noqa: BLE001
            return StepResult(self.id, False, error=str(exc))
