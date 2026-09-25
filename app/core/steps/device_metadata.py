"""Device EXIF metadata step via ExifTool when available."""
from __future__ import annotations

import random

from app.config.schema import AppConfig
from app.core.image_metadata import build_device_tags, resolve_capture_datetime
from app.core.models import StepResult
from app.core.steps.base import Step, StepContext


class DeviceMetadataStep(Step):
    id = "device_metadata"
    title = "写入设备 Metadata"

    def enabled(self, config: AppConfig) -> bool:
        return bool(config.steps.device_metadata.enabled)

    def run(self, ctx: StepContext) -> StepResult:
        cfg = ctx.config.steps.device_metadata
        lib = ctx.resources.get("device_library")
        rng: random.Random = ctx.resources.get("rng") or random.Random()
        runner = ctx.resources.get("exiftool")
        if lib is None:
            return StepResult(self.id, False, error="device library missing")

        try:
            device = lib.choose(cfg.selection, cfg.fixed_device_id, rng=rng)
            ctx.record.device = device
            # Hidden-image metadata source (prepared in preflight) takes
            # priority for inheritable capture params; missing fields fall
            # back to generated device values. Never depends on step 8 output.
            hidden_src: dict = {}
            if ctx.config.steps.hidden_image.enabled:
                hidden_src = dict(getattr(ctx.record, "hidden_metadata_source", None) or {})
                if not hidden_src:
                    pre_meta: dict = ctx.resources.get("hidden_metadata", {})
                    hidden_src = dict(pre_meta.get(str(ctx.record.source_path), {}) or {})
                    if hidden_src:
                        ctx.record.hidden_metadata_source = hidden_src
            when = resolve_capture_datetime(
                hidden_src,
                cfg.randomize_datetime,
                cfg.offset_min_minutes,
                cfg.offset_max_minutes,
                rng,
            )
            ctx.record.capture_dt = when
            if hidden_src:
                ctx.record.hidden_metadata_source = hidden_src

            tags = build_device_tags(
                make=device.make,
                model=device.model,
                lens=device.lens,
                when=when,
                software=cfg.software_tag,
                hidden_src=hidden_src,
            )
            if runner is None or not getattr(runner, "available", lambda: False)():
                # Still succeed logically for environments without exiftool binary;
                # metadata write skipped but device selection recorded.
                return StepResult(self.id, True, message="exiftool unavailable; device chosen only")

            args = ["-overwrite_original"]
            for k, v in tags.items():
                args.append(f"-{k}={v}")
            args.append(str(ctx.record.current_path))
            runner.run(args)
            return StepResult(self.id, True, message=f"exif written for {device.model}")
        except Exception as exc:  # noqa: BLE001
            return StepResult(self.id, False, error=str(exc))
