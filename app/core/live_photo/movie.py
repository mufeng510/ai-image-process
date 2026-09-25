"""MovieNormalizer: unify local/AI outputs into standard Live Photo MOV."""
from __future__ import annotations

import subprocess
from pathlib import Path

from app.platform import CREATE_NO_WINDOW


TARGET_FPS = 30.0


def normalize_movie(src: Path, dest: Path, *, ffmpeg: Path, duration_seconds: float = 3.0,
                    still_size: tuple[int, int] | None = None) -> Path:
    """Re-encode to MOV/H.264/yuv420p, no audio.

    When `still_size` is given, the output is scaled+cropped to exactly the
    still aspect (cover-style center crop, no stretch, no black bars) with
    the long side capped at 1920, so Stage-1 aspect validation passes for
    any provider-native aspect.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    if still_size and still_size[0] > 0 and still_size[1] > 0:
        sw, sh = still_size
        scale = min(1.0, 1920 / max(sw, sh))
        tw, th = max(2, int(sw * scale)), max(2, int(sh * scale))
        tw -= tw % 2
        th -= th % 2
        vf = (f"scale={tw}:{th}:force_original_aspect_ratio=increase,"
              f"crop={tw}:{th},setsar=1,format=yuv420p")
    else:
        vf = "scale='min(1920,iw)':'-2',scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p"
    cmd = [
        str(ffmpeg), "-y", "-i", str(src),
        "-vf", vf,
        "-r", str(int(TARGET_FPS)),
        "-t", str(float(duration_seconds)),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-an",
        "-movflags", "faststart",
        str(dest),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False,
                          creationflags=CREATE_NO_WINDOW)
    if proc.returncode != 0 or not dest.exists():
        raise RuntimeError(f"movie normalize failed: {(proc.stderr or proc.stdout)[-2000:]}")
    return dest
