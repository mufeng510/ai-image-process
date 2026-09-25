"""Local subtle-motion video generator (ffmpeg zoompan/pan)."""
from __future__ import annotations

import random
import subprocess
from pathlib import Path

from app.core.live_photo.providers.base import VideoGenerator, VideoGeneratorContext
from app.platform import CREATE_NO_WINDOW


class LocalMotionVideoGenerator(VideoGenerator):
    name = "local_motion"

    def __init__(self, ffmpeg: Path, *, motion_strength: float = 0.06) -> None:
        self.ffmpeg = Path(ffmpeg)
        self.motion_strength = max(0.01, min(0.25, float(motion_strength)))

    def generate(self, ctx: VideoGeneratorContext) -> Path:
        from PIL import Image

        with Image.open(ctx.still_image) as im:
            w, h = im.size
        # Cap video long-side for performance/size; never change aspect.
        max_side = 1920
        scale = min(1.0, max_side / max(w, h))
        vw, vh = int(w * scale), int(h * scale)
        vw -= vw % 2
        vh -= vh % 2
        n_frames = max(2, int(ctx.duration_seconds * ctx.fps))
        rng = random.Random(ctx.seed)
        direction = rng.choice([-1, 1])
        # Subtle zoom: 1.0 -> 1.0+strength over the clip (Ken Burns lite).
        z0, z1 = 1.0, 1.0 + self.motion_strength
        out = Path(ctx.work_dir) / "local_motion.mov"
        out.parent.mkdir(parents=True, exist_ok=True)
        # zoompan operates per-input-frame; single still looped.
        filt = (
            f"scale={vw * 4}:{vh * 4}:flags=lanczos,"
            f"zoompan=z='min({z0}+{z1 - z0:.5f}*on/{max(1, n_frames - 1)}"
            f",{z1:.5f})':x='iw/2-(iw/zoom/2){direction:+d}*on/{max(1, n_frames - 1)}*10'"
            f":y='ih/2-(ih/zoom/2)':d={n_frames}:fps={ctx.fps}:s={vw}x{vh}:"
            "flags=lanczos,format=yuv420p"
        )
        cmd = [
            str(self.ffmpeg), "-y",
            "-loop", "1", "-i", str(ctx.still_image),
            "-vf", filt,
            "-frames:v", str(n_frames),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-an",
            "-movflags", "faststart",
            str(out),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False,
                              creationflags=CREATE_NO_WINDOW)
        if proc.returncode != 0 or not out.exists():
            raise RuntimeError(f"ffmpeg local motion failed: {(proc.stderr or proc.stdout)[-2000:]}")
        return out
