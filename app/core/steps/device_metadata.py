"""Device EXIF metadata step via ExifTool when available."""
from __future__ import annotations

from datetime import datetime, timedelta
import random

from app.config.schema import AppConfig
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
            if cfg.randomize_datetime:
                # PowerShell: AddMinutes(-(Get-Random -Minimum 10 -Maximum 10000))
                # => offset in [10, 10000)
                lo = cfg.offset_min_minutes
                hi = cfg.offset_max_minutes
                offset = rng.randrange(lo, max(lo + 1, hi))
                when = datetime.now() - timedelta(minutes=offset)
            else:
                when = datetime.now()
            ctx.record.capture_dt = when
            date_string = when.strftime("%Y:%m:%d %H:%M:%S")

            if runner is None or not getattr(runner, "available", lambda: False)():
                # Still succeed logically for environments without exiftool binary;
                # metadata write skipped but device selection recorded.
                return StepResult(self.id, True, message="exiftool unavailable; device chosen only")

            args = [
                "-overwrite_original",
                f"-Make={device.make}",
                f"-Model={device.model}",
                f"-LensMake={device.make}",
                f"-LensModel={device.lens}",
                f"-DateTimeOriginal={date_string}",
                f"-CreateDate={date_string}",
                "-FNumber=1.78",
                "-ExposureTime=1/120",
                "-ISO=100",
                "-FocalLength=24 mm",
                "-Flash=Off, Did not fire",
                f"-Software={cfg.software_tag}",
                str(ctx.record.current_path),
            ]
            runner.run(args)
            return StepResult(self.id, True, message=f"exif written for {device.model}")
        except Exception as exc:  # noqa: BLE001
            return StepResult(self.id, False, error=str(exc))
