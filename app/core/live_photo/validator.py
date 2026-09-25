"""Stage-1 Live Photo validator (local file validation, never claims Photos compat)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.core.live_photo.metadata import read_mov_livephoto_tags, read_photo_identifiers


@dataclass
class ValidationReport:
    ok: bool
    errors: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)


def _probe_video(mov: Path, ffprobe: Path | None) -> dict:
    info: dict = {"width": 0, "height": 0, "duration": 0.0, "codec": "", "has_video": False, "fps": 0.0}
    if ffprobe is not None and Path(ffprobe).exists():
        try:
            import json
            import subprocess

            from app.platform import CREATE_NO_WINDOW

            proc = subprocess.run(
                [str(ffprobe), "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height,codec_name,avg_frame_rate,duration",
                 "-show_entries", "format=duration", "-of", "json", str(mov)],
                capture_output=True, text=True, check=False, creationflags=CREATE_NO_WINDOW)
            if proc.returncode == 0 and proc.stdout.strip():
                data = json.loads(proc.stdout)
                streams = data.get("streams", [])
                if streams:
                    s = streams[0]
                    info["width"] = int(s.get("width") or 0)
                    info["height"] = int(s.get("height") or 0)
                    info["codec"] = str(s.get("codec_name") or "")
                    info["has_video"] = info["width"] > 0 and info["height"] > 0
                    try:
                        num, den = str(s.get("avg_frame_rate", "0/1")).split("/")
                        info["fps"] = float(num) / float(den) if float(den) else 0.0
                    except Exception:
                        pass
                try:
                    info["duration"] = float((data.get("format") or {}).get("duration") or (streams[0].get("duration") if streams else 0) or 0)
                except Exception:
                    pass
                return info
        except Exception:
            pass
    # Fallback: minimal BMFF box scan (ftyp+moov+mvhd/trak present, non-trivial size)
    try:
        raw = mov.read_bytes()
        info["has_video"] = b"moov" in raw and b"trak" in raw and len(raw) > 4096
        info["codec"] = "unknown"
        # mvhd duration is version-dependent; skip precise parse here.
    except Exception:
        pass
    return info


class LivePhotoValidator:
    def __init__(self, *, ffprobe: Path | None = None, exiftool=None) -> None:
        self.ffprobe = Path(ffprobe) if ffprobe else None
        self.exiftool = exiftool

    def validate(self, photo: Path, video: Path, expected_identifier: str | None = None) -> ValidationReport:
        errors: list[str] = []
        details: dict = {}
        # Photo checks
        if not photo.exists():
            errors.append(f"photo missing: {photo}")
        else:
            try:
                from PIL import Image

                with Image.open(photo) as im:
                    im.load()
                    details["photo_size"] = im.size
                    details["photo_format"] = im.format
                    if min(im.size) <= 0:
                        errors.append("photo has zero dimension")
            except Exception as exc:
                errors.append(f"photo unreadable: {exc}")
            p_ids = read_photo_identifiers(photo, exiftool=self.exiftool)
            details["photo_identifiers"] = p_ids
            if not p_ids:
                errors.append("photo asset identifier missing")
        # Movie checks
        if not video.exists():
            errors.append(f"movie missing: {video}")
        else:
            if video.suffix.lower() != ".mov":
                errors.append("movie must use .mov container")
            probe = _probe_video(video, self.ffprobe)
            details["movie_probe"] = probe
            if not probe.get("has_video"):
                errors.append("movie has no video track")
            if not (probe.get("duration", 0) or 0) > 0:
                # ffprobe-less fallback can't read duration; require size sanity
                try:
                    if video.stat().st_size < 4096:
                        errors.append("movie too small / duration unknown")
                except Exception:
                    errors.append("movie unreadable")
            if probe.get("width", 0) <= 0 or probe.get("height", 0) <= 0:
                if probe.get("codec") == "unknown":
                    pass  # fallback already asserted has_video
                else:
                    errors.append("movie has zero video dimensions")
            m = read_mov_livephoto_tags(video, exiftool=self.exiftool)
            details["movie_tags"] = m
            if not m.get("identifiers"):
                errors.append("movie content.identifier missing")
            if m.get("still_image_time_ms") is None:
                errors.append("movie still-image-time missing")
        # Pair checks
        p_ids = details.get("photo_identifiers", [])
        m_ids = (details.get("movie_tags") or {}).get("identifiers", [])
        if p_ids and m_ids and not (set(p_ids) & set(m_ids)):
            errors.append("photo/movie identifier mismatch")
        if expected_identifier:
            if expected_identifier not in (p_ids or []) or expected_identifier not in (m_ids or []):
                errors.append("bundle identifier does not match expected")
        # Aspect sanity: still vs movie aspect should be close (no deformation)
        try:
            pw, ph = details.get("photo_size", (0, 0))
            mw, mh = details.get("movie_probe", {}).get("width", 0), details.get("movie_probe", {}).get("height", 0)
            if pw > 0 and ph > 0 and mw > 0 and mh > 0:
                par = abs((pw / ph) - (mw / mh))
                details["aspect_delta"] = par
                if par > 0.05:
                    errors.append(f"aspect mismatch still {pw}x{ph} vs movie {mw}x{mh}")
        except Exception:
            pass
        return ValidationReport(ok=not errors, errors=errors, details=details)
