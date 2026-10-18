"""Per-run output folder resolution.

Product behaviour: the user picks ONE directory, and every job publishes into
a fresh timestamped sub-folder of it, so repeated runs never mix or overwrite
each other and the input batch stays untouched.

    /data/exports/
        20261018-143052/   <- job 1
        20261018-150241/   <- job 2
        20261018-150241-2/ <- same second, second job in that second

Set `output.subfolder_per_run = False` to restore writing straight into the
chosen directory.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

TIMESTAMP_FORMAT = "%Y%m%d-%H%M%S"
MAX_SUFFIX_ATTEMPTS = 1000


def run_folder_name(when: datetime | None = None) -> str:
    return (when or datetime.now()).strftime(TIMESTAMP_FORMAT)


def resolve_run_folder(root: Path | str, *, when: datetime | None = None,
                       per_run: bool = True) -> Path:
    """Return the directory this job should publish into.

    Creates nothing — `output_write` owns directory creation so that a
    preflight failure still leaves no side effects on disk.
    """
    base = Path(root).expanduser()
    if not per_run:
        return base
    base = base / run_folder_name(when)
    if not base.exists():
        return base
    # Same second as an earlier run: walk -2, -3, ... without ever reusing or
    # overwriting an existing folder.
    n = 2
    while n <= MAX_SUFFIX_ATTEMPTS:
        candidate = base.with_name(f"{base.name}-{n}")
        if not candidate.exists():
            return candidate
        n += 1
    raise RuntimeError(
        f"无法为本次任务分配输出子目录（{base.name}-N 已存在 {MAX_SUFFIX_ATTEMPTS} 个）：{base.parent}")