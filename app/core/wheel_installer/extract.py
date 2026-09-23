"""Extract wheel contents into a target site directory."""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path

from .errors import WheelInstallError


@dataclass(frozen=True, slots=True)
class WheelMetadata:
    """Parsed metadata from a wheel's .dist-info/METADATA file."""

    name: str
    version: str
    requires_dist: tuple[str, ...]


def read_wheel_metadata(wheel_path: Path) -> WheelMetadata:
    """Read and parse the METADATA file from a wheel.

    Args:
        wheel_path: Path to the .whl file.

    Returns:
        WheelMetadata with name, version, and requires_dist.

    Raises:
        WheelInstallError: If wheel is invalid or metadata missing/malformed.
    """
    try:
        with zipfile.ZipFile(wheel_path, "r") as zf:
            # Find the .dist-info/METADATA entry
            metadata_entries = [
                name for name in zf.namelist() if name.endswith(".dist-info/METADATA")
            ]
            if not metadata_entries:
                raise WheelInstallError(f"wheel 中未找到 .dist-info/METADATA：{wheel_path}")
            if len(metadata_entries) > 1:
                raise WheelInstallError(f"wheel 包含多个 .dist-info 目录：{wheel_path}")

            metadata_content = zf.read(metadata_entries[0]).decode("utf-8")
    except zipfile.BadZipFile as exc:
        raise WheelInstallError(f"无效的 wheel 文件：{exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise WheelInstallError(f"读取 wheel 失败：{exc}") from exc

    # Parse headers (RFC 822 style)
    name = None
    version = None
    requires_dist: list[str] = []

    for line in metadata_content.splitlines():
        if line.startswith("Name:"):
            name = line[5:].strip()
        elif line.startswith("Version:"):
            version = line[8:].strip()
        elif line.startswith("Requires-Dist:"):
            requires_dist.append(line[14:].strip())

    if not name or not version:
        raise WheelInstallError(f"METADATA 缺少 Name 或 Version：{wheel_path}")

    return WheelMetadata(
        name=name,
        version=version,
        requires_dist=tuple(requires_dist),
    )


def extract_wheel(wheel_path: Path, target: Path) -> Path:
    """Extract a wheel into the target site directory.

    Args:
        wheel_path: Path to the .whl file.
        target: Target directory (a site-packages-like directory).

    Returns:
        Path to the extracted .dist-info directory.

    Raises:
        WheelInstallError: On ZIP-slip attempt or extraction failure.
    """
    target.mkdir(parents=True, exist_ok=True)
    target_resolved = target.resolve()

    dist_info_path = None

    try:
        with zipfile.ZipFile(wheel_path, "r") as zf:
            for member in zf.infolist():
                # Resolve member path safely (ZIP-slip protection)
                member_path = (target / member.filename).resolve()
                try:
                    member_path.relative_to(target_resolved)
                except ValueError:
                    raise WheelInstallError(f"ZIP-slip 检测到路径逃逸：{member.filename}") from None

                if member.filename.endswith(".dist-info/"):
                    # Directory entry for .dist-info — extract as-is under target
                    zf.extract(member, target)
                    if dist_info_path is None:
                        dist_info_path = target / member.filename.rstrip("/")
                elif member.filename.endswith(".dist-info/"):
                    # Already handled above
                    pass
                elif member.filename.startswith(".data/"):
                    # Handle .data scheme subdirectories
                    # Format: .data/{scheme}/...
                    parts = member.filename.split("/")
                    if len(parts) >= 3:
                        scheme = parts[1]
                        if scheme in ("purelib", "platlib"):
                            # Extract contents under target (strip .data/{scheme}/ prefix)
                            rel_path = "/".join(parts[2:])
                            if rel_path:  # Skip directory entries
                                target_file = target / rel_path
                                target_file.parent.mkdir(parents=True, exist_ok=True)
                                if not member.is_dir():
                                    with zf.open(member) as src, open(target_file, "wb") as dst:
                                        dst.write(src.read())
                        # schemes 'scripts', 'headers', 'data' are skipped
                        # unknown schemes are also skipped
                else:
                    # Regular package files at root — extract under target
                    zf.extract(member, target)
                    # Track .dist-info directory if we encounter a file inside it
                    if member.filename.endswith(".dist-info/") or (
                        ".dist-info/" in member.filename and dist_info_path is None
                    ):
                        # Find the .dist-info directory from the member path
                        parts = member.filename.split(".dist-info/")
                        if parts:
                            dist_info_path = target / (parts[0] + ".dist-info")

    except zipfile.BadZipFile as exc:
        raise WheelInstallError(f"无效的 wheel 文件：{exc}") from exc
    except WheelInstallError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise WheelInstallError(f"解压 wheel 失败：{exc}") from exc

    if dist_info_path is None or not dist_info_path.exists():
        # Fallback: scan for .dist-info directory
        candidates = list(target.glob("*.dist-info"))
        if candidates:
            dist_info_path = candidates[0]
        else:
            raise WheelInstallError(f"解压后未找到 .dist-info 目录：{wheel_path}")

    return dist_info_path