"""ExifTool / perl diagnosis and one-click install, without touching the machine.

Nothing here reaches the network, spawns a real tool, or writes outside
``tmp_path``: every test pins the status probe (``exiftool_status``), the
candidate paths (``_script_candidates``), the downloaders (``_download_with_curl``
and ``urllib.request.urlopen``) and the user-install directory, so the assertions
are about this module's decisions rather than about what happens to be installed
on the machine running the suite.

The behaviour under test is the one that used to fail silently: a unix ExifTool
that exists but cannot start (no perl) must be named as such, refused before any
output is written, and repairable without administrator rights.
"""
from __future__ import annotations

import hashlib
import platform
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core import runtime_install as ri
from app.core import runtime_tools
from app.core.runtime_install import (
    PERL_RELEASE_BASE,
    RuntimeInstallError,
    RuntimeProblem,
    _download,
    _download_with_curl,
    _platform_asset,
    diagnose,
    install_runtime,
    manual_install_command,
)
from app.core.runtime_tools import ToolStatus

PERL_ASSET = "perl-linux-amd64.tar.xz"
URL = "https://example.invalid/archive"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _forbid(label: str):
    """A stand-in that fails the test if the code under test calls it."""
    def _boom(*_a, **_k):
        raise AssertionError(f"{label} must not be called here")
    return _boom


def _sequence(*values):
    """A callable returning ``values[i]`` per call and recording the call count.

    Used to answer "what did the code decide the first time / the second time",
    which is how the re-probe after an install is verified.
    """
    calls: list[int] = []

    def fn(*_a, **_k):
        index = len(calls) + 1
        calls.append(index)
        value = values[min(index, len(values)) - 1]
        return value(index) if callable(value) else value

    fn.calls = calls
    return fn


def _pin_status(monkeypatch, status: ToolStatus, calls: list | None = None) -> None:
    """Replace the whole status probe ``diagnose`` relies on.

    ``diagnose`` imports ``exiftool_status`` inside the function body, so
    patching the module attribute is enough -- and it records the keywords so a
    test can assert diagnose probes the way the pipeline probes.
    """
    def status_fn(*, portable_mode=False, probe_version=True):
        if calls is not None:
            calls.append({"portable_mode": portable_mode, "probe_version": probe_version})
        return status

    monkeypatch.setattr(runtime_tools, "exiftool_status", status_fn)


def _pin_candidates(monkeypatch, paths: list[Path]) -> None:
    """Pin the "is the script somewhere on disk" half of the diagnosis.

    The real ``_script_candidates`` calls ``user_install_dir``, which mkdirs the
    user's data directory; the tests must not depend on (or create) that.
    """
    monkeypatch.setattr(ri, "_script_candidates", lambda tool, portable_mode: list(paths))


def _pin_unix(monkeypatch, *, asset: str | None = PERL_ASSET, system: str = "Linux") -> None:
    """Pretend to be a unix box with no package manager and no downloader."""
    monkeypatch.setattr(platform, "system", lambda: system)
    monkeypatch.setattr(ri, "_platform_asset", lambda: asset)
    monkeypatch.setattr(shutil, "which", lambda cmd: None)


def _fake_exiftool(tmp_path: Path, name: str = "exiftool") -> Path:
    """A file that stands in for the bundled exiftool wrapper."""
    p = tmp_path / name
    p.write_text("#!/bin/sh\nexec perl exiftool.pl\n", encoding="utf-8")
    p.chmod(0o755)
    return p


def _unavailable(name: str = "exiftool") -> ToolStatus:
    return ToolStatus(name, False, None, "", "")


def _available(name: str = "exiftool") -> ToolStatus:
    return ToolStatus(name, True, Path("/opt/tools") / name, "13.59", "bundled")


def _problem(reason: str = "interpreter_missing", *, manual: str = "sudo apt-get install -y perl",
             can_auto_install: bool = True, asset: str | None = PERL_ASSET,
             detail: str = "包内的 ExifTool 是 perl 脚本，而本机没有可用的 perl 解释器") -> RuntimeProblem:
    return RuntimeProblem(
        tool="exiftool", reason=reason, detail=detail, manual=manual,
        can_auto_install=can_auto_install, extra={"asset": asset or ""},
    )


class _FakeResponse:
    """Minimal stand-in for the object ``urlopen`` returns."""

    def __init__(self, body: bytes, content_length: str | None = None):
        self._body = body
        self._pos = 0
        self.headers = {"Content-Length": content_length} if content_length is not None else {}

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            n = len(self._body) - self._pos
        chunk = self._body[self._pos:self._pos + n]
        self._pos += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


# ---------------------------------------------------------------------------
# 1. diagnosis
# ---------------------------------------------------------------------------

def test_diagnose_returns_none_when_exiftool_actually_works(monkeypatch):
    """A working tool has no problem to report -- None, not a fake RuntimeProblem.

    Every caller (preflight, the settings button) treats None as "go ahead", so
    returning a problem here would block every job on a healthy machine.
    """
    _pin_status(monkeypatch, _available())
    assert diagnose("exiftool") is None


def test_diagnose_probes_the_version_and_honours_portable_mode(monkeypatch):
    """diagnose must probe the way the pipeline probes.

    A file that exists and carries the exec bit but cannot start is *not*
    usable; a probe_version=False diagnosis would call that available and the
    two steps that need ExifTool would still fail later, on the user's files.
    """
    calls: list[dict] = []
    _pin_status(monkeypatch, _available(), calls)
    diagnose("exiftool", portable_mode=True)
    assert calls == [{"portable_mode": True, "probe_version": True}]


def test_diagnose_blames_the_interpreter_when_the_script_is_there_but_will_not_start(tmp_path, monkeypatch):
    """Present-but-broken is not "not installed": the fix is a perl, not ExifTool.

    This is the unix case the module exists for. Misreporting it as not_found
    would send the user to download an ExifTool they already have.
    """
    _pin_unix(monkeypatch)
    _pin_status(monkeypatch, _unavailable())
    _pin_candidates(monkeypatch, [_fake_exiftool(tmp_path, "exiftool-13.59")])

    problem = diagnose("exiftool")
    assert problem is not None
    assert problem.reason == "interpreter_missing"
    assert problem.tool == "exiftool"
    # the message must name the file it found, so the user can connect it to the
    # copy they believed was working
    assert "exiftool-13.59" in problem.detail
    assert "perl" in problem.detail
    assert problem.can_auto_install is True
    assert problem.extra["asset"] == PERL_ASSET


def test_diagnose_names_the_copy_that_is_actually_present(tmp_path, monkeypatch):
    """Bundled first, user-install second: only the existing one may be named.

    The bundled path is searched before the installed one, so a naive
    "candidates[0]" would point the user at a file that is not there.
    """
    _pin_unix(monkeypatch)
    _pin_status(monkeypatch, _unavailable())
    installed = _fake_exiftool(tmp_path, "user-install-exiftool")
    _pin_candidates(monkeypatch, [tmp_path / "Tools" / "exiftool" / "exiftool", installed])

    problem = diagnose("exiftool")
    assert problem is not None
    assert problem.reason == "interpreter_missing"
    assert "user-install-exiftool" in problem.detail
    assert "Tools" not in problem.detail


def test_diagnose_manual_command_names_perl_without_a_package_manager(tmp_path, monkeypatch):
    """The copy-paste fallback must still say perl is what is missing."""
    _pin_unix(monkeypatch)          # shutil.which -> None: no apt-get/dnf/pacman
    _pin_status(monkeypatch, _unavailable())
    _pin_candidates(monkeypatch, [_fake_exiftool(tmp_path)])

    problem = diagnose("exiftool")
    assert problem is not None
    assert "perl" in problem.manual
    # something the user can act on -- never an empty string that leaves them stuck
    assert problem.manual.strip()


def test_diagnose_reports_not_found_when_the_script_is_nowhere(monkeypatch):
    """No candidate on disk means "install ExifTool", and perl is irrelevant."""
    _pin_unix(monkeypatch)
    _pin_status(monkeypatch, _unavailable())
    _pin_candidates(monkeypatch, [])

    problem = diagnose("exiftool")
    assert problem is not None
    assert problem.reason == "not_found"
    assert problem.can_auto_install is False
    assert problem.manual.strip()
    # must NOT claim the interpreter is the problem: nothing is installed at all
    assert "perl" not in problem.detail


def test_diagnose_offers_no_auto_install_when_the_platform_has_no_perl_asset(tmp_path, monkeypatch):
    """Without a portable perl build for this platform, promising a fix would lie."""
    _pin_unix(monkeypatch, asset=None)
    _pin_status(monkeypatch, _unavailable())
    _pin_candidates(monkeypatch, [_fake_exiftool(tmp_path)])

    problem = diagnose("exiftool")
    assert problem is not None
    assert problem.reason == "interpreter_missing"
    assert problem.can_auto_install is False
    assert problem.extra["asset"] == ""


def test_diagnose_never_blames_perl_for_ffmpeg(tmp_path, monkeypatch):
    """The interpreter story is ExifTool-specific; ffmpeg is a plain binary.

    Without the tool == "exiftool" guard, a missing ffmpeg that happens to sit
    next to some stale script would send the user off installing perl.
    """
    _pin_unix(monkeypatch)
    monkeypatch.setattr(runtime_tools, "ffmpeg_status", lambda **kw: _unavailable("ffmpeg"))
    _pin_candidates(monkeypatch, [_fake_exiftool(tmp_path)])

    problem = diagnose("ffmpeg")
    assert problem is not None
    # A candidate that exists but will not start is "broken", not "not_found" --
    # telling a user their files are missing when they can see them is worse
    # than the old wording. What matters here is only that the perl story stays
    # out of an ffmpeg diagnosis.
    assert problem.reason == "broken"
    assert problem.tool == "ffmpeg"
    assert "perl" not in problem.detail and "perl" not in problem.manual
    assert problem.can_auto_install is False


def test_diagnose_on_windows_points_at_exiftool_exe(monkeypatch):
    """The Windows distribution is a built exe; the manual text must say so."""
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    _pin_status(monkeypatch, _unavailable())
    _pin_candidates(monkeypatch, [])

    problem = diagnose("exiftool")
    assert problem is not None
    assert problem.reason == "not_found"
    assert "exiftool" in problem.manual.lower()
    assert "perl" not in problem.detail.lower()


# ---------------------------------------------------------------------------
# 2. the preflight wording
# ---------------------------------------------------------------------------

def test_explain_names_the_steps_the_tool_is_needed_for(tmp_path, monkeypatch):
    """The refusal must say which enabled step caused it, in the user's words.

    It is the only place the user learns *why* a run they configured as valid
    was refused before a single file was written.
    """
    _pin_unix(monkeypatch)
    _pin_status(monkeypatch, _unavailable())
    _pin_candidates(monkeypatch, [_fake_exiftool(tmp_path)])

    text = diagnose("exiftool").explain(["「写入设备信息」", "「Live Photo」"])
    assert "「写入设备信息」" in text
    assert "「Live Photo」" in text
    assert "、" in text                       # both steps listed, not just the first
    assert "ExifTool" in text
    assert "perl" in text                     # the actual cause, not just the tool


def test_explain_repeats_the_manual_command(tmp_path, monkeypatch):
    """The copy-paste fallback has to survive into the message the user sees."""
    _pin_unix(monkeypatch)
    _pin_status(monkeypatch, _unavailable())
    _pin_candidates(monkeypatch, [_fake_exiftool(tmp_path)])

    problem = diagnose("exiftool")
    assert problem.manual in problem.explain(["「写入设备信息」"])


def test_explain_points_at_the_settings_button_only_when_auto_install_exists():
    """A one-click fix must be advertised only when there really is one."""
    text = _problem(can_auto_install=True).explain(["「写入设备信息」"])
    assert "设置" in text and "安装" in text

    # Without a portable perl for the platform there is nothing to click, and
    # advertising it sends the user to a button that can only fail.
    manual_only = _problem(can_auto_install=False).explain(["「写入设备信息」"])
    assert "设置" not in manual_only
    assert manual_only.count("sudo apt-get install -y perl") == 1


def test_explain_without_step_names_still_renders():
    """An empty needs list must not produce a message with a dangling blank."""
    text = _problem().explain([])
    assert "本次任务" in text
    assert "ExifTool" in text
    assert text.strip()


# ---------------------------------------------------------------------------
# 3. platform asset mapping (pure function)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("system,machine,expected", [
    ("Linux", "x86_64", "perl-linux-amd64.tar.xz"),
    ("Linux", "amd64", "perl-linux-amd64.tar.xz"),
    ("Linux", "aarch64", "perl-linux-arm64.tar.xz"),
    ("Linux", "arm64", "perl-linux-arm64.tar.xz"),
    ("Darwin", "x86_64", "perl-darwin-amd64.tar.xz"),
    ("Darwin", "arm64", "perl-darwin-arm64.tar.xz"),
    ("windows", "AMD64", None),        # no portable perl is shipped for Windows
    ("FreeBSD", "x86_64", None),       # not a platform we build for
    ("Linux", "riscv64", None),        # architecture we do not publish
    ("Linux", "", None),               # unknown machine string
])
def test_platform_asset_maps_supported_platforms_only(monkeypatch, system, machine, expected):
    """The asset name decides the download URL; a wrong or invented one 404s.

    Unsupported hosts must yield None, which the diagnosis turns into
    can_auto_install=False instead of an install button that cannot work.
    """
    monkeypatch.setattr(platform, "system", lambda: system)
    monkeypatch.setattr(platform, "machine", lambda: machine)
    assert _platform_asset() == expected


# ---------------------------------------------------------------------------
# 4. the download layer
# ---------------------------------------------------------------------------

def _fake_run(queue: list[tuple[int, int]], calls: list[list[str]], boom: bool = False):
    """subprocess.run stand-in; each queued (returncode, bytes written) is used once."""
    def run(argv, **_kw):
        calls.append(list(argv))
        if boom:
            raise OSError("cannot execute")
        returncode, size = queue.pop(0)
        flag = "-o" if "-o" in argv else "-O"
        dest = Path(argv[argv.index(flag) + 1])
        if size:
            dest.write_bytes(b"x" * size)
        return SimpleNamespace(returncode=returncode, stdout="", stderr="boom")
    return run


def test_download_with_curl_reports_failure_when_no_downloader_exists(monkeypatch, tmp_path):
    """Neither curl nor wget on PATH is a normal case, not an exception.

    It is the caller's cue to fall back to urllib; raising here would break the
    install on a minimal container.
    """
    monkeypatch.setattr(shutil, "which", lambda cmd: None)
    monkeypatch.setattr(ri.subprocess, "run", _forbid("subprocess.run"))
    assert _download_with_curl(URL, tmp_path / "f") is False
    assert not (tmp_path / "f").exists()


def test_download_with_curl_prefers_curl_over_wget(monkeypatch, tmp_path):
    """curl is the one that can resume and retry; wget is only the fallback."""
    monkeypatch.setattr(shutil, "which", lambda cmd: f"/usr/bin/{cmd}")
    calls: list[list[str]] = []
    monkeypatch.setattr(ri.subprocess, "run", _fake_run([(0, 2048)], calls))
    assert _download_with_curl(URL, tmp_path / "f") is True
    assert len(calls) == 1 and calls[0][0] == "curl"
    assert (tmp_path / "f").stat().st_size == 2048


def test_download_with_curl_falls_back_to_wget_when_curl_fails(monkeypatch, tmp_path):
    """One flaky transfer must not fail the whole install."""
    monkeypatch.setattr(shutil, "which", lambda cmd: f"/usr/bin/{cmd}")
    calls: list[list[str]] = []
    monkeypatch.setattr(ri.subprocess, "run", _fake_run([(22, 0), (0, 512)], calls))
    assert _download_with_curl(URL, tmp_path / "f") is True
    assert [c[0] for c in calls] == ["curl", "wget"]


def test_download_with_curl_refuses_an_empty_result(monkeypatch, tmp_path):
    """A zero exit with nothing on disk is a failure, not a success.

    Accepting it would hand tarfile a truncated archive and fail much later with
    an unrelated "structure is not as expected" message.
    """
    monkeypatch.setattr(shutil, "which", lambda cmd: "/usr/bin/curl" if cmd == "curl" else None)
    calls: list[list[str]] = []
    monkeypatch.setattr(ri.subprocess, "run", _fake_run([(0, 0)], calls))
    assert _download_with_curl(URL, tmp_path / "f") is False
    assert [c[0] for c in calls] == ["curl"]      # ran, wrote nothing, was not accepted


def test_download_with_curl_treats_an_unrunnable_downloader_as_failure(monkeypatch, tmp_path):
    """A present-but-broken curl (wrong arch, no exec bit) must not raise."""
    monkeypatch.setattr(shutil, "which", lambda cmd: f"/usr/bin/{cmd}")
    calls: list[list[str]] = []
    monkeypatch.setattr(ri.subprocess, "run", _fake_run([], calls, boom=True))
    assert _download_with_curl(URL, tmp_path / "f") is False
    assert [c[0] for c in calls] == ["curl", "wget"]


def test_download_falls_back_to_urllib_when_no_downloader_exists(tmp_path, monkeypatch):
    """The urllib path must actually work: create the parent, write every byte."""
    monkeypatch.setattr(shutil, "which", lambda cmd: None)
    monkeypatch.setattr(ri.subprocess, "run", _forbid("subprocess.run"))
    seen: list[urllib.request.Request] = []

    def fake_urlopen(req, timeout=None):
        seen.append(req)
        return _FakeResponse(b"payload-bytes", content_length="13")

    monkeypatch.setattr(ri.urllib.request, "urlopen", fake_urlopen)
    dest = tmp_path / "nested" / "file.bin"
    _download(URL, dest)

    assert dest.read_bytes() == b"payload-bytes"
    assert len(seen) == 1
    assert seen[0].full_url == URL
    # codeload rejects the stock python-urllib agent, so this header is load-bearing
    assert any("AI-Image-Process" in v for v in seen[0].headers.values())


def test_download_never_touches_urllib_once_curl_succeeded(tmp_path, monkeypatch):
    """A completed curl transfer must not be re-fetched by urllib.

    Re-downloading doubles the traffic on an already slow link and can replace a
    good file with a partial one.
    """
    monkeypatch.setattr(ri, "_download_with_curl", lambda url, dest: True)
    monkeypatch.setattr(ri.urllib.request, "urlopen", _forbid("urllib.request.urlopen"))
    dest = tmp_path / "file.bin"
    _download(URL, dest)                          # must simply return
    assert not dest.exists()                      # the urllib path never ran


def test_download_drops_a_partial_curl_file_before_retrying(tmp_path, monkeypatch):
    """Truncated bytes from curl must not end up under the new download.

    Resuming on top of them yields a corrupt archive that only fails at
    extraction time, with no hint that the transfer was the problem.
    """
    def fake_curl(url, dest):
        dest.write_bytes(b"truncated")
        return False

    monkeypatch.setattr(ri, "_download_with_curl", fake_curl)
    dest = tmp_path / "file.bin"
    observed: list[bool] = []

    def fake_urlopen(req, timeout=None):
        observed.append(dest.exists())
        raise OSError("no route to host")

    monkeypatch.setattr(ri.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(RuntimeInstallError):
        _download(URL, dest)
    assert observed == [False, False, False]      # stale file gone before each attempt
    assert not dest.exists()


def test_download_retries_then_reports_the_failure(tmp_path, monkeypatch):
    """A persistent network failure must raise an actionable error, not hang.

    The message has to name the URL and say it was retried, otherwise the GUI
    shows the user an empty reason.
    """
    monkeypatch.setattr(ri, "_download_with_curl", lambda url, dest: False)
    attempts: list[str] = []

    def fake_urlopen(req, timeout=None):
        attempts.append(req.full_url)
        raise OSError("no route to host")

    monkeypatch.setattr(ri.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(RuntimeInstallError) as excinfo:
        _download(URL, tmp_path / "f")
    message = str(excinfo.value)
    assert "下载失败" in message
    assert URL in message
    assert len(attempts) == 3                    # retried before giving up


def test_download_rejects_a_truncated_body_with_a_declared_length(tmp_path, monkeypatch):
    """Content-Length is the only way to notice a body that ended early.

    urllib raises nothing when a connection closes mid-stream, so without this
    check a half-written tarball is unpacked and fails with a misleading
    "structure is not as expected".
    """
    monkeypatch.setattr(ri, "_download_with_curl", lambda url, dest: False)
    monkeypatch.setattr(
        ri.urllib.request, "urlopen",
        lambda req, timeout=None: _FakeResponse(b"half", content_length="1024"),
    )
    with pytest.raises(RuntimeInstallError) as excinfo:
        _download(URL, tmp_path / "f", attempts=1)
    assert "下载不完整" in str(excinfo.value)


# ---------------------------------------------------------------------------
# 5. install_runtime
# ---------------------------------------------------------------------------

def test_install_runtime_is_a_noop_when_the_tool_already_works(monkeypatch, tmp_path):
    """A second click (or a racing install) must download nothing.

    Otherwise two runs can unpack into the same user directory at once, which is
    one of the ways a half-written ExifTool comes about in the first place.
    """
    monkeypatch.setattr(ri, "diagnose", lambda *a, **k: None)
    monkeypatch.setattr(ri, "_download", _forbid("_download"))
    monkeypatch.setattr(ri, "_install_perl", _forbid("_install_perl"))
    monkeypatch.setattr(ri, "_install_exiftool_unix", _forbid("_install_exiftool_unix"))
    monkeypatch.setattr(ri, "_install_exiftool_windows", _forbid("_install_exiftool_windows"))
    monkeypatch.setattr(ri, "user_install_dir", lambda tool, portable_mode=False: tmp_path / tool)
    assert install_runtime("exiftool", log=_forbid("log")) is None
    assert list(tmp_path.iterdir()) == []


def test_install_runtime_refuses_when_the_platform_has_no_perl_asset(monkeypatch, tmp_path):
    """No portable perl for this platform: say what to run by hand, install nothing."""
    monkeypatch.setattr(ri, "diagnose", lambda *a, **k: _problem(asset=""))
    # install_runtime consults _platform_asset directly as well as the diagnosis,
    # so both have to say "this platform has none".
    monkeypatch.setattr(ri, "_platform_asset", lambda: None)
    monkeypatch.setattr(ri, "_download", _forbid("_download"))
    monkeypatch.setattr(ri, "_install_perl", _forbid("_install_perl"))
    monkeypatch.setattr(ri, "_install_exiftool_unix", _forbid("_install_exiftool_unix"))
    monkeypatch.setattr(ri, "user_install_dir", lambda tool, portable_mode=False: tmp_path / tool)

    with pytest.raises(RuntimeInstallError) as excinfo:
        install_runtime("exiftool")
    assert "sudo apt-get install -y perl" in str(excinfo.value)   # actionable
    assert list(tmp_path.iterdir()) == []                         # and nothing was written


def test_install_runtime_installs_perl_before_exiftool(tmp_path, monkeypatch):
    """Order matters: the wrapper execs ../perl/bin/perl.

    Installing ExifTool first would produce a tool that exists, fails to start,
    and looks like the very problem we are trying to fix.
    """
    targets: list[Path] = []
    monkeypatch.setattr(ri, "_install_perl", lambda target, log: targets.append(target))
    monkeypatch.setattr(ri, "_install_exiftool_unix", lambda target, log: targets.append(target))
    monkeypatch.setattr(ri, "user_install_dir", lambda tool, portable_mode=False: tmp_path / tool)
    monkeypatch.setattr(
        ri, "diagnose",
        _sequence(lambda n: _problem() if n == 1 else _problem(detail="perl 未生效")),
    )

    lines: list[str] = []
    with pytest.raises(RuntimeInstallError):
        install_runtime("exiftool", log=lines.append)
    assert [t.name for t in targets] == ["perl", "exiftool"]
    # and they must be siblings: the wrapper resolves ../perl/bin/perl
    assert targets[0].parent == targets[1].parent == tmp_path
    assert any(PERL_ASSET in line for line in lines)   # progress names what it fetched
    assert "安装完成" not in lines                      # must not claim success


def test_install_runtime_reports_when_exiftool_is_still_unusable(tmp_path, monkeypatch):
    """A finished download that did not fix the tool must not read as success.

    The message carries the post-install diagnosis, which is the only way the
    user learns that the perl they just got is still not being picked up.
    """
    monkeypatch.setattr(ri, "_install_perl", lambda target, log: None)
    monkeypatch.setattr(ri, "_install_exiftool_unix", lambda target, log: None)
    monkeypatch.setattr(ri, "user_install_dir", lambda tool, portable_mode=False: tmp_path / tool)
    monkeypatch.setattr(
        ri, "diagnose",
        _sequence(lambda n: _problem() if n == 1 else _problem(detail="exiftool 无法启动")),
    )

    with pytest.raises(RuntimeInstallError) as excinfo:
        install_runtime("exiftool")
    message = str(excinfo.value)
    assert "仍不可用" in message
    assert "exiftool 无法启动" in message          # the post-install detail


def test_install_runtime_skips_the_recheck_when_verify_is_off(tmp_path, monkeypatch):
    """The re-probe is the "is it fixed" answer; asking not to means not asking.

    Without this the caller could never install a runtime whose availability
    only shows up after a restart. The flag is named `verify`, not
    `timeout_check`: there is no timeout anywhere in the install path.
    """
    monkeypatch.setattr(ri, "_install_perl", lambda target, log: None)
    monkeypatch.setattr(ri, "_install_exiftool_unix", lambda target, log: None)
    monkeypatch.setattr(ri, "user_install_dir", lambda tool, portable_mode=False: tmp_path / tool)
    diagnose_calls = _sequence(_problem())
    monkeypatch.setattr(ri, "diagnose", diagnose_calls)

    install_runtime("exiftool", verify=False)
    assert diagnose_calls.calls == [1]               # exactly one probe


def test_install_runtime_rejects_tools_it_cannot_install(monkeypatch, tmp_path):
    """ffmpeg has no in-app installer; the message must not pretend otherwise."""
    monkeypatch.setattr(ri, "diagnose", lambda *a, **k: RuntimeProblem(
        tool="ffmpeg", reason="not_found", detail="没有找到 ffmpeg", manual="请安装后重试"))
    monkeypatch.setattr(ri, "user_install_dir", lambda tool, portable_mode=False: tmp_path / tool)
    with pytest.raises(RuntimeInstallError) as excinfo:
        install_runtime("ffmpeg")
    assert "ffmpeg" in str(excinfo.value)


# ---------------------------------------------------------------------------
# 6. manual_install_command
# ---------------------------------------------------------------------------

def test_manual_install_command_follows_the_diagnosis(monkeypatch):
    """The GUI shows this after a failed install, so it must follow the diagnosis.

    While the tool works there is nothing to install, and a stale command would
    make a healthy machine look broken.
    """
    monkeypatch.setattr(ri, "diagnose", lambda *a, **k: None)
    assert manual_install_command("exiftool") == ""

    monkeypatch.setattr(ri, "diagnose", lambda *a, **k: _problem(manual="brew install perl"))
    assert manual_install_command("exiftool") == "brew install perl"


# ---------------------------------------------------------------------------
# 7. the unpack steps, from archives built in tmp_path (download stubbed)
# ---------------------------------------------------------------------------

def _perl_tarball(tmp_path: Path, *, root: str = "perl-9.5.0", with_perl: bool = True) -> Path:
    """Build a small .tar.xz shaped like a relocatable-perl release."""
    src = tmp_path / f"src-{root}"
    (src / "bin").mkdir(parents=True)
    (src / "README").write_text("fake perl\n", encoding="utf-8")
    if with_perl:
        (src / "bin" / "perl").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        (src / "bin" / "cpanm").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    archive = tmp_path / "perl.tar.xz"
    with tarfile.open(archive, "w:xz") as tf:
        tf.add(src, arcname=root)
    return archive


def _exiftool_tarball(tmp_path: Path, version: str) -> Path:
    """Build a small .tar.gz shaped like the pinned ExifTool source release."""
    src = tmp_path / "exiftool-src"
    (src / "lib" / "Image").mkdir(parents=True)
    (src / "exiftool").write_text(f'#!/usr/bin/perl\nprint "{version}\\n";\n', encoding="utf-8")
    (src / "lib" / "Image" / "ExifTool.pm").write_text("# stub\n", encoding="utf-8")
    archive = tmp_path / f"exiftool-{version}.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        tf.add(src, arcname=f"exiftool-{version}")
    return archive


def _stub_download(monkeypatch, archive: Path, urls: list[str] | None = None) -> None:
    """Replace the network with a copy of a locally built archive."""
    def fake_download(url, dest, **_k):
        if urls is not None:
            urls.append(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(archive, dest)

    monkeypatch.setattr(tempfile, "tempdir", str(archive.parent))
    monkeypatch.setattr(ri, "_download", fake_download)


def _pin_archive_checksum(monkeypatch, archive: Path) -> None:
    """Let the locally built archive through the pinned sha256 check.

    The constant stays the real release digest for the tests that assert it is
    enforced; here we approve of *our* archive so the unpack steps can run.
    """
    monkeypatch.setattr(ri, "EXIFTOOL_SHA256",
                        hashlib.sha256(archive.read_bytes()).hexdigest())


def test_install_perl_unpacks_the_tree_and_marks_binaries_executable(tmp_path, monkeypatch):
    """The end state must be a runnable <user>/tools/perl/bin/perl.

    A tree without the exec bit produces exactly the "present but will not
    start" state this module is meant to repair.
    """
    archive = _perl_tarball(tmp_path)
    urls: list[str] = []
    _stub_download(monkeypatch, archive, urls)
    monkeypatch.setattr(ri, "_platform_asset", lambda: PERL_ASSET)
    # a stale, broken perl from an earlier attempt must be replaced, not merged
    target = tmp_path / "target"
    (target / "bin").mkdir(parents=True)
    (target / "bin" / "perl").write_text("stale", encoding="utf-8")

    lines: list[str] = []
    ri._install_perl(target, lines.append)

    assert urls == [f"{PERL_RELEASE_BASE}/{PERL_ASSET}"]
    assert (target / "bin" / "perl").is_file()
    assert (target / "bin" / "cpanm").is_file()
    for name in ("perl", "cpanm"):
        assert (target / "bin" / name).stat().st_mode & 0o111, f"{name} is not executable"
    assert "stale" not in (target / "bin" / "perl").read_text(encoding="utf-8")
    assert any(PERL_ASSET in line for line in lines)


def test_install_perl_rejects_an_archive_without_bin_perl(tmp_path, monkeypatch):
    """A release with an unexpected layout must fail loudly, not install nothing.

    Otherwise the next step writes an ExifTool wrapper pointing at a missing
    interpreter -- the exact state we are trying to leave.
    """
    archive = _perl_tarball(tmp_path, with_perl=False)
    _stub_download(monkeypatch, archive)
    monkeypatch.setattr(ri, "_platform_asset", lambda: PERL_ASSET)
    with pytest.raises(RuntimeInstallError) as excinfo:
        ri._install_perl(tmp_path / "target", lambda _l: None)
    assert "bin/perl" in str(excinfo.value)


def test_install_perl_refuses_when_no_asset_matches_the_platform(monkeypatch, tmp_path):
    """No asset for this platform, no download attempt."""
    monkeypatch.setattr(ri, "_download", _forbid("_download"))
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(platform, "machine", lambda: "AMD64")
    with pytest.raises(RuntimeInstallError) as excinfo:
        ri._install_perl(tmp_path / "target", lambda _l: None)
    assert "Windows/AMD64" in str(excinfo.value)


def test_install_exiftool_unix_rejects_an_archive_that_fails_the_checksum(tmp_path, monkeypatch):
    """The pinned sha256 is the only integrity check on a downloaded tarball.

    Accepting a mismatch would unpack whatever the CDN served -- including a
    truncated download -- into the tool directory.
    """
    urls: list[str] = []

    def fake_download(url, dest, **_k):
        urls.append(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"not the pinned release")

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(ri, "_download", fake_download)
    target = tmp_path / "target"
    with pytest.raises(RuntimeInstallError) as excinfo:
        ri._install_exiftool_unix(target, lambda _l: None)

    assert "sha256" in str(excinfo.value)
    assert urls == [ri.EXIFTOOL_TARBALL]      # the pinned URL, not a moving "latest"
    assert ri.EXIFTOOL_VERSION in urls[0]
    assert not target.exists()


def test_installed_exiftool_is_a_runnable_wrapper_with_its_library(tmp_path, monkeypatch):
    """The last mile: a built tarball must end up as something the app can run.

    The wrapper and its .pl need the exec bit and the lib/ tree has to come
    along; a missing one reproduces the "present but broken" state in the user's
    own data directory, where nobody can repair it by re-downloading ExifTool.
    """
    archive = _exiftool_tarball(tmp_path, ri.EXIFTOOL_VERSION)
    _stub_download(monkeypatch, archive)
    _pin_archive_checksum(monkeypatch, archive)
    target = tmp_path / "installed"
    ri._install_exiftool_unix(target, lambda _l: None)

    wrapper = target / "exiftool"
    assert wrapper.is_file() and wrapper.stat().st_mode & 0o111
    assert (target / "exiftool.pl").stat().st_mode & 0o111
    assert (target / "lib" / "Image" / "ExifTool.pm").is_file()
    # bundled perl first, host perl second: the same order scripts/fetch_exiftool.sh uses
    body = wrapper.read_text(encoding="utf-8")
    assert "../perl/bin/perl" in body and body.index("../perl/bin/perl") < body.index('exec perl ')


@pytest.mark.skipif(not shutil.which("perl"), reason="no perl on this machine to run the wrapper with")
def test_find_tool_accepts_what_the_installer_produced(tmp_path, monkeypatch):
    """The installed copy must satisfy the app's own discovery.

    This is the contract that matters: after installing, exiftool_status() has
    to report the user-install copy as available, without a restart and without
    the user editing PATH.
    """
    archive = _exiftool_tarball(tmp_path, ri.EXIFTOOL_VERSION)
    _stub_download(monkeypatch, archive)
    _pin_archive_checksum(monkeypatch, archive)
    target = tmp_path / "installed"
    ri._install_exiftool_unix(target, lambda _l: None)

    monkeypatch.setattr(runtime_tools, "_bundled_candidates", lambda *a, **k: [])
    monkeypatch.setattr(runtime_tools, "_user_candidates",
                        lambda tool_dir, name, portable_mode=False: [target / "exiftool"])
    monkeypatch.setattr(runtime_tools.shutil, "which", lambda cmd: None)

    status = runtime_tools.exiftool_status()
    assert status.available is True
    assert status.source == "user-install"
    assert status.path == target / "exiftool"
    assert status.version == ri.EXIFTOOL_VERSION   # probed, not just assumed