"""Collect and normalize input files."""
from __future__ import annotations

from pathlib import Path

from app.config.schema import AppConfig
from app.core.models import FileRecord


IMAGE_FALLBACK_EXTS = {"jpg", "jpeg", "png", "webp", "tif", "tiff", "bmp"}


def collect_inputs(paths: list[Path], config: AppConfig) -> list[Path]:
    exts = {e.lower().lstrip(".") for e in config.input.extensions} or IMAGE_FALLBACK_EXTS
    found: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if not p.exists():
            continue
        if p.is_file():
            if p.suffix.lstrip(".").lower() in exts:
                found.append(p.resolve())
            continue
        if p.is_dir():
            iterator = p.rglob("*") if config.input.recurse_folders else p.glob("*")
            for child in sorted(iterator):
                if child.is_file() and child.suffix.lstrip(".").lower() in exts:
                    found.append(child.resolve())
    # stable unique
    seen: set[Path] = set()
    out: list[Path] = []
    for f in found:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


def to_records(files: list[Path]) -> list[FileRecord]:
    records: list[FileRecord] = []
    for i, f in enumerate(files, start=1):
        records.append(
            FileRecord(
                source_path=f,
                current_path=f,
                original_name=f.stem,
                original_ext=f.suffix.lstrip("."),
                index=i,
            )
        )
    return records
