"""Offline tests for the pure-Python wheel installer.

All tests use fixture wheels built with zipfile; no network access.
The urllib seam is mocked at the fetch module level.
"""

from __future__ import annotations

import hashlib
import io
import json
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

import pytest
from packaging.specifiers import SpecifierSet
from packaging.tags import Tag
from packaging.version import Version

from app.core.wheel_installer import (
    WheelInstallError,
    PyPIError,
    ResolutionError,
    compute_compatible_tags,
    select_best_wheel,
    fetch_wheel,
    read_wheel_metadata,
    extract_wheel,
    resolve_and_fetch,
    install_specs_to_target,
    WheelMetadata,
    ResolvedWheel,
)


# =============================================================================
# Fixture wheel builder
# =============================================================================

def make_wheel(
    tmp_path: Path,
    name: str,
    version: str,
    requires: tuple[str, ...] = (),
    tag: str = "py3-none-any",
    extra_files: dict[str, bytes] | None = None,
) -> Path:
    """Build a valid wheel zip file for testing.

    Args:
        tmp_path: Temporary directory to write the wheel.
        name: Package name (e.g., "my-package").
        version: Version string (e.g., "1.0.0").
        requires: Requires-Dist entries.
        tag: Wheel tag (default: py3-none-any).
        extra_files: Additional files to include in the wheel.

    Returns:
        Path to the created .whl file.
    """
    normalized = name.lower().replace("_", "-").replace(".", "-")
    wheel_name = f"{normalized}-{version}-{tag}.whl"
    wheel_path = tmp_path / wheel_name

    dist_info = f"{normalized}-{version}.dist-info"

    # Build METADATA content
    metadata_lines = [
        f"Metadata-Version: 2.1",
        f"Name: {name}",
        f"Version: {version}",
        f"Summary: Test package",
    ]
    for req in requires:
        metadata_lines.append(f"Requires-Dist: {req}")
    metadata_content = "\n".join(metadata_lines) + "\n"

    # Build WHEEL content
    wheel_content = f"""Wheel-Version: 1.0
Generator: test
Root-Is-Purelib: true
Tag: {tag}
"""

    with zipfile.ZipFile(wheel_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # Package __init__.py
        zf.writestr(f"{normalized}/__init__.py", f"# {name} {version}\n")

        # .dist-info/METADATA
        zf.writestr(f"{dist_info}/METADATA", metadata_content)

        # .dist-info/WHEEL
        zf.writestr(f"{dist_info}/WHEEL", wheel_content)

        # .dist-info/RECORD (minimal)
        record_lines = [
            f"{normalized}/__init__.py,,",
            f"{dist_info}/METADATA,,",
            f"{dist_info}/WHEEL,,",
            f"{dist_info}/RECORD,,",
        ]
        zf.writestr(f"{dist_info}/RECORD", "\n".join(record_lines) + "\n")

        # Extra files (e.g., .data/purelib/...)
        if extra_files:
            for arcname, content in extra_files.items():
                zf.writestr(arcname, content)

    return wheel_path


def make_wheel_with_data(
    tmp_path: Path,
    name: str,
    version: str,
    requires: tuple[str, ...] = (),
    tag: str = "py3-none-any",
    purelib_files: dict[str, bytes] | None = None,
) -> Path:
    """Build a wheel with .data/purelib entries."""
    extra = {}
    if purelib_files:
        for rel, content in purelib_files.items():
            extra[f".data/purelib/{rel}"] = content
    return make_wheel(tmp_path, name, version, requires, tag, extra)


# =============================================================================
# Tests for compute_compatible_tags
# =============================================================================

def test_compute_compatible_tags_returns_non_empty():
    """compute_compatible_tags returns a non-empty list of Tag objects."""
    tags = compute_compatible_tags()
    assert isinstance(tags, list)
    assert len(tags) > 0
    assert all(isinstance(t, Tag) for t in tags)


# =============================================================================
# Tests for select_best_wheel
# =============================================================================

def test_select_best_wheel_picks_highest_satisfying_version():
    """select_best_wheel picks the highest version satisfying the specifier."""
    json_data = {
        "info": {"name": "test-pkg"},
        "releases": {
            "1.0.0": [{"filename": "test_pkg-1.0.0-py3-none-any.whl", "packagetype": "bdist_wheel", "yanked": False, "url": "http://example.com/1.0.0.whl", "digests": {"sha256": "a" * 64}}],
            "2.0.0": [{"filename": "test_pkg-2.0.0-py3-none-any.whl", "packagetype": "bdist_wheel", "yanked": False, "url": "http://example.com/2.0.0.whl", "digests": {"sha256": "b" * 64}}],
            "3.0.0": [{"filename": "test_pkg-3.0.0-py3-none-any.whl", "packagetype": "bdist_wheel", "yanked": False, "url": "http://example.com/3.0.0.whl", "digests": {"sha256": "c" * 64}}],
        },
    }
    tags = [Tag("py3", "none", "any")]
    specifier = SpecifierSet(">=1.0.0")
    result = select_best_wheel(json_data, specifier, tags)
    assert result["filename"] == "test_pkg-3.0.0-py3-none-any.whl"


def test_select_best_wheel_skips_yanked():
    """select_best_wheel skips yanked files."""
    json_data = {
        "info": {"name": "test-pkg"},
        "releases": {
            "2.0.0": [{"filename": "test_pkg-2.0.0-py3-none-any.whl", "packagetype": "bdist_wheel", "yanked": True, "url": "http://example.com/2.0.0.whl", "digests": {"sha256": "b" * 64}}],
            "1.0.0": [{"filename": "test_pkg-1.0.0-py3-none-any.whl", "packagetype": "bdist_wheel", "yanked": False, "url": "http://example.com/1.0.0.whl", "digests": {"sha256": "a" * 64}}],
        },
    }
    tags = [Tag("py3", "none", "any")]
    specifier = SpecifierSet(">=1.0.0")
    result = select_best_wheel(json_data, specifier, tags)
    assert result["filename"] == "test_pkg-1.0.0-py3-none-any.whl"


def test_select_best_wheel_skips_incompatible_platform_tag():
    """select_best_wheel skips wheels with incompatible platform tags."""
    json_data = {
        "info": {"name": "test-pkg"},
        "releases": {
            "1.0.0": [
                {"filename": "test_pkg-1.0.0-cp310-win_amd64.whl", "packagetype": "bdist_wheel", "yanked": False, "url": "http://example.com/win.whl", "digests": {"sha256": "a" * 64}},
                {"filename": "test_pkg-1.0.0-py3-none-any.whl", "packagetype": "bdist_wheel", "yanked": False, "url": "http://example.com/any.whl", "digests": {"sha256": "b" * 64}},
            ],
        },
    }
    # Only py3-none-any compatible
    tags = [Tag("py3", "none", "any")]
    specifier = SpecifierSet(">=1.0.0")
    result = select_best_wheel(json_data, specifier, tags)
    assert result["filename"] == "test_pkg-1.0.0-py3-none-any.whl"


def test_select_best_wheel_raises_resolution_error_when_none():
    """select_best_wheel raises ResolutionError when no compatible wheel."""
    json_data = {
        "info": {"name": "test-pkg"},
        "releases": {
            "1.0.0": [{"filename": "test_pkg-1.0.0-cp310-win_amd64.whl", "packagetype": "bdist_wheel", "yanked": False, "url": "http://example.com/win.whl", "digests": {"sha256": "a" * 64}}],
        },
    }
    tags = [Tag("py3", "none", "any")]
    specifier = SpecifierSet(">=1.0.0")
    with pytest.raises(ResolutionError, match="无兼容 wheel"):
        select_best_wheel(json_data, specifier, tags)


# =============================================================================
# Tests for fetch_wheel
# =============================================================================

def test_fetch_wheel_sha256_ok(tmp_path: Path):
    """fetch_wheel downloads and verifies SHA256."""
    content = b"hello wheel"
    sha256 = hashlib.sha256(content).hexdigest()

    def mock_urlopen(req, timeout=None):
        class Resp:
            def __init__(self):
                self._done = False
            def read(self, size=-1):
                if self._done:
                    return b""
                self._done = True
                return content
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
        return Resp()

    with patch("urllib.request.urlopen", mock_urlopen):
        dest = fetch_wheel("http://example.com/wheel.whl", tmp_path, sha256)
        assert dest.exists()
        assert dest.read_bytes() == content


def test_fetch_wheel_sha256_mismatch_raises(tmp_path: Path):
    """fetch_wheel raises PyPIError on SHA256 mismatch."""
    content = b"hello wheel"
    wrong_sha256 = "0" * 64

    def mock_urlopen(req, timeout=None):
        class Resp:
            def __init__(self):
                self._done = False
            def read(self, size=-1):
                if self._done:
                    return b""
                self._done = True
                return content
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
        return Resp()

    with patch("urllib.request.urlopen", mock_urlopen):
        with pytest.raises(PyPIError, match="校验失败"):
            fetch_wheel("http://example.com/wheel.whl", tmp_path, wrong_sha256)
        # No leftover .tmp file
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0


def test_fetch_wheel_atomic_no_leftover_tmp_on_success(tmp_path: Path):
    """fetch_wheel leaves no .tmp file on success."""
    content = b"hello wheel"
    sha256 = hashlib.sha256(content).hexdigest()

    def mock_urlopen(req, timeout=None):
        class Resp:
            def __init__(self):
                self._done = False
            def read(self, size=-1):
                if self._done:
                    return b""
                self._done = True
                return content
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
        return Resp()

    with patch("urllib.request.urlopen", mock_urlopen):
        fetch_wheel("http://example.com/wheel.whl", tmp_path, sha256)
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0


# =============================================================================
# Tests for read_wheel_metadata
# =============================================================================

def test_read_wheel_metadata_parses_multiple_requires_dist(tmp_path: Path):
    """read_wheel_metadata parses multiple Requires-Dist lines."""
    wheel = make_wheel(tmp_path, "test-pkg", "1.0.0", requires=("requests>=2.0", "numpy>=1.20; extra == 'vis'"))
    meta = read_wheel_metadata(wheel)
    assert meta.name == "test-pkg"
    assert meta.version == "1.0.0"
    assert meta.requires_dist == ("requests>=2.0", "numpy>=1.20; extra == 'vis'")


# =============================================================================
# Tests for extract_wheel
# =============================================================================

def test_extract_wheel_purelib_package_lands_in_target(tmp_path: Path):
    """extract_wheel places purelib package contents in target."""
    wheel = make_wheel_with_data(
        tmp_path, "test-pkg", "1.0.0",
        purelib_files={"test_pkg/__init__.py": b"# init\n", "test_pkg/mod.py": b"# mod\n"},
    )
    target = tmp_path / "site"
    dist_info = extract_wheel(wheel, target)

    assert (target / "test_pkg" / "__init__.py").exists()
    assert (target / "test_pkg" / "mod.py").exists()
    assert dist_info.exists()
    assert dist_info.name.endswith(".dist-info")


def test_extract_wheel_dist_info_lands_in_target(tmp_path: Path):
    """extract_wheel places .dist-info directory in target."""
    wheel = make_wheel(tmp_path, "test-pkg", "1.0.0")
    target = tmp_path / "site"
    dist_info = extract_wheel(wheel, target)

    assert dist_info.exists()
    assert (dist_info / "METADATA").exists()
    assert (dist_info / "WHEEL").exists()


def test_extract_wheel_data_scripts_not_extracted(tmp_path: Path):
    """extract_wheel does NOT extract .data/scripts entries."""
    extra = {
        ".data/scripts/script.py": b"#!/usr/bin/env python\nprint('hi')\n",
        ".data/purelib/test_pkg/__init__.py": b"# init\n",
    }
    wheel = make_wheel(tmp_path, "test-pkg", "1.0.0", extra_files=extra)
    target = tmp_path / "site"
    extract_wheel(wheel, target)

    assert (target / "test_pkg" / "__init__.py").exists()
    assert not (target / "script.py").exists()
    assert not (target / "scripts" / "script.py").exists()


def test_extract_wheel_zip_slip_raises(tmp_path: Path):
    """extract_wheel raises WheelInstallError on ZIP-slip attempt."""
    # Create a wheel with a malicious path
    wheel_path = tmp_path / "evil.whl"
    with zipfile.ZipFile(wheel_path, "w") as zf:
        zf.writestr("../escape.txt", "evil")
        zf.writestr("test_pkg/__init__.py", "# init\n")
        zf.writestr("test_pkg-1.0.0.dist-info/METADATA", "Name: test-pkg\nVersion: 1.0.0\n")
        zf.writestr("test_pkg-1.0.0.dist-info/WHEEL", "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n")

    target = tmp_path / "site"
    with pytest.raises(WheelInstallError, match="ZIP-slip"):
        extract_wheel(wheel_path, target)


# =============================================================================
# Tests for resolve_and_fetch (with mocked fetch seam)
# =============================================================================

class MockFetch:
    """Mock fetch seam for resolve_and_fetch tests."""

    def __init__(self, wheels: dict[tuple[str, str], Path]):
        # wheels: (normalized_name, version) -> wheel_path
        self.wheels = wheels
        self.json_cache: dict[str, dict] = {}

    def mock_get_pypi_json(self, name: str) -> dict:
        norm = name.lower().replace("_", "-").replace(".", "-")
        if norm in self.json_cache:
            return self.json_cache[norm]
        # Build JSON with all versions for this package
        releases = {}
        for (w_name, w_version), wheel_path in self.wheels.items():
            if w_name != norm:
                continue
            from app.core.wheel_installer.extract import read_wheel_metadata
            meta = read_wheel_metadata(wheel_path)
            filename = wheel_path.name
            sha256 = hashlib.sha256(wheel_path.read_bytes()).hexdigest()
            if meta.version not in releases:
                releases[meta.version] = []
            releases[meta.version].append({
                "filename": filename,
                "packagetype": "bdist_wheel",
                "yanked": False,
                "url": f"http://example.com/{filename}",
                "digests": {"sha256": sha256},
            })
        json_data = {
            "info": {"name": norm},
            "releases": releases,
        }
        self.json_cache[norm] = json_data
        return json_data

    def mock_fetch_wheel(self, url: str, dest_dir: Path, expected_sha256: str | None = None) -> Path:
        filename = url.split("/")[-1]
        # Find wheel by filename
        for (norm, version), path in self.wheels.items():
            if path.name == filename:
                dest = dest_dir / filename
                dest.write_bytes(path.read_bytes())
                return dest
        raise PyPIError(f"Mock wheel not found: {filename}")


def test_resolve_no_deps_single_package(tmp_path: Path):
    """resolve_and_fetch resolves a single package with no dependencies."""
    wheel = make_wheel(tmp_path, "simplepkg", "1.0.0")
    mock = MockFetch({("simplepkg", "1.0.0"): wheel})
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    target = tmp_path / "site"
    target.mkdir()
    tags = [Tag("py3", "none", "any")]

    with patch("app.core.wheel_installer.resolve.get_pypi_json", mock.mock_get_pypi_json), \
         patch("app.core.wheel_installer.resolve.fetch_wheel", mock.mock_fetch_wheel):
        resolved = resolve_and_fetch(["simplepkg>=1.0.0"], target, tags, cache_dir)

    assert len(resolved) == 1
    assert resolved[0].name == "simplepkg"
    assert resolved[0].version == Version("1.0.0")


def test_resolve_transitive_a_b_c(tmp_path: Path):
    """resolve_and_fetch resolves transitive A->B->C."""
    # C has no deps
    wheel_c = make_wheel(tmp_path, "pkgc", "1.0.0")
    # B depends on C
    wheel_b = make_wheel(tmp_path, "pkgb", "2.0.0", requires=("pkgc>=1.0.0",))
    # A depends on B
    wheel_a = make_wheel(tmp_path, "pkga", "3.0.0", requires=("pkgb>=2.0.0",))

    mock = MockFetch({("pkga", "3.0.0"): wheel_a, ("pkgb", "2.0.0"): wheel_b, ("pkgc", "1.0.0"): wheel_c})
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    target = tmp_path / "site"
    target.mkdir()
    tags = [Tag("py3", "none", "any")]

    with patch("app.core.wheel_installer.resolve.get_pypi_json", mock.mock_get_pypi_json), \
         patch("app.core.wheel_installer.resolve.fetch_wheel", mock.mock_fetch_wheel):
        resolved = resolve_and_fetch(["pkga>=3.0.0"], target, tags, cache_dir)

    assert len(resolved) == 3
    # Order: C, B, A (dependencies before dependents)
    names = [r.name for r in resolved]
    assert names.index("pkgc") < names.index("pkgb")
    assert names.index("pkgb") < names.index("pkga")


def test_resolve_extras_marker_gating(tmp_path: Path):
    """resolve_and_fetch respects extra markers (only when extras set)."""
    # pkga has extra 'vis' that pulls pkgb
    wheel_a = make_wheel(tmp_path, "pkga", "1.0.0", requires=("pkgb>=1.0; extra == 'vis'",))
    wheel_b = make_wheel(tmp_path, "pkgb", "1.0.0")

    mock = MockFetch({("pkga", "1.0.0"): wheel_a, ("pkgb", "1.0.0"): wheel_b})
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    target = tmp_path / "site"
    target.mkdir()
    tags = [Tag("py3", "none", "any")]

    with patch("app.core.wheel_installer.resolve.get_pypi_json", mock.mock_get_pypi_json), \
         patch("app.core.wheel_installer.resolve.fetch_wheel", mock.mock_fetch_wheel):
        # Without extra - should NOT pull pkgb
        resolved = resolve_and_fetch(["pkga>=1.0.0"], target, tags, cache_dir)
        names = [r.name for r in resolved]
        assert names == ["pkga"]

        # With extra - SHOULD pull pkgb
        resolved = resolve_and_fetch(["pkga[vis]>=1.0.0"], target, tags, cache_dir)
        names = [r.name for r in resolved]
        assert "pkgb" in names
        assert names.index("pkgb") < names.index("pkga")


def test_resolve_env_marker_gating(tmp_path: Path):
    """resolve_and_fetch respects environment markers (sys_platform == 'never' excludes)."""
    # pkga depends on pkgb only on a never-matching platform
    wheel_a = make_wheel(tmp_path, "pkga", "1.0.0", requires=("pkgb>=1.0; sys_platform == 'never'",))
    wheel_b = make_wheel(tmp_path, "pkgb", "1.0.0")

    mock = MockFetch({("pkga", "1.0.0"): wheel_a, ("pkgb", "1.0.0"): wheel_b})
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    target = tmp_path / "site"
    target.mkdir()
    tags = [Tag("py3", "none", "any")]

    with patch("app.core.wheel_installer.resolve.get_pypi_json", mock.mock_get_pypi_json), \
         patch("app.core.wheel_installer.resolve.fetch_wheel", mock.mock_fetch_wheel):
        resolved = resolve_and_fetch(["pkga>=1.0.0"], target, tags, cache_dir)
        names = [r.name for r in resolved]
        assert names == ["pkga"]


def test_resolve_already_installed_skip_still_walks_deps(tmp_path: Path):
    """Already-installed package is skipped but its deps are still walked."""
    # Pre-install pkgb in target
    target = tmp_path / "site"
    target.mkdir()
    wheel_b = make_wheel(tmp_path, "pkgb", "1.0.0", requires=("pkgc>=1.0.0",))
    # Extract pkgb into target to simulate pre-installed
    extract_wheel(wheel_b, target)

    # pkga depends on pkgb
    wheel_a = make_wheel(tmp_path, "pkga", "1.0.0", requires=("pkgb>=1.0.0",))
    wheel_c = make_wheel(tmp_path, "pkgc", "1.0.0")

    mock = MockFetch({("pkga", "1.0.0"): wheel_a, ("pkgb", "1.0.0"): wheel_b, ("pkgc", "1.0.0"): wheel_c})
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    tags = [Tag("py3", "none", "any")]

    with patch("app.core.wheel_installer.resolve.get_pypi_json", mock.mock_get_pypi_json), \
         patch("app.core.wheel_installer.resolve.fetch_wheel", mock.mock_fetch_wheel):
        resolved = resolve_and_fetch(["pkga>=1.0.0"], target, tags, cache_dir)

    names = [r.name for r in resolved]
    # pkgb should not be in resolved (already installed)
    # but pkgc should be (transitive dep of pkgb)
    assert "pkgb" not in names
    assert "pkgc" in names
    assert "pkga" in names


def test_resolve_pin_conflict_raises(tmp_path: Path):
    """Conflicting version requirements raise ResolutionError."""
    # pkga requires pkgb==1.0.0 exactly
    wheel_a = make_wheel(tmp_path, "pkga", "1.0.0", requires=("pkgb==1.0.0",))
    wheel_b1 = make_wheel(tmp_path, "pkgb", "1.0.0")
    wheel_b2 = make_wheel(tmp_path, "pkgb", "2.0.0")

    # Both versions available on PyPI
    mock = MockFetch({("pkga", "1.0.0"): wheel_a, ("pkgb", "1.0.0"): wheel_b1, ("pkgb", "2.0.0"): wheel_b2})
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    target = tmp_path / "site"
    target.mkdir()
    tags = [Tag("py3", "none", "any")]

    with patch("app.core.wheel_installer.resolve.get_pypi_json", mock.mock_get_pypi_json), \
         patch("app.core.wheel_installer.resolve.fetch_wheel", mock.mock_fetch_wheel):
        # pkga requires pkgb==1.0.0, but user also requires pkgb==2.0.0 -> conflict
        with pytest.raises(ResolutionError, match="依赖冲突"):
            resolve_and_fetch(["pkga>=1.0.0", "pkgb==2.0.0"], target, tags, cache_dir)


def test_resolve_cycle_terminates(tmp_path: Path):
    """Cyclic dependencies (A->B->A) terminate without infinite loop."""
    wheel_a = make_wheel(tmp_path, "pkga", "1.0.0", requires=("pkgb>=1.0.0",))
    wheel_b = make_wheel(tmp_path, "pkgb", "1.0.0", requires=("pkga>=1.0.0",))

    mock = MockFetch({("pkga", "1.0.0"): wheel_a, ("pkgb", "1.0.0"): wheel_b})
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    target = tmp_path / "site"
    target.mkdir()
    tags = [Tag("py3", "none", "any")]

    with patch("app.core.wheel_installer.resolve.get_pypi_json", mock.mock_get_pypi_json), \
         patch("app.core.wheel_installer.resolve.fetch_wheel", mock.mock_fetch_wheel):
        resolved = resolve_and_fetch(["pkga>=1.0.0"], target, tags, cache_dir)

    names = [r.name for r in resolved]
    assert set(names) == {"pkga", "pkgb"}
    assert len(resolved) == 2


def test_resolve_install_order_deps_before_dependents(tmp_path: Path):
    """Install order puts dependencies before dependents (topological)."""
    wheel_c = make_wheel(tmp_path, "pkgc", "1.0.0")
    wheel_b = make_wheel(tmp_path, "pkgb", "1.0.0", requires=("pkgc>=1.0.0",))
    wheel_a = make_wheel(tmp_path, "pkga", "1.0.0", requires=("pkgb>=1.0.0",))

    mock = MockFetch({("pkga", "1.0.0"): wheel_a, ("pkgb", "1.0.0"): wheel_b, ("pkgc", "1.0.0"): wheel_c})
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    target = tmp_path / "site"
    target.mkdir()
    tags = [Tag("py3", "none", "any")]

    with patch("app.core.wheel_installer.resolve.get_pypi_json", mock.mock_get_pypi_json), \
         patch("app.core.wheel_installer.resolve.fetch_wheel", mock.mock_fetch_wheel):
        resolved = resolve_and_fetch(["pkga>=1.0.0"], target, tags, cache_dir)

    names = [r.name for r in resolved]
    assert names == ["pkgc", "pkgb", "pkga"]


# =============================================================================
# Tests for install_specs_to_target (end-to-end with mocked fetch)
# =============================================================================

def test_install_specs_to_target_end_to_end(tmp_path: Path):
    """install_specs_to_target extracts wheels into target and cleans cache."""
    wheel_a = make_wheel(tmp_path, "pkga", "1.0.0", requires=("pkgb>=1.0.0",))
    wheel_b = make_wheel(tmp_path, "pkgb", "1.0.0")

    mock = MockFetch({("pkga", "1.0.0"): wheel_a, ("pkgb", "1.0.0"): wheel_b})
    target = tmp_path / "site"
    target.mkdir()
    tags = [Tag("py3", "none", "any")]

    logs: list[str] = []

    with patch("app.core.wheel_installer.resolve.get_pypi_json", mock.mock_get_pypi_json), \
         patch("app.core.wheel_installer.resolve.fetch_wheel", mock.mock_fetch_wheel), \
         patch("tempfile.mkdtemp", lambda prefix="aip-wheels-": str(tmp_path / "watched_cache")):
        # Use a watched cache dir so we can verify cleanup
        watched_cache = tmp_path / "watched_cache"
        watched_cache.mkdir(exist_ok=True)

        install_specs_to_target(["pkga>=1.0.0"], target, log=logs.append)

    # Verify target contents
    assert (target / "pkga" / "__init__.py").exists()
    assert (target / "pkgb" / "__init__.py").exists()

    # Verify cache was cleaned up
    assert not watched_cache.exists() or len(list(watched_cache.iterdir())) == 0

    # Verify logs
    assert any("解析" in log for log in logs)
    assert any("下载" in log for log in logs)
    assert any("解压" in log for log in logs)
    assert any("安装完成" in log for log in logs)


# =============================================================================
# Run tests
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-q"])