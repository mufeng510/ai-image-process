"""Fetch wheel metadata and files from PyPI."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

from packaging.specifiers import SpecifierSet
from packaging.tags import Tag
from packaging.utils import parse_wheel_filename

from app.version import __version__

from .errors import PyPIError, ResolutionError

if TYPE_CHECKING:
    from packaging.tags import Tag


UA = f"ai-image-process/{__version__}"
PYPI_BASE = "https://pypi.org/pypi"
DEFAULT_TIMEOUT = 30


def get_pypi_json(name: str) -> dict:
    """GET https://pypi.org/pypi/{name}/json via urllib.request.

    Args:
        name: Package name (PEP 503 normalized or not).

    Returns:
        Parsed JSON response dict.

    Raises:
        PyPIError: On network, HTTP, or JSON decode errors (Chinese message).
    """
    url = f"{PYPI_BASE}/{name}/json"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
            data = resp.read()
    except urllib.error.URLError as exc:
        raise PyPIError(f"无法连接 PyPI：{exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise PyPIError(f"请求 PyPI 失败：{exc}") from exc

    try:
        return json.loads(data.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise PyPIError(f"PyPI 返回非 JSON 响应：{exc}") from exc


def select_best_wheel(
    json_data: dict,
    specifier: SpecifierSet,
    tags: list[Tag],
) -> dict:
    """Select the best matching wheel from PyPI release data.

    Args:
        json_data: Parsed PyPI JSON (from get_pypi_json).
        specifier: Version specifier from the requirement.
        tags: Compatible tags from compute_compatible_tags().

    Returns:
        The release file dict (contains url, filename, digests.sha256).

    Raises:
        ResolutionError: If no compatible wheel satisfies the specifier.
    """
    releases = json_data.get("releases", {})
    tag_set = set(tags)

    best_version = None
    best_file = None

    for version_str, files in releases.items():
        # Skip yanked versions entirely
        if any(f.get("yanked", False) for f in files):
            continue

        try:
            from packaging.version import Version

            version = Version(version_str)
        except Exception:  # noqa: BLE001
            continue

        if version not in specifier:
            continue

        # Find best file for this version
        for file_info in files:
            if file_info.get("packagetype") != "bdist_wheel":
                continue
            if file_info.get("yanked", False):
                continue

            filename = file_info.get("filename", "")
            try:
                parsed = parse_wheel_filename(filename)
            except Exception:  # noqa: BLE001
                continue

            # parsed is (name, version, build, tags)
            file_tags = set(parsed[3])
            if not file_tags & tag_set:
                continue

            # This version satisfies and has a compatible wheel
            if best_version is None or version > best_version:
                best_version = version
                best_file = file_info

    if best_file is None:
        raise ResolutionError(
            f"无兼容 wheel：{json_data.get('info', {}).get('name', 'unknown')} {specifier}"
        )

    return best_file


def fetch_wheel(url: str, dest_dir: Path, expected_sha256: str | None = None) -> Path:
    """Stream-download a wheel into dest_dir atomically.

    Args:
        url: Wheel download URL.
        dest_dir: Destination directory (must exist).
        expected_sha256: Expected SHA256 hex digest (optional).

    Returns:
        Path to the downloaded wheel file.

    Raises:
        PyPIError: On download failure or SHA256 mismatch (Chinese message).
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    filename = os.path.basename(url)
    dest_path = dest_dir / filename
    tmp_path = dest_dir / f".{filename}.tmp"

    sha256 = hashlib.sha256()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
            with open(tmp_path, "wb") as f:
                while True:
                    chunk = resp.read(8192)
                    if not chunk:
                        break
                    f.write(chunk)
                    sha256.update(chunk)
    except urllib.error.URLError as exc:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
        raise PyPIError(f"下载失败：{exc}") from exc
    except Exception as exc:  # noqa: BLE001
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
        raise PyPIError(f"下载失败：{exc}") from exc

    if expected_sha256 is not None:
        actual = sha256.hexdigest()
        if actual.lower() != expected_sha256.lower():
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass
            raise PyPIError(f"校验失败：期望 {expected_sha256}，实际 {actual}")

    try:
        os.replace(tmp_path, dest_path)
    except Exception as exc:  # noqa: BLE001
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
        raise PyPIError(f"写入文件失败：{exc}") from exc

    return dest_path