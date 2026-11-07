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
        z1 = 1.0 + self.motion_strength
        rng = random.Random(ctx.seed)
        # Two-phase handheld move: a quick ease-out zoom over the first
        # ~0.5s (like the lens settling the instant the shutter fires), then
        # the framing holds still with only a tiny sinusoidal jitter. This
        # reads far closer to a real handheld shot than a slow Ken Burns.
        ease_frames = min(n_frames - 1, max(2, int(0.5 * ctx.fps)))
        # pseudo-random phases so consecutive shots never jitter in sync
        p1, p2, p3, p4 = (rng.uniform(0, 6.2831853072) for _ in range(4))
        # amplitude in input (4x supersampled) pixels; ~1px at output scale
        amp = 4.0
        out = Path(ctx.work_dir) / "local_motion.mov"
        out.parent.mkdir(parents=True, exist_ok=True)
        # zoompan operates per-input-frame; single still looped.
        # NOTE: zoompan has no `flags` option (it was rejected by ffmpeg
        # 7.1 with "Option not found"); lanczos lives on the scale filter.
        z_expr = (
            f"if(lt(on,{ease_frames}),"
            f"1+{self.motion_strength:.5f}*(1-pow(1-on/{ease_frames},3)),"
            f"{z1:.5f})"
        )
        x_expr = (
            f"iw/2-(iw/zoom/2)"
            f"+{amp:.5f}*(sin(on*0.83+{p1:.5f})+0.55*sin(on*1.97+{p2:.5f}))"
        )
        y_expr = (
            f"ih/2-(ih/zoom/2)"
            f"+{amp:.5f}*(sin(on*0.71+{p3:.5f})+0.55*sin(on*2.31+{p4:.5f}))"
        )
        filt = (
            f"scale={vw * 4}:{vh * 4}:flags=lanczos,"
            f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}'"
            f":d={n_frames}:fps={ctx.fps}:s={vw}x{vh},"
            "format=yuv420p"
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
