"""Hidden-image library pool: scan, path-safety, assignment, deletion.

Only direct children of the configured library directory are considered
(no recursive scan unless the project later adds an explicit option).
"""
from __future__ import annotations

import os
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


def _norm(p: Path) -> Path:
    # Resolve symlinks/junctions, normalize case on Windows.
    try:
        r = p.expanduser().resolve()
    except OSError:
        r = p.expanduser().absolute()
    if os.name == "nt":
        return Path(str(r).lower())
    return r


def _is_within(child: Path, parent: Path) -> bool:
    c, par = _norm(child), _norm(parent)
    if c == par:
        return True
    try:
        c.relative_to(par)
        return True
    except ValueError:
        return False


def check_hidden_library_path_safety(
    library_dir: Path,
    input_dirs: Iterable[Path],
    output_dir: Path | None,
) -> str | None:
    """Return an error message if the hidden library overlaps input/output.

    Dangerous configurations (equal or nested in either direction) are refused
    so permanent deletion can never touch user inputs/outputs.
    """
    lib = _norm(Path(library_dir))
    outs: list[Path] = []
    if output_dir is not None:
        outs.append(_norm(Path(output_dir)))
    ins = [_norm(p) for p in input_dirs]
    for cand in ins:
        if cand == lib or _is_within(lib, cand) or _is_within(cand, lib):
            return (
                "隐藏图片库路径与输入目录存在重叠，存在误删风险，已拒绝启动。"
                f"隐藏库={library_dir} 输入={cand}"
            )
    for cand in outs:
        if cand == lib or _is_within(lib, cand) or _is_within(cand, lib):
            return (
                "隐藏图片库路径与输出目录存在重叠，存在误删风险，已拒绝启动。"
                f"隐藏库={library_dir} 输出={output_dir}"
            )
    return None


def is_supported_image(path: Path, supported_exts: set[str]) -> bool:
    return path.suffix.lstrip(".").lower() in supported_exts


def is_decodable_image(path: Path) -> bool:
    """True only if Pillow can fully decode the file (catches corrupt files)."""
    try:
        from PIL import Image

        with Image.open(path) as im:
            im.load()
        return True
    except Exception:
        return False


def scan_hidden_library(library_dir: Path, supported_exts: set[str]) -> list[Path]:
    """Scan direct children only; return sorted list of usable images."""
    lib = Path(library_dir)
    if not lib.is_dir():
        return []
    usable: list[Path] = []
    try:
        children = sorted(lib.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return []
    for child in children:
        try:
            if not child.is_file():
                continue
            if child.is_symlink() and not child.exists():
                continue  # dangling link
            # Resolve symlink/junction targets; must stay inside the library.
            resolved = child.resolve()
            if not _is_within(resolved, lib):
                continue
        except OSError:
            continue
        if not is_supported_image(child, supported_exts):
            continue
        if not is_decodable_image(child):
            continue
        usable.append(resolved if child.is_symlink() else child)
    return usable


@dataclass
class HiddenAssignmentPlan:
    mapping: dict[str, Path] = field(default_factory=dict)  # str(source) -> hidden path


def assign_hidden_images(
    sources: list[Path],
    pool: list[Path],
    rng: random.Random,
) -> HiddenAssignmentPlan:
    """Shuffle pool with project Rng and assign 1:1 without reuse."""
    shuffled = list(pool)
    rng.shuffle(shuffled)
    mapping: dict[str, Path] = {}
    for src, hidden in zip(sources, shuffled):
        mapping[str(src)] = hidden
    return HiddenAssignmentPlan(mapping=mapping)


def delete_hidden_image(path: Path, library_dir: Path) -> None:
    """Permanently delete one used hidden image with boundary re-check."""
    target = Path(path).expanduser()
    lib = Path(library_dir).expanduser()
    try:
        resolved_target = target.resolve()
    except OSError as exc:
        raise FileNotFoundError(f"hidden image missing: {target}") from exc
    # Same case-folding boundary rule as the preflight safety check.
    if not _is_within(resolved_target, lib):
        raise PermissionError(f"refusing to delete outside hidden library: {resolved_target}")
    if not resolved_target.is_file():
        raise FileNotFoundError(f"hidden image missing: {resolved_target}")
    # Windows: permanent delete, never via Recycle Bin (unlink does that).
    resolved_target.unlink()
