
"""Output conflict policies."""
from __future__ import annotations

from enum import Enum
from pathlib import Path


class ConflictPolicy(str, Enum):
    OVERWRITE = "overwrite"
    SKIP = "skip"
    RENAME = "rename"


def resolve_output_path(path: Path, policy: ConflictPolicy) -> Path | None:
    """Return destination path, or None if skip."""
    if not path.exists():
        return path
    if policy == ConflictPolicy.OVERWRITE:
        return path
    if policy == ConflictPolicy.SKIP:
        return None
    # rename: name_1.ext, name_2.ext...
    stem, ext = path.stem, path.suffix
    parent = path.parent
    n = 1
    while True:
        candidate = parent / f"{stem}_{n}{ext}"
        if not candidate.exists():
            return candidate
        n += 1
