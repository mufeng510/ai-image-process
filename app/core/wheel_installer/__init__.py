"""Pure-Python wheel installer for frozen PyInstaller builds.

This package replaces the broken in-process pip installer. It resolves
requirements from PyPI, downloads compatible wheels, and extracts them
into a target site directory — all without invoking pip.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

from .errors import PyPIError, ResolutionError, WheelInstallError
from .extract import WheelMetadata, extract_wheel, read_wheel_metadata
from .fetch import fetch_wheel, get_pypi_json, select_best_wheel
from .resolve import ResolvedWheel, resolve_and_fetch
from .tags import compute_compatible_tags

__all__ = [
    # Errors
    "WheelInstallError",
    "PyPIError",
    "ResolutionError",
    # Tags
    "compute_compatible_tags",
    # Fetch
    "get_pypi_json",
    "select_best_wheel",
    "fetch_wheel",
    # Extract
    "WheelMetadata",
    "read_wheel_metadata",
    "extract_wheel",
    # Resolve
    "ResolvedWheel",
    "resolve_and_fetch",
    # Orchestration
    "install_specs_to_target",
]


def install_specs_to_target(
    specs: list[str],
    target: Path,
    log: Callable[[str], None] | None = None,
) -> None:
    """Orchestration entry used by dependency_installer.

    1. Compute compatible tags
    2. Create temporary cache directory
    3. Resolve and fetch all wheels
    4. Extract each wheel into target
    5. Clean up cache directory

    Args:
        specs: List of requirement specifiers.
        target: Target site directory (e.g., runtime_site_dir()).
        log: Optional callback for progress logs (Chinese messages).

    Raises:
        WheelInstallError: On any failure (subclasses: PyPIError, ResolutionError).
    """
    if not specs:
        return

    tags = compute_compatible_tags()
    cache_dir = Path(tempfile.mkdtemp(prefix="aip-wheels-"))

    try:
        resolved = resolve_and_fetch(specs, target, tags, cache_dir, log)
        for r in resolved:
            if log:
                log(f"解压 {r.name} {r.version} …")
            extract_wheel(r.wheel_path, target)
        if log:
            log(f"安装完成（{len(resolved)} 个包）")
    finally:
        shutil.rmtree(cache_dir, ignore_errors=True)