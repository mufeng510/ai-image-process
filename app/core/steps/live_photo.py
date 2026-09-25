"""Live Photo pair step: final still + MOV -> Apple bundle in staging."""
from __future__ import annotations

from pathlib import Path

from app.config.schema import AppConfig
from app.core.live_photo.builder import LivePhotoBuilder
from app.core.live_photo.validator import LivePhotoValidator
from app.core.models import StepResult
from app.core.steps.base import Step, StepContext


class LivePhotoStep(Step):
    id = "live_photo"
    title = "生成 Apple Live Photo"

    def enabled(self, config: AppConfig) -> bool:
        return bool(config.steps.live_photo.enabled)

    def validate(self, config: AppConfig) -> list[str]:
        if not self.enabled(config):
            return []
        mode = config.steps.live_photo.video_source
        if mode not in ("local_motion", "ai_video"):
            return [f"live_photo: unknown video_source {mode}"]
        if mode == "local_motion":
            from app.core.ffmpeg_resolver import resolve_ffmpeg

            if resolve_ffmpeg() is None:
                return ["live_photo: FFmpeg not found; install/bundle FFmpeg for local motion"]
        else:
            ai = config.steps.live_photo.ai_video
            missing = [k for k in ("provider", "model", "endpoint") if not getattr(ai, k).strip()]
            if missing:
                return [f"live_photo ai_video: missing {', '.join(missing)}"]
            if not ai.api_key.strip():
                return ["live_photo ai_video: api_key missing"]
        return []

    def run(self, ctx: StepContext) -> StepResult:
        from app.core.ffmpeg_resolver import resolve_ffmpeg, resolve_ffprobe

        try:
            ffmpeg = resolve_ffmpeg()
            if ffmpeg is None:
                if ctx.config.steps.live_photo.video_source == "local_motion":
                    return StepResult(self.id, False, error="FFmpeg not available for local motion")
                # AI path still needs ffmpeg for normalization
                return StepResult(self.id, False, error="FFmpeg not available for movie normalization")
            ffprobe = resolve_ffprobe()
            stem = ctx.record.output_stem or ctx.record.output_name or f"{ctx.record.index:04d}"
            if stem.endswith(".jpg"):
                stem = stem[: -len(".jpg")]
            cfg = ctx.config.steps.live_photo
            rng = ctx.resources.get("rng")
            seed = rng.randrange(1 << 30) if rng else 0
            builder = LivePhotoBuilder(ffmpeg=ffmpeg, ffprobe=ffprobe,
                                       exiftool=ctx.resources.get("exiftool"))
            bundle = builder.build(
                still_jpeg=Path(ctx.record.current_path),
                stem=stem,
                staging=Path(ctx.workspace.staging),
                video_source=cfg.video_source,
                local_cfg=cfg.local_motion,
                ai_cfg=cfg.ai_video,
                seed=seed,
                still_time_ms=0,
            )
            validator = LivePhotoValidator(ffprobe=ffprobe, exiftool=ctx.resources.get("exiftool"))
            report = validator.validate(bundle.photo_path, bundle.video_path,
                                        expected_identifier=bundle.asset_identifier)
            if not report.ok:
                return StepResult(self.id, False,
                                  error="LivePhoto Stage-1 validation failed: " + "; ".join(report.errors[:5]))
            ctx.record.live_photo_bundle = bundle
            # Point downstream output at the staging still; MOV travels via bundle.
            ctx.record.current_path = bundle.photo_path
            return StepResult(self.id, True, message=f"live photo {stem} ({cfg.video_source})")
        except Exception as exc:  # noqa: BLE001
            return StepResult(self.id, False, error=str(exc))
