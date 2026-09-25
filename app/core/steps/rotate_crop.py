"""Rotate + crop step: random angle, keep visual aspect, no borders."""
from __future__ import annotations

import math
import random

from app.config.schema import AppConfig
from app.core.models import StepResult
from app.core.steps.base import Step, StepContext


def largest_axis_aligned_rect(w: int, h: int, angle_deg: float) -> tuple[int, int]:
    """Largest centered axis-aligned rect with same aspect inside rotated image.

    Candidate (cw, ch) keeps aspect r=w/h, scaled from the original. A
    candidate fits iff its four corners, inverse-rotated by -theta, still lie
    inside the original w x h bounds. Binary-search the scale for max area.
    """
    theta = math.radians(abs(angle_deg) % 90.0)
    if theta < 1e-6 or w <= 2 or h <= 2:
        return w, h
    cos_t, sin_t = math.cos(theta), math.sin(theta)

    def fits(scale: float) -> bool:
        cw, ch = w * scale, h * scale
        # corner (cw/2, ch/2) inverse-rotated; 2px margin absorbs canvas
        # rounding + resampling bleed at extreme aspects.
        x, y = cw / 2.0, ch / 2.0
        xr = x * cos_t + y * sin_t
        yr = -x * sin_t + y * cos_t
        return xr <= w / 2.0 - 2.0 + 1e-9 and yr <= h / 2.0 - 2.0 + 1e-9

    lo, hi = 0.0, 1.0
    for _ in range(50):
        mid = (lo + hi) / 2
        if fits(mid):
            lo = mid
        else:
            hi = mid
    cw = max(2, int(w * lo))
    ch = max(2, int(cw * h / w))
    # keep exact aspect within rounding: derive ch from cw
    if ch < 2:
        ch = 2
        cw = max(2, int(ch * w / h))
    return cw, ch


def _fits_rotated(cw: float, ch: float, w: float, h: float, sin_t: float, cos_t: float) -> bool:
    # Kept for backwards-compat import; superseded by corner-based check.
    x, y = cw / 2.0, ch / 2.0
    return (x * cos_t + y * sin_t) <= w / 2.0 + 1e-6 and (-x * sin_t + y * cos_t) <= h / 2.0 + 1e-6


class RotateCropStep(Step):
    id = "rotate_crop"
    title = "图片旋转与裁剪"

    def enabled(self, config: AppConfig) -> bool:
        return bool(config.steps.rotate_crop.enabled)

    def validate(self, config: AppConfig) -> list[str]:
        lo = config.steps.rotate_crop.min_angle
        hi = config.steps.rotate_crop.max_angle
        if lo > hi:
            return [f"rotate_crop: min_angle {lo} > max_angle {hi}"]
        return []

    def run(self, ctx: StepContext) -> StepResult:
        try:
            from PIL import Image, ImageOps

            cfg = ctx.config.steps.rotate_crop
            rng: random.Random = ctx.resources.get("rng") or random.Random()
            angle = rng.uniform(float(cfg.min_angle), float(cfg.max_angle))
            src = ctx.record.current_path
            dest = ctx.workspace.work / f"{ctx.record.index:04d}_rot.jpg"
            with Image.open(src) as im:
                im = ImageOps.exif_transpose(im)
                if im.mode != "RGB":
                    im = im.convert("RGB")
                w, h = im.size
                if abs(angle) < 1e-9:
                    im.save(dest, format="JPEG", quality=95, subsampling=0)
                    ctx.record.current_path = dest
                    return StepResult(self.id, True, message="rotation 0°; kept")
                rotated = im.rotate(angle, resample=Image.BICUBIC, expand=True)
                cw, ch = largest_axis_aligned_rect(w, h, angle)
                cw = min(cw, rotated.size[0])
                ch = min(ch, rotated.size[1])
                # Safety inset: resampling at the exact inscribed boundary can
                # still bleed background pixels (center rounding); scale down
                # proportionally (~4px off the long side) so no black edge
                # survives while the aspect ratio stays exact.
                if cw > 16 and ch > 16:
                    f = (cw - 4) / cw
                    cw, ch = int(cw * f), int(ch * f)
                cw = max(2, min(cw, rotated.size[0]))
                ch = max(2, min(ch, rotated.size[1]))
                left = (rotated.size[0] - cw) // 2
                top = (rotated.size[1] - ch) // 2
                cropped = rotated.crop((left, top, left + cw, top + ch))
                # Orientation normalized: plain save without EXIF orientation.
                cropped.save(dest, format="JPEG", quality=95, subsampling=0)
            ctx.record.current_path = dest
            # Pixel step only; final EXIF/ICC finalization happens downstream
            # (device/hidden final tags + ICC re-embed) to avoid Pillow drops.
            from app.core.finalize import finalize_image_metadata

            finalize_image_metadata(ctx.record, ctx.config, ctx.resources)
            return StepResult(self.id, True, message=f"rotated {angle:.2f}°")
        except Exception as exc:  # noqa: BLE001
            return StepResult(self.id, False, error=str(exc))
