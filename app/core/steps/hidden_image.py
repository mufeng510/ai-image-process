"""Hidden-image overlay step: cover-fit, centered, low opacity composite."""
from __future__ import annotations

from pathlib import Path

from app.config.schema import AppConfig
from app.core.models import StepResult
from app.core.steps.base import Step, StepContext


def composite_cover(main_path: Path, hidden_path: Path, dest: Path, opacity: float) -> None:
    from PIL import Image

    with Image.open(main_path) as base, Image.open(hidden_path) as hid:
        base_rgba = base.convert("RGBA")
        hid_rgb = hid.convert("RGB")
        bw, bh = base_rgba.size
        hw, hh = hid_rgb.size
        scale = max(bw / max(1, hw), bh / max(1, hh))
        nw, nh = max(1, int(hw * scale)), max(1, int(hh * scale))
        hid_resized = hid_rgb.resize((nw, nh), Image.LANCZOS)
        left = (nw - bw) // 2
        top = (nh - bh) // 2
        hid_cropped = hid_resized.crop((left, top, left + bw, top + bh))
        # low-opacity overlay: blend full-cover hidden layer onto main
        alpha = max(0.0, min(0.5, float(opacity)))
        blended = Image.blend(base_rgba.convert("RGB"), hid_cropped, alpha)
        blended.save(dest, format="JPEG", quality=95, subsampling=0)


class HiddenImageStep(Step):
    id = "hidden_image"
    title = "隐藏图片"

    def enabled(self, config: AppConfig) -> bool:
        return bool(config.steps.hidden_image.enabled)

    def validate(self, config: AppConfig) -> list[str]:
        if not self.enabled(config):
            return []
        issues: list[str] = []
        if not (config.steps.hidden_image.library_dir or "").strip():
            issues.append("hidden_image: library_dir not configured")
        try:
            op = float(config.steps.hidden_image.opacity)
        except Exception:
            return issues + ["hidden_image: opacity invalid"]
        if not (0 < op <= 0.5):
            issues.append(f"hidden_image: opacity {op} out of range (0, 0.5]")
        return issues

    def run(self, ctx: StepContext) -> StepResult:
        try:
            hidden = ctx.record.assigned_hidden_image
            if hidden is None:
                # Fallback: preflight mapping stored in resources
                mapping: dict = ctx.resources.get("hidden_mapping", {})
                hidden = mapping.get(str(ctx.record.source_path))
            if hidden is None:
                return StepResult(self.id, False, error="no hidden image assigned (preflight failed?)")
            hidden = Path(hidden)
            if not hidden.is_file():
                return StepResult(self.id, False, error=f"assigned hidden image missing: {hidden}")
            # Safety: hidden must live inside configured library
            lib = Path(ctx.config.steps.hidden_image.library_dir).expanduser().resolve()
            try:
                Path(hidden).expanduser().resolve().relative_to(lib)
            except ValueError:
                return StepResult(self.id, False, error="assigned hidden image outside library; refusing")
            opacity = float(ctx.config.steps.hidden_image.opacity)
            dest = ctx.workspace.work / f"{ctx.record.index:04d}_hid.jpg"
            composite_cover(ctx.record.current_path, hidden, dest, opacity)
            ctx.record.current_path = dest
            from app.core.finalize import finalize_image_metadata

            finalize_image_metadata(ctx.record, ctx.config, ctx.resources)
            return StepResult(self.id, True, message=f"hidden overlay {hidden.name} @ {opacity:.3f}")
        except Exception as exc:  # noqa: BLE001
            return StepResult(self.id, False, error=str(exc))
