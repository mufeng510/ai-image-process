"""Offline tests for the GitHub Releases update check.

The urllib seam is mocked at the module level; no network access.
"""
from __future__ import annotations

import io
import json
import urllib.error
from unittest.mock import patch

import pytest

from app.core import update_check
from app.core.update_check import (
    RELEASES_LATEST_API,
    MAX_NOTES_CHARS,
    ReleaseInfo,
    UpdateCheckError,
    check_for_update,
    fetch_latest_release,
    is_newer_version,
    normalize_tag,
    parse_release_payload,
)


def _payload(tag: str = "v0.8.0", **overrides) -> dict:
    base = {
        "tag_name": tag,
        "name": f"Release {tag}",
        "html_url": "https://github.com/mufeng510/ai-image-process/releases/tag/" + tag,
        "body": "what changed",
        "published_at": "2026-11-09T00:00:00Z",
    }
    base.update(overrides)
    return base


class _FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_normalize_tag_accepts_v_prefix_and_plain():
    assert str(normalize_tag("v0.8.0")) == "0.8.0"
    assert str(normalize_tag("0.8.0")) == "0.8.0"
    assert str(normalize_tag("V1.2.3")) == "1.2.3"


def test_normalize_tag_rejects_garbage():
    with pytest.raises(UpdateCheckError):
        normalize_tag("not-a-version")
    with pytest.raises(UpdateCheckError):
        normalize_tag("")


def test_is_newer_version_compares_semver():
    assert is_newer_version("v0.10.0", "0.7.0")
    assert not is_newer_version("v0.7.0", "0.7.0")
    assert not is_newer_version("v0.6.9", "0.7.0")
    # numeric, not lexicographic: 0.10.0 > 0.9.0
    assert is_newer_version("v0.10.0", "0.9.0")


def test_parse_release_payload_happy_path():
    info = parse_release_payload(_payload("v0.8.0"))
    assert info.tag == "v0.8.0"
    assert info.version == "0.8.0"
    assert info.html_url.endswith("/tag/v0.8.0")
    assert info.notes == "what changed"


def test_parse_release_payload_falls_back_to_releases_page_and_tag_name():
    info = parse_release_payload(_payload("v0.8.0", html_url="", name=""))
    assert info.html_url == update_check.RELEASES_PAGE
    assert info.name == "v0.8.0"


def test_parse_release_payload_truncates_huge_notes():
    info = parse_release_payload(_payload("v0.8.0", body="x" * (MAX_NOTES_CHARS + 500)))
    assert len(info.notes) <= MAX_NOTES_CHARS + len("\n…（更新日志过长，已截断）")


def test_parse_release_payload_requires_tag():
    with pytest.raises(UpdateCheckError):
        parse_release_payload({"name": "no tag here"})
    with pytest.raises(UpdateCheckError):
        parse_release_payload(["not", "a", "dict"])  # type: ignore[arg-type]


def test_fetch_latest_release_hits_latest_endpoint():
    captured = {}

    def fake_urlopen(req, timeout, context):
        captured["url"] = req.full_url
        captured["ua"] = req.headers.get("User-agent")
        return _FakeResponse(json.dumps(_payload("v0.8.0")).encode("utf-8"))

    with patch.object(update_check.urllib.request, "urlopen", fake_urlopen):
        info = fetch_latest_release()
    assert captured["url"] == RELEASES_LATEST_API
    assert captured["ua"].startswith("ai-image-process/")
    assert info.version == "0.8.0"


def test_fetch_latest_release_http_error_raises():
    def fake_urlopen(req, timeout, context):
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, io.BytesIO(b""))

    with patch.object(update_check.urllib.request, "urlopen", fake_urlopen):
        with pytest.raises(UpdateCheckError, match="403"):
            fetch_latest_release()


def test_fetch_latest_release_network_error_raises():
    def fake_urlopen(req, timeout, context):
        raise urllib.error.URLError("no route to host")

    with patch.object(update_check.urllib.request, "urlopen", fake_urlopen):
        with pytest.raises(UpdateCheckError):
            fetch_latest_release()


def test_fetch_latest_release_bad_json_raises():
    with patch.object(
        update_check.urllib.request,
        "urlopen",
        lambda req, timeout, context: _FakeResponse(b"<html>oops</html>"),
    ):
        with pytest.raises(UpdateCheckError):
            fetch_latest_release()


def test_check_for_update_returns_none_when_current():
    with patch.object(update_check, "fetch_latest_release", lambda: parse_release_payload(_payload("v0.7.0"))):
        assert check_for_update("0.7.0") is None


def test_check_for_update_returns_release_when_newer():
    with patch.object(update_check, "fetch_latest_release", lambda: parse_release_payload(_payload("v0.9.0"))):
        info = check_for_update("0.7.0")
        assert isinstance(info, ReleaseInfo)
        assert info.version == "0.9.0"
