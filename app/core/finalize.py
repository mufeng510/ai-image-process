"""Final pixel-step metadata finalization: keep JPEG/sRGB/device tags alive.

Pixel transforms (rotate/crop, hidden composite) use Pillow saves that drop
EXIF/ICC. This helper re-applies the resolved device tags + sRGB ICC so the
final image still satisfies project metadata requirements without each step
inventing its own metadata logic.
"""
from __future__ import annotations

from pathlib import Path

from app.core.image_metadata import apply_final_metadata, build_device_tags, reembed_icc


def finalize_image_metadata(record, config, resources) -> None:
    """Re-apply ICC + device tags onto record.current_path (best effort)."""
    if not config.steps.device_metadata.enabled:
        # Still re-embed ICC so sRGB survives even with metadata step off.
        try:
            reembed_icc(Path(record.current_path), resources.get("icc_path"))
        except Exception:
            pass
        return
    device = getattr(record, "device", None)
    when = getattr(record, "capture_dt", None)
    if device is None or when is None:
        try:
            reembed_icc(Path(record.current_path), resources.get("icc_path"))
        except Exception:
            pass
        return
    hidden_src = getattr(record, "hidden_metadata_source", None) or {}
    tags = build_device_tags(
        make=device.make,
        model=device.model,
        lens=device.lens,
        when=when,
        software=config.steps.device_metadata.software_tag,
        hidden_src=hidden_src,
    )
    try:
        reembed_icc(Path(record.current_path), resources.get("icc_path"))
    except Exception:
        pass
    try:
        apply_final_metadata(Path(record.current_path), tags, exiftool=resources.get("exiftool"))
    except Exception:
        pass
