"""JPEG re-encode + ICC step."""
from __future__ import annotations

import random
from pathlib import Path

from app.config.schema import AppConfig
from app.core.models import StepResult
from app.core.steps.base import Step, StepContext


class ReencodeStep(Step):
    id = "reencode"
    title = "图片重编码"

    def enabled(self, config: AppConfig) -> bool:
        return bool(config.steps.reencode.enabled)

    def validate(self, config: AppConfig) -> list[str]:
        issues = []
        qmin = config.steps.reencode.quality_min
        qmax = config.steps.reencode.quality_max
        if not (1 <= qmin <= 100 and 1 <= qmax <= 100 and qmin <= qmax):
            issues.append("invalid jpeg quality range")
        return issues

    def run(self, ctx: StepContext) -> StepResult:
        try:
            from PIL import Image, ImageCms
        except ImportError as exc:
            return StepResult(self.id, False, error=f"Pillow required: {exc}")

        cfg = ctx.config.steps.reencode
        rng: random.Random = ctx.resources.get("rng") or random.Random()
        # match PowerShell Get-Random -Minimum 96 -Maximum 100 => 96..99
        qmax_exclusive = cfg.quality_max + 1 if cfg.quality_max == 99 and cfg.quality_min == 96 else cfg.quality_max
        if cfg.quality_min == cfg.quality_max:
            quality = cfg.quality_min
        else:
            quality = rng.randrange(cfg.quality_min, max(cfg.quality_min + 1, cfg.quality_max + 1))
        ctx.record.quality = quality

        src = ctx.record.current_path
        dest = ctx.workspace.work / f"{ctx.record.index:04d}_reenc.jpg"
        try:
            with Image.open(src) as im:
                if im.mode not in ("RGB", "L"):
                    im = im.convert("RGB")
                elif im.mode == "L":
                    im = im.convert("RGB")
                save_kwargs = {"quality": quality, "subsampling": 0}
                if cfg.apply_srgb_icc:
                    icc = ctx.resources.get("icc_path")
                    if icc and Path(icc).exists():
                        try:
                            profile = ImageCms.getOpenProfile(str(icc))
                            save_kwargs["icc_profile"] = profile.tobytes()
                        except Exception:
                            # still save jpeg without failing whole step hard
                            pass
                im.save(dest, format="JPEG", **save_kwargs)
            ctx.record.current_path = dest
            return StepResult(self.id, True, message=f"reencoded q={quality}")
        except Exception as exc:  # noqa: BLE001
            return StepResult(self.id, False, error=str(exc))
