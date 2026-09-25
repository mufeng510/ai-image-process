"""LivePhotoBuilder: still + movie -> paired bundle (Step orchestrates)."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from app.core.live_photo.metadata import (
    new_asset_identifier,
    patch_mov_with_livephoto_tags,
    write_photo_identifier,
)
from app.core.live_photo.models import LivePhotoBundle
from app.core.live_photo.movie import normalize_movie
from app.core.live_photo.providers.ai_video import build_ai_provider
from app.core.live_photo.providers.base import VideoGeneratorContext
from app.core.live_photo.providers.local_motion import LocalMotionVideoGenerator
from app.platform import CREATE_NO_WINDOW


class LivePhotoBuilder:
    def __init__(self, *, ffmpeg: Path, ffprobe: Path | None = None, exiftool=None) -> None:
        self.ffmpeg = Path(ffmpeg)
        self.ffprobe = Path(ffprobe) if ffprobe else None
        self.exiftool = exiftool

    def build(self, *, still_jpeg: Path, stem: str, staging: Path,
              video_source: str = "local_motion", local_cfg=None, ai_cfg=None,
              seed: int = 0, still_time_ms: int = 0,
              ai_fixture: Path | None = None, cancel=None) -> LivePhotoBundle:
        staging.mkdir(parents=True, exist_ok=True)
        work = staging / f"lp_{stem}"
        work.mkdir(parents=True, exist_ok=True)
        # still frame: copy final pixels to staging still (anchor frame)
        still_out = staging / f"{stem}.jpg"
        shutil.copy2(still_jpeg, still_out)

        from PIL import Image

        with Image.open(still_out) as im:
            still_size = im.size

        if video_source == "ai_video":
            if ai_cfg is None:
                raise RuntimeError("AI video config missing")
            provider = build_ai_provider(ai_cfg, mock_fixture=ai_fixture)
            raw = provider.generate(still_out, work, cancel=cancel)
            norm = work / "normalized.mov"
            duration = float(getattr(ai_cfg, "duration_seconds", 3.0) or 3.0)
            normalize_movie(raw, norm, ffmpeg=self.ffmpeg, duration_seconds=duration,
                            still_size=still_size)
        else:
            duration = float(getattr(local_cfg, "duration_seconds", 3.0) or 3.0)
            fps = int(getattr(local_cfg, "fps", 30) or 30)
            strength = float(getattr(local_cfg, "motion_strength", 0.06) or 0.06)
            gen = LocalMotionVideoGenerator(self.ffmpeg, motion_strength=strength)
            raw = gen.generate(VideoGeneratorContext(
                still_image=still_out, work_dir=work,
                duration_seconds=duration, fps=fps, seed=seed))
            norm = work / "normalized.mov"
            # local output is already standard; still normalize for one code path
            normalize_movie(raw, norm, ffmpeg=self.ffmpeg, duration_seconds=duration,
                            still_size=still_size)

        video_out = staging / f"{stem}.mov"
        if video_out.exists():
            video_out.unlink()
        shutil.move(str(norm), str(video_out))

        # Pair: fresh identifier on both resources + still-image-time.
        identifier = new_asset_identifier()
        write_photo_identifier(still_out, identifier, exiftool=self.exiftool)
        patch_mov_with_livephoto_tags(video_out, identifier, int(still_time_ms),
                                      exiftool=self.exiftool)
        return LivePhotoBundle(
            photo_path=still_out,
            video_path=video_out,
            asset_identifier=identifier,
            still_image_time_ms=int(still_time_ms),
            metadata={"video_source": video_source},
        )
