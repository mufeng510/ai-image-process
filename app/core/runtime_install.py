"""Diagnose and install the external runtimes (ExifTool, FFmpeg).

ExifTool is the awkward one. On unix it is a perl script, so shipping it is
not enough: without a perl interpreter the wrapper fails, every ExifTool probe
reports "unavailable", and the two steps that need it then misbehave in
opposite ways -- device metadata returns ``ok=True`` and writes nothing at all,
while Live Photo dies later with "photo asset identifier missing", which names
a symptom the user has never heard of. Releases bundle a perl (see
``scripts/fetch_perl.sh``) so this rarely bites, but a developer checkout, a
damaged install, or a platform we did not ship for still lands here.

This module answers two questions separately:

* :func:`diagnose` -- what exactly is missing, in words a user can act on.
* :func:`install_runtime` -- fetch it into the per-user tools directory, no
  administrator rights required, then re-probe.

Everything here is best-effort by design: a failed install must never raise out
of the GUI's install button in a way that leaves the app unusable.
"""
from __future__ import annotations

import platform
import shutil
import stat
import subprocess
import tarfile
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from app.core.runtime_tools import user_install_dir

# Pinned to the ExifTool line the repo already ships (Tools/exiftool on unix,
# exiftool.exe in git for Windows). Keep the three in step.
EXIFTOOL_VERSION = "13.59"
EXIFTOOL_SHA256 = "87d3317882fdae9cb4dcfe57a96a378d0132ffc02c731315bf128b19ddcf7aac"
EXIFTOOL_TARBALL = (
    "https://codeload.github.com/exiftool/exiftool/tar.gz/refs/tags/" + EXIFTOOL_VERSION
)
PERL_RELEASE_BASE = "https://github.com/skaji/relocatable-perl/releases/latest/download"

DOWNLOAD_TIMEOUT = 120


class RuntimeInstallError(RuntimeError):
    """An install attempt failed. Carries the manual command for the user."""


@dataclass
class RuntimeProblem:
    """What is wrong with one external runtime, and how to fix it."""

    tool: str
    reason: str          # machine-ish key, for tests
    detail: str          # one sentence, shown as the headline
    manual: str = ""     # command the user can run themselves
    can_auto_install: bool = False
    extra: dict[str, str] = field(default_factory=dict)

    def explain(self, needs: list[str] | None = None) -> str:
        """The preflight refusal text.

        Multi-paragraph on purpose: what is missing, what it costs, and what to
        do -- matching the style of the other preflight messages, which are not
        length-limited and render fine in both the GUI dialog and the CLI.
        """
        used = "、".join(needs) if needs else "本次任务"
        parts = [
            f"已启用{used}，但 ExifTool 不可用。\n\n"
            f"原因：{self.detail}\n\n"
            "影响：设备信息（机型、ISO、软件、拍摄时间）不会被写入；"
            "Live Photo 会因缺少配对标识而失败。",
        ]
        if self.can_auto_install:
            parts.append(
                "\n请在「设置 → 外部运行时」中点击「安装」自动修复；"
                "或用以下命令手动安装：\n" + self.manual
            )
        elif self.manual:
            parts.append("\n请手动安装后重试：\n" + self.manual)
        return "".join(parts)


# --------------------------------------------------------------------------
# platform helpers
# --------------------------------------------------------------------------

def _platform_asset() -> str | None:
    """The relocatable-perl asset name for this machine, if there is one."""
    system = platform.system().lower()
    machine = platform.machine().lower()
    os_token = {"linux": "linux", "darwin": "darwin"}.get(system)
    arch_token = {"x86_64": "amd64", "amd64": "amd64",
                  "aarch64": "arm64", "arm64": "arm64"}.get(machine)
    if not os_token or not arch_token:
        return None
    return f"perl-{os_token}-{arch_token}.tar.xz"


def _perl_manual_command() -> str:
    """The platform's own way to get a perl, for the copy-paste fallback."""
    system = platform.system().lower()
    if system == "darwin":
        return "brew install perl   # 或从 https://www.perl.com 下载安装"
    if shutil.which("apt-get"):
        return "sudo apt-get install -y perl"
    if shutil.which("dnf"):
        return "sudo dnf install -y perl"
    if shutil.which("pacman"):
        return "sudo pacman -S perl"
    if shutil.which("zypper"):
        return "sudo zypper install perl"
    return "请用系统包管理器安装 perl（unix 版 ExifTool 需要解释器）"


# --------------------------------------------------------------------------
# diagnosis
# --------------------------------------------------------------------------

def diagnose(tool: str = "exiftool", *, portable_mode: bool = False) -> RuntimeProblem | None:
    """None when the tool works; otherwise what is wrong and how to fix it.

    Deliberately probes the way the pipeline probes (``probe_version=True``):
    a file that exists and carries the executable bit but cannot start is *not*
    available, and reporting it as such is the entire point here.
    """
    from app.core.runtime_tools import exiftool_status, ffmpeg_status

    status_fn = ffmpeg_status if tool == "ffmpeg" else exiftool_status
    status = status_fn(portable_mode=portable_mode, probe_version=True)
    if status.available:
        return None

    # Distinguish "not installed anywhere" from "installed but won't start":
    # the fix is completely different (download vs. install perl).
    candidates = _script_candidates(tool, portable_mode)
    present = [p for p in candidates if p.exists()]
    is_win = platform.system().lower().startswith("win")

    # "The files are there but nothing starts" and "there is nothing at all"
    # are different problems with different fixes, on *every* platform -- the
    # Windows distribution can equally arrive broken (a half-extracted copy, a
    # missing exiftool_files/ next to the exe). Saying "not found" about files
    # the user can see in their own install directory is just wrong.
    if present:
        asset = _platform_asset()
        problem = RuntimeProblem(
            tool=tool,
            reason="interpreter_missing" if (tool == "exiftool" and not is_win) else "broken",
            detail=(
                f"找到了 {present[0].name}，但它无法启动"
                + ("：unix 版 ExifTool 是 perl 脚本，而本机没有可用的 perl 解释器"
                   if (tool == "exiftool" and not is_win) else "")
            ),
            manual=(_perl_manual_command() if (tool == "exiftool" and not is_win)
                    else f"请删除 {present[0]} 后重新安装软件，或手动安装 {tool}"),
            can_auto_install=(tool == "exiftool" and not is_win and asset is not None),
            extra={"asset": asset or "", "path": str(present[0])},
        )
        return problem

    if tool == "exiftool" and is_win:
        return RuntimeProblem(
            tool=tool, reason="not_found",
            detail="没有找到 exiftool.exe",
            manual="请从 https://exiftool.org 下载 Windows 版，解压后把 exiftool.exe "
                   "与 exiftool_files 目录一起放到软件的 Tools\\exiftool\\ 下",
        )

    return RuntimeProblem(
        tool=tool,
        reason="not_found",
        detail=f"没有找到 {tool}",
        manual="请安装后重试",
    )


def _script_candidates(tool: str, portable_mode: bool) -> list[Path]:
    from app.core.runtime_tools import _bundled_candidates, _names

    out = [p for n in _names(tool) for p in _bundled_candidates(tool, n)]
    out.extend(p for n in _names(tool) for p in (user_install_dir(tool, portable_mode) / n,))
    return out


# --------------------------------------------------------------------------
# install
# --------------------------------------------------------------------------

def _remote_size(url: str) -> int | None:
    """Content-Length of ``url``, or None when the server will not say."""
    try:
        req = urllib.request.Request(
            url, method="HEAD", headers={"User-Agent": "AI-Image-Process"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.headers.get("Content-Length")
            return int(raw) if raw else None
    except Exception:  # noqa: BLE001 - purely informational
        return None


def _download_with_curl(url: str, dest: Path) -> bool:
    """Try curl (then wget). Returns False when neither is usable.

    Not an optimisation: codeload/github release CDNs on flaky links close the
    body early, and urllib cannot recover from that -- it either restarts (no
    Range support) or dies mid-archive. curl's own --retry and -C - handle both.

    The result is checked against Content-Length like the urllib path, so an
    empty or half-written file cannot pass as a successful download here while
    failing there.
    """
    expected: int | None = None
    expected_known = False
    for argv in (
        ["curl", "-fsSL", "--retry", "3", "--retry-delay", "2", "-C", "-",
         "-o", str(dest), url],
        ["wget", "-q", "-c", "-O", str(dest), url],
    ):
        if not shutil.which(argv[0]):
            continue
        # Only now that a downloader exists is the extra round trip worth it.
        if not expected_known:
            expected = _remote_size(url)
            expected_known = True
        try:
            proc = subprocess.run(
                argv, capture_output=True, text=True, timeout=DOWNLOAD_TIMEOUT * 2
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if proc.returncode != 0 or not dest.exists():
            continue
        got = dest.stat().st_size
        if got and (expected is None or got >= expected):
            return True
    return False


def _download(url: str, dest: Path, *, attempts: int = 3) -> None:
    """Fetch ``url`` to ``dest``, verifying the transfer actually completed."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if _download_with_curl(url, dest):
        return
    dest.unlink(missing_ok=True)
    last: Exception | None = None
    for _attempt in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AI-Image-Process"})
            with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT) as resp:
                declared = resp.headers.get("Content-Length")
                total = 0
                with open(dest, "wb") as out:
                    while True:
                        chunk = resp.read(1 << 16)
                        if not chunk:
                            break
                        out.write(chunk)
                        total += len(chunk)
            if declared and total != int(declared):
                raise RuntimeInstallError(f"下载不完整（{total}/{declared} 字节）")
            return
        except Exception as exc:  # noqa: BLE001 - retried, reported below
            last = exc
    raise RuntimeInstallError(f"下载失败（已重试 {attempts} 次）：{url}（{last}）")


def _chmod_exec(path: Path) -> None:
    try:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError:
        pass


def _install_perl(target: Path, log) -> None:
    asset = _platform_asset()
    if not asset:
        raise RuntimeInstallError(
            f"没有适用于本平台的便携 perl（{platform.system()}/{platform.machine()}）"
        )
    url = f"{PERL_RELEASE_BASE}/{asset}"
    log(f"下载 {asset} …")
    with tempfile.TemporaryDirectory() as tmp:
        tarball = Path(tmp) / "perl.tar.xz"
        _download(url, tarball)
        unpack = Path(tmp) / "unpacked"
        unpack.mkdir()
        with tarfile.open(tarball) as tf:
            tf.extractall(unpack, filter="data")
        roots = [p for p in unpack.iterdir() if (p / "bin" / "perl").is_file()]
        if not roots:
            raise RuntimeInstallError(f"{asset} 的结构不符合预期（缺少 bin/perl）")
        log("解压完成")
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copytree(roots[0], target)
        except OSError as exc:
            raise RuntimeInstallError(f"安装到 {target} 失败：{exc}") from exc
    for name in ("perl", "cpanm", "cpan"):
        _chmod_exec(target / "bin" / name)


def _install_exiftool_unix(target: Path, log) -> None:
    log(f"下载 ExifTool {EXIFTOOL_VERSION} …")
    with tempfile.TemporaryDirectory() as tmp:
        tarball = Path(tmp) / "exiftool.tar.gz"
        _download(EXIFTOOL_TARBALL, tarball)
        import hashlib

        digest = hashlib.sha256()
        with open(tarball, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                digest.update(chunk)
        if digest.hexdigest() != EXIFTOOL_SHA256:
            raise RuntimeInstallError("ExifTool 压缩包校验失败（sha256 不匹配），已放弃安装")
        with tarfile.open(tarball) as tf:
            tf.extractall(tmp, filter="data")
        src = Path(tmp) / f"exiftool-{EXIFTOOL_VERSION}"
        if not src.is_dir():
            raise RuntimeInstallError("ExifTool 压缩包结构不符合预期")
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / "exiftool", target / "exiftool.pl")
        shutil.copytree(src / "lib", target / "lib")
    # Same wrapper as scripts/fetch_exiftool.sh, so the installed copy behaves
    # identically to the bundled one (bundled perl first, host perl second).
    (target / "exiftool").write_text(
        "#!/bin/sh\n"
        "# Auto-installed by AI-Image-Process.\n"
        "dir=${0%/*}\n"
        '[ "$dir" = "$0" ] && dir=.\n'
        'dir=$(CDPATH= cd -- "$dir" 2>/dev/null && pwd) || exit 1\n'
        'bundled="$dir/../perl/bin/perl"\n'
        'if [ -x "$bundled" ]; then\n'
        '  exec "$bundled" "$dir/exiftool.pl" "$@"\n'
        "fi\n"
        'exec perl "$dir/exiftool.pl" "$@"\n',
        encoding="utf-8",
    )
    _chmod_exec(target / "exiftool")
    _chmod_exec(target / "exiftool.pl")


def _install_exiftool_windows(target: Path, log) -> None:
    # The Windows distribution is a *built* package hosted on exiftool.org
    # (SourceForge), not in the GitHub mirror we download from elsewhere. Rather
    # than hard-code a URL that may be unreachable, say so plainly.
    raise RuntimeInstallError(
        "Windows 版 ExifTool 需要从 https://exiftool.org 手动下载（内置的 "
        "exiftool.exe 随安装包提供，通常无需处理）"
    )


def install_runtime(
    tool: str = "exiftool",
    *,
    log=lambda _line: None,
    portable_mode: bool = False,
    # Post-install re-probe, not a timeout: `tool` is missing from the
    # signature on purpose -- an install that reports success must be proven by
    # the same probe the pipeline will run later.
    verify: bool = True,
) -> None:
    """Install ``tool`` into the per-user directory and verify it now works.

    Raises :class:`RuntimeInstallError` with an actionable message on failure;
    on success the next status probe reports available, so no restart is needed.

    Not safe to call concurrently for the same tool: two threads unpacking into
    the same directory produce exactly the half-installed state this feature
    exists to repair. The GUI serialises calls; other callers must too.
    """
    problem = diagnose(tool, portable_mode=portable_mode)
    if problem is None:
        return  # nothing to do -- the caller may race with another attempt

    is_win = platform.system().lower().startswith("win")
    if tool == "exiftool":
        if is_win:
            _install_exiftool_windows(user_install_dir(tool, portable_mode), log)
        else:
            # Always install the interpreter on unix, not only when perl was
            # the diagnosed cause. When nothing is installed at all we cannot
            # tell whether the host has a usable perl, and a portable one costs
            # the user nothing while making the result deterministic instead of
            # dependent on the machine.
            asset = problem.extra.get("asset") or _platform_asset()
            if asset:
                log(f"安装便携 perl（{asset}）到用户目录，不需要管理员权限 …")
                _install_perl(user_install_dir("perl", portable_mode), log)
            elif problem.reason == "interpreter_missing":
                raise RuntimeInstallError(
                    problem.manual or "本平台没有可用的便携 perl"
                )
            # The wrapper looks for a perl next to itself; the user-install
            # layout mirrors that: <tools>/perl/bin/perl next to <tools>/exiftool.
            log("安装 ExifTool …")
            _install_exiftool_unix(user_install_dir(tool, portable_mode), log)
    else:
        raise RuntimeInstallError(
            f"暂不支持自动安装 {tool}。{problem.manual}"
        )

    if verify:
        remaining = diagnose(tool, portable_mode=portable_mode)
        if remaining is not None:
            label = {"exiftool": "ExifTool"}.get(tool, tool)
            raise RuntimeInstallError(
                f"安装后 {label} 仍不可用：{remaining.detail}"
            )
    log("安装完成")


def manual_install_command(tool: str = "exiftool", *, portable_mode: bool = False) -> str:
    """The command to show when auto-install is unavailable or failed."""
    problem = diagnose(tool, portable_mode=portable_mode)
    return problem.manual if problem else ""