"""Per-run output folder resolution.

Product behaviour: the user picks ONE directory, and every job publishes into
a fresh sub-folder of it, so repeated runs never mix or overwrite each other
and the input batch stays untouched.

    /data/exports/
        1028-1430-旅行照片/    <- job 1 (MMDD-HHmm + source hint)
        1028-1430-旅行照片-2/  <- second job in the same minute
        1102-0915-2026日本/    <- next batch

The name leads with a short timestamp (keeps chronological sorting) and ends
with a sanitized hint taken from the source folder, so a glance at the folder
tells you roughly what is inside. `output.subfolder_per_run = False` restores
writing straight into the chosen directory.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Sequence

TIMESTAMP_FORMAT = "%m%d-%H%M"
MAX_PREFIX_LEN = 8
MAX_SUFFIX_ATTEMPTS = 1000

# Windows forbids these in file/folder names; NUL and control characters are
# illegal everywhere. Replacing them keeps one naming rule across platforms.
_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1F]')


def _sanitize_prefix(raw: object, max_len: int = MAX_PREFIX_LEN) -> str:
    """Make a source name safe as a folder-name component."""
    cleaned = _INVALID_CHARS.sub("_", str(raw or ""))
    # Windows also rejects trailing dots/spaces; leading/trailing underscores
    # are just noise after a character replacement.
    cleaned = cleaned.strip(" ._")[:max_len].strip(" ._")
    return cleaned or "batch"


def run_folder_prefix(inputs: Sequence[Path | str]) -> str:
    """Derive the hint from the first input: folder name, or a file's parent.

    Multiple inputs are intentionally reduced to the first one -- the rule is
    deterministic and easy to document. No inputs means no hint at all.
    """
    for raw in inputs or ():
        p = Path(raw)
        candidate = p.name if p.is_dir() else p.parent.name
        return _sanitize_prefix(candidate)
    return ""


def run_folder_name(when: datetime | None = None, prefix: str | None = None) -> str:
    stamp = (when or datetime.now()).strftime(TIMESTAMP_FORMAT)
    if prefix:
        return f"{stamp}-{_sanitize_prefix(prefix)}"
    return stamp


def resolve_run_folder(
    root: Path | str,
    *,
    when: datetime | None = None,
    per_run: bool = True,
    prefix: str | None = None,
) -> Path:
    """Return the directory this job should publish into.

    Creates nothing — `output_write` owns directory creation so that a
    preflight failure still leaves no side effects on disk.
    """
    base = Path(root).expanduser()
    if not per_run:
        return base
    base = base / run_folder_name(when, prefix)
    if not base.exists():
        return base
    # Same minute as an earlier run: walk -2, -3, ... without ever reusing or
    # overwriting an existing folder.
    n = 2
    while n <= MAX_SUFFIX_ATTEMPTS:
        candidate = base.with_name(f"{base.name}-{n}")
        if not candidate.exists():
            return candidate
        n += 1
    raise RuntimeError(
        f"无法为本次任务分配输出子目录（{base.name}-N 已存在 {MAX_SUFFIX_ATTEMPTS} 个）：{base.parent}")
