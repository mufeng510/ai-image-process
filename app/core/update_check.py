"""Check for a newer release on GitHub Releases.

Uses the public GitHub Releases API (``/releases/latest``), which by
definition returns the newest non-draft, non-prerelease release - main-branch
auto builds tagged ``vX.Y.Z-build.N`` are prereleases and never trigger the
update prompt.

Network access is deliberately tiny: one GET, JSON body, 10 s timeout. All
failure modes (no network, proxy interception, bad JSON, unparseable tag)
raise :class:`UpdateCheckError`; callers decide whether to surface the error
(manual check) or stay silent (startup check).
"""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass

from packaging.version import InvalidVersion, Version

from app.version import __version__

RELEASES_LATEST_API = "https://api.github.com/repos/mufeng510/ai-image-process/releases/latest"
RELEASES_PAGE = "https://github.com/mufeng510/ai-image-process/releases"
UA = f"ai-image-process/{__version__}"
DEFAULT_TIMEOUT = 10
# Release notes are rendered in a message box; keep the payload sane even if
# someone publishes a tag with a huge body.
MAX_NOTES_CHARS = 4000


class UpdateCheckError(Exception):
    """Any failure to determine whether a newer release exists."""


@dataclass(frozen=True)
class ReleaseInfo:
    """The latest stable release, as far as the caller needs it."""

    tag: str          # tag as published, e.g. "v0.8.0"
    version: str      # normalized version, e.g. "0.8.0"
    name: str         # release title (falls back to the tag)
    html_url: str     # release page the browser should open
    notes: str        # release body, truncated to MAX_NOTES_CHARS
    published_at: str  # ISO-8601 timestamp from the API (may be "")


def normalize_tag(tag: str) -> Version:
    """Parse a release tag like ``v0.8.0`` into a comparable Version."""
    text = (tag or "").strip()
    if text.lower().startswith("v"):
        text = text[1:]
    try:
        return Version(text)
    except InvalidVersion as exc:
        raise UpdateCheckError(f"无法解析 release tag：{tag!r}") from exc


def parse_release_payload(payload: dict) -> ReleaseInfo:
    """Turn the ``/releases/latest`` JSON payload into a ReleaseInfo."""
    if not isinstance(payload, dict):
        raise UpdateCheckError("GitHub 返回的数据格式不正确（不是 JSON 对象）")
    tag = str(payload.get("tag_name") or "").strip()
    if not tag:
        raise UpdateCheckError("GitHub 返回的 release 缺少 tag_name")
    version = normalize_tag(tag)
    notes = str(payload.get("body") or "")
    if len(notes) > MAX_NOTES_CHARS:
        notes = notes[:MAX_NOTES_CHARS] + "\n…（更新日志过长，已截断）"
    html_url = str(payload.get("html_url") or "").strip() or RELEASES_PAGE
    return ReleaseInfo(
        tag=tag,
        version=str(version),
        name=str(payload.get("name") or "").strip() or tag,
        html_url=html_url,
        notes=notes,
        published_at=str(payload.get("published_at") or ""),
    )


def is_newer_version(latest_tag: str, current_version: str = __version__) -> bool:
    """True when the tag names a release strictly newer than current_version."""
    latest = normalize_tag(latest_tag)
    try:
        current = Version(str(current_version).strip())
    except InvalidVersion as exc:
        raise UpdateCheckError(f"当前版本号无法解析：{current_version!r}") from exc
    return latest > current


def _ssl_context():
    """Certifi-backed SSL context when available, else system default."""
    try:
        import certifi  # type: ignore

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001 - certifi is optional
        return ssl.create_default_context()


def fetch_latest_release(timeout: int = DEFAULT_TIMEOUT) -> ReleaseInfo:
    """GET the latest stable release from GitHub. Raises UpdateCheckError."""
    req = urllib.request.Request(
        RELEASES_LATEST_API,
        headers={
            "User-Agent": UA,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
            data = resp.read()
    except ssl.SSLCertVerificationError as exc:
        raise UpdateCheckError(
            f"无法验证 GitHub 的 SSL 证书：{exc}\n请检查本机系统时间，或网络代理/防火墙是否拦截了 SSL 连接。"
        ) from exc
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateCheckError("仓库还没有任何正式 release（GitHub 返回 404）。") from exc
        raise UpdateCheckError(f"GitHub 返回 HTTP {exc.code}：{exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise UpdateCheckError(f"无法连接 GitHub：{exc.reason}") from exc
    except TimeoutError as exc:
        raise UpdateCheckError("连接 GitHub 超时，请检查网络后重试。") from exc
    except Exception as exc:  # noqa: BLE001 - network stack raises a zoo of errors
        raise UpdateCheckError(f"检查更新失败：{exc}") from exc

    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateCheckError("GitHub 返回了无法解析的响应（不是 JSON）。") from exc
    return parse_release_payload(payload)


def check_for_update(current_version: str = __version__) -> ReleaseInfo | None:
    """Return the newer ReleaseInfo, or None when already up to date.

    Raises UpdateCheckError when the latest release cannot be determined.
    """
    info = fetch_latest_release()
    if is_newer_version(info.tag, current_version):
        return info
    return None
