"""Runtime tool discovery: resolution order, exec-bit self-heal, status text.

Real-machine tests use what this checkout has (native ExifTool under
Tools/exiftool, ffmpeg/ffprobe on PATH). Ordering tests build throwaway files
in tmp_path and pin the module attributes find_tool looks up, so nothing here
depends on what is installed where the suite runs.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

import pytest

from app.core import runtime_tools as rt
from app.core.exiftool_runner import ExifToolRunner

_WIN = sys.platform.startswith("win")
# Under root os.access(X_OK) is always True, making self-heal checks vacuous.
_NON_ROOT = hasattr(os, "geteuid") and os.geteuid() != 0
# Probed off the filesystem, not via find_tool: the skip must not hide a bug.
_BUNDLED_EXIFTOOL = (Path(__file__).resolve().parents[2] / "Tools" / "exiftool"
                     / ("exiftool.exe" if _WIN else "exiftool"))

def _binary(path: Path) -> Path:
    """A file that passes _looks_runnable on both unix and Windows."""
    path.write_bytes(b"fake-binary")
    path.chmod(0o755)
    return path

def _script(path: Path, output: str = "9.9.9") -> Path:
    """An executable printing `output` whatever args it is given."""
    path.write_text(f'#!/bin/sh\necho "{output}"\n', encoding="utf-8")
    path.chmod(0o755)
    return path

def _fake_sources(monkeypatch, bundled, user, which) -> None:
    """Pin find_tool's three sources to explicit lists / one PATH hit."""
    monkeypatch.setattr(rt, "_bundled_candidates", lambda *a, **k: list(bundled))
    monkeypatch.setattr(rt, "_user_candidates", lambda *a, **k: list(user))
    monkeypatch.setattr(rt.shutil, "which", lambda cmd: which)

def test_looks_runnable_accepts_real_and_fresh_executables(tmp_path):
    """A system interpreter and a just-written executable both pass."""
    assert rt._looks_runnable(Path(sys.executable)) is True
    assert rt._looks_runnable(_binary(tmp_path / "fresh")) is True

def test_looks_runnable_rejects_missing_path_and_directory(tmp_path):
    """A path that does not exist, and a directory, are both not runnable."""
    assert rt._looks_runnable(tmp_path / "nope") is False
    (tmp_path / "adir").mkdir()
    assert rt._looks_runnable(tmp_path / "adir") is False

@pytest.mark.skipif(_WIN, reason="exec bits and chmod do not exist on Windows")
@pytest.mark.skipif(not _NON_ROOT, reason="root bypasses exec-bit permission checks")
def test_looks_runnable_self_heals_missing_exec_bit(tmp_path):
    """A tarball-extracted script without the exec bit is chmod-ed in place."""
    p = tmp_path / "tool.sh"
    p.write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    p.chmod(0o644)
    assert not p.stat().st_mode & 0o111
    assert os.access(p, os.X_OK) is False
    assert rt._looks_runnable(p) is True
    assert p.stat().st_mode & 0o111
    assert os.access(p, os.X_OK) is True

@pytest.mark.skipif(_WIN, reason="Windows is expected to run .exe files")
def test_looks_runnable_rejects_windows_exe_on_unix(tmp_path):
    """The Windows ExifTool sitting next to the unix one is never executed."""
    assert rt._looks_runnable(_binary(tmp_path / "x.exe")) is False  # exec bit set

def test_find_tool_prefers_bundled_over_user_and_path(tmp_path, monkeypatch):
    """A usable bundled candidate wins, skipping missing/non-file candidates."""
    (tmp_path / "adir").mkdir()
    bundled = _binary(tmp_path / "bundled")
    _fake_sources(monkeypatch, [tmp_path / "missing", tmp_path / "adir", bundled],
                  [_binary(tmp_path / "user")], str(sys.executable))
    st = rt.find_tool("exiftool", "tool", probe_version=False)
    assert (st.path, st.source, st.available) == (bundled, "bundled", True)

def test_find_tool_falls_back_to_user_install(tmp_path, monkeypatch):
    """With nothing bundled, the one-click install target is used."""
    user = _binary(tmp_path / "user")
    _fake_sources(monkeypatch, [], [user], str(sys.executable))
    st = rt.find_tool("exiftool", "tool", probe_version=False)
    assert (st.path, st.source, st.available) == (user, "user-install", True)

def test_find_tool_falls_back_to_system_path(monkeypatch):
    """With neither local source, shutil.which is the last resort."""
    _fake_sources(monkeypatch, [], [], str(sys.executable))
    st = rt.find_tool("ffmpeg", "tool", probe_version=False)
    assert (st.path, st.source, st.available) == (Path(sys.executable), "PATH", True)

def test_find_tool_reports_missing_when_every_source_is_empty(monkeypatch):
    """No candidate anywhere yields an explicitly unavailable status."""
    _fake_sources(monkeypatch, [], [], None)
    st = rt.find_tool("ffprobe", "tool")
    assert st.available is False and st.path is None
    assert st.source == "" and st.version == ""
    assert st.display() == "未安装"

def test_find_tool_threads_portable_mode_into_the_user_search(tmp_path, monkeypatch):
    """portable_mode must reach _user_candidates or the portable lookup breaks."""
    seen: list[bool] = []

    def spy(tool_dir, name, portable_mode=False):
        seen.append(portable_mode)
        return [_binary(tmp_path / "user")]

    _fake_sources(monkeypatch, [], [], None)
    monkeypatch.setattr(rt, "_user_candidates", spy)
    # probe_version=False: the fake binary is not a real program, so the
    # runnability probe would (correctly) reject it.
    assert rt.find_tool("exiftool", "tool", portable_mode=True,
                        probe_version=False).source == "user-install"
    assert rt.find_tool("exiftool", "tool", probe_version=False).source == "user-install"
    assert seen == [True, False]

@pytest.mark.skipif(_WIN, reason="fake tool is a unix shell script")
def test_find_tool_probes_the_version_of_the_binary_it_picked(tmp_path, monkeypatch):
    """probe_version=True runs the chosen binary and keeps its first line."""
    _fake_sources(monkeypatch, [_script(tmp_path / "tool", "13.59")], [], None)
    st = rt.find_tool("exiftool", "tool")
    assert st.available is True and st.version == "13.59"

@pytest.mark.skipif(_WIN, reason="fake tool is a unix shell script")
def test_find_tool_skips_candidates_that_cannot_report_a_version(tmp_path, monkeypatch):
    """A half-installed tool (present but broken) must not be reported ready.

    This is the case that used to surface as "✓ 已内置 · Can't locate" in the
    settings panel while every device_metadata step failed afterwards.
    """
    broken = tmp_path / "broken"
    broken.write_text("#!/bin/sh\necho \"Can't locate Image/ExifTool.pm\"\nexit 0\n",
                      encoding="utf-8")
    broken.chmod(0o755)
    good = _script(tmp_path / "good", "13.59")
    _fake_sources(monkeypatch, [broken], [], None)
    assert rt.find_tool("exiftool", "tool").available is False

    # ...and the search keeps going to the next source instead of giving up.
    _fake_sources(monkeypatch, [broken], [good], None)
    st = rt.find_tool("exiftool", "tool")
    assert st.available is True and st.path == good and st.source == "user-install"

def test_probe_version_false_skips_the_process_but_stays_available(tmp_path, monkeypatch):
    """probe_version=False must not spawn the tool, and must stay available."""
    exe = _script(tmp_path / "tool")
    probed: list[Path] = []
    monkeypatch.setattr(rt, "_version_of", lambda p, args=None: probed.append(p) or "13.59")
    _fake_sources(monkeypatch, [exe], [], None)
    assert rt.find_tool("exiftool", "tool", probe_version=True).version == "13.59"
    assert probed == [exe]
    probed.clear()
    st = rt.find_tool("exiftool", "tool", probe_version=False)
    assert st.available is True and st.path == exe
    assert st.version == "" and probed == []

@pytest.mark.skipif(not _BUNDLED_EXIFTOOL.exists(), reason="no bundled ExifTool in this checkout")
def test_exiftool_version_is_probed_only_when_asked():
    """Real ExifTool: probing yields a dotted version, not probing yields ""."""
    st = rt.exiftool_status()
    assert st.available is True
    assert re.fullmatch(r"\d+(\.\d+)+", st.version), f"bad version {st.version!r}"
    assert rt.exiftool_status(probe_version=False).version == ""

@pytest.mark.parametrize(
    "status_fn", [rt.exiftool_status, rt.ffmpeg_status, rt.ffprobe_status],
    ids=["exiftool", "ffmpeg", "ffprobe"],
)
def test_status_is_self_consistent_on_this_machine(status_fn):
    """available means runnable-and-labelled; unavailable means fully blank.

    A contract, not "the tool is installed", so it stays honest on a CI box
    with no tools, and still fails there when one *is* present but misreported.
    """
    st = status_fn()
    assert st.name in ("exiftool", "ffmpeg", "ffprobe")
    if st.available:
        assert st.path is not None and st.path.is_file()
        assert rt._looks_runnable(st.path) is True
        assert st.source in ("bundled", "user-install", "PATH")
        assert st.version  # probed by default
    else:
        assert st.path is None
        assert st.source == "" and st.version == ""
        assert st.display() == "未安装"

@pytest.mark.skipif(not _BUNDLED_EXIFTOOL.exists(), reason="no bundled ExifTool in this checkout")
def test_bundled_exiftool_is_actually_discovered():
    """With the binary in the checkout, exiftool_status must find it."""
    st = rt.exiftool_status()
    assert st.available is True and st.source in ("bundled", "PATH")
    assert st.path is not None and st.path.exists()

@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
                    reason="ffmpeg/ffprobe not on PATH")
def test_path_ffmpeg_and_ffprobe_are_actually_discovered():
    """With both on PATH, ffmpeg/ffprobe status must point at something real."""
    for st in (rt.ffmpeg_status(), rt.ffprobe_status()):
        assert st.available is True and st.source in ("bundled", "PATH")
        assert st.path is not None and rt._looks_runnable(st.path)
        assert st.version  # e.g. "ffmpeg version 7.1.5 ..." from the real binary

def test_runtime_summary_covers_the_three_tools_without_probing_versions():
    """The GUI list gets exactly three statuses, none of which spawn a tool."""
    summary = rt.runtime_summary()
    assert set(summary) == {"exiftool", "ffmpeg", "ffprobe"}
    for key, st in summary.items():
        assert isinstance(st, rt.ToolStatus)
        assert st.name == key
        assert st.version == ""  # probe_version=False: one status row per tool

def test_exiftool_runner_shares_the_runtime_tools_lookup():
    """The runner must not grow a second, diverging lookup of its own."""
    runner = ExifToolRunner()
    st = rt.exiftool_status()
    assert runner.binary == st.path
    assert runner.available() == st.available
    assert ExifToolRunner._looks_runnable(Path("/definitely/not/here")) is False

def test_display_names_the_source_for_available_tools():
    """Each source label is distinct so users can tell where a tool came from."""
    def shown(source: str) -> str:
        return rt.ToolStatus("tool", True, Path("/opt/tool"), "1.0", source).display()

    assert "已内置" in shown("bundled")
    assert "已安装" in shown("user-install")
    assert "来自系统 PATH" in shown("PATH")
    assert "已就绪" in shown("")
    # probe_version=False must not leave a dangling separator behind.
    assert rt.ToolStatus("tool", True, Path("/opt/tool"), "", "bundled").display() == "已内置"
    assert rt.ToolStatus("tool", False).display() == "未安装"

def test_display_truncates_a_full_copyright_version_line():
    """ffmpeg's first line is a whole copyright notice; the row stays short."""
    long_version = "ffmpeg version 7.1.5-0+deb13u1 Copyright (c) 2000-2026 FFmpeg developers, gcc 14"
    text = rt.ToolStatus("ffmpeg", True, Path("/usr/bin/ffmpeg"), long_version, "PATH").display()
    assert text.startswith("来自系统 PATH ·")
    assert "Copyright" not in text and "gcc" not in text
    assert len(text) < 40, f"status row too long: {text!r}"