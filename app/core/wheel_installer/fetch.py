"""Fetch wheel metadata and files from PyPI."""

from __future__ import annotations

import hashlib
import json
import os
import ssl
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

# 中国大陆境内可直接访问的 PyPI 镜像源，按优先级排序。
# 用户点“安装依赖”时自动尝试这些源，无需手动配置。
# 最后一位保留官方源作为兜底。
PYPI_MIRRORS: list[str] = [
    "https://pypi.tuna.tsinghua.edu.cn/pypi",
    "https://mirrors.aliyun.com/pypi/pypi",
    "https://pypi.mirrors.ustc.edu.cn/pypi",
    "https://pypi.douban.com/pypi",
    "https://pypi.org/pypi",
]
DEFAULT_TIMEOUT = 30


def _ssl_context():
    """Build an SSL context that trusts PyPI's certificate.

    Prefers the ``certifi`` CA bundle when available (more reliable inside
    frozen/PyInstaller builds), otherwise falls back to the system default
    verification. Returns ``None`` when verification should be left to
    ``urllib``'s default behaviour.
    """
    try:
        import certifi  # type: ignore

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001 - certifi optional
        return ssl.create_default_context()


def _pypi_json_urls(name: str) -> list[str]:
    """Build candidate JSON URLs for all PyPI mirrors."""
    return [f"{base}/{name}/json" for base in PYPI_MIRRORS]


def get_pypi_json(name: str) -> dict:
    """GET {mirror}/pypi/{name}/json via urllib.request.

    Automatically tries Chinese mainland PyPI mirrors first, then falls back
    to the official PyPI. No user configuration needed.

    Args:
        name: Package name (PEP 503 normalized or not).

    Returns:
        Parsed JSON response dict.

    Raises:
        PyPIError: When all mirrors fail.
    """
    last_error: str | None = None
    for url in _pypi_json_urls(name):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(
                req, timeout=DEFAULT_TIMEOUT, context=_ssl_context()
            ) as resp:
                data = resp.read()
        except ssl.SSLCertVerificationError as exc:
            last_error = (
                f"{url}: 无法验证服务器证书（SSL 证书验证失败）：{exc}"
            )
            continue
        except urllib.error.URLError as exc:
            last_error = f"{url}: 无法连接：{exc}"
            continue
        except Exception as exc:  # noqa: BLE001
            last_error = f"{url}: 请求失败：{exc}"
            continue

        try:
            return json.loads(data.decode("utf-8"))
        except json.JSONDecodeError as exc:
            last_error = f"{url}: 返回非 JSON 响应：{exc}"
            continue

    raise PyPIError(
        "所有 PyPI 镜像源均不可用，无法获取包元数据。\n"
        "最近一次错误：" + (last_error or "未知错误")
        + "\n请检查本机网络、系统时间，或代理/防火墙是否拦截了 SSL 连接。"
    )


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
        with urllib.request.urlopen(
            req, timeout=DEFAULT_TIMEOUT, context=_ssl_context()
        ) as resp:
            with open(tmp_path, "wb") as f:
                while True:
                    chunk = resp.read(8192)
                    if not chunk:
                        break
                    f.write(chunk)
                    sha256.update(chunk)
    except ssl.SSLCertVerificationError as exc:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
        raise PyPIError(
            "无法验证 PyPI 服务器证书（SSL 证书验证失败）。"
            "请检查本机系统时间是否正确，或网络代理/防火墙是否拦截了 SSL 连接。"
            f"详细错误：{exc}"
        ) from exc
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