"""In-app installation of the optional remove-ai-watermarks dependency.

Two features depend on this package and can each be installed without
leaving the app (settings dialog buttons map 1:1 to these features):

- "provenance"   清理 AI Metadata  -> remove-ai-watermarks>=0.26.0
- "visible"      去除可见水印      -> remove-ai-watermarks[visible]>=0.26.0
- "onnxruntime"  migan/lama 填充后端支持 -> onnxruntime>=1.16

Install strategy:

- Development checkout (non-frozen): run ``python -m pip install <spec>``
  with the running interpreter so the package lands in the active venv.
- Frozen app (PyInstaller): the bundle ships pip; run it in-process with
  ``--only-binary`` and ``--target`` pointing at a writable per-user
  directory that is prepended to sys.path (see ensure_runtime_site).
  If pip is unavailable in the bundle, fall back to a system interpreter
  whose major.minor version matches the frozen runtime — binary wheels
  (cv2/onnxruntime) only load in a matching interpreter, so an exact
  match is required.
"""
from __future__ import annotations

import io
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from app.config.paths import is_frozen, user_data_dir
from app.platform import CREATE_NO_WINDOW

# Installable features -> pip requirement specs. The dialog exposes one
# install button per feature (the two that matter: provenance + visible).
FEATURE_SPECS: dict[str, str] = {
    "provenance": "remove-ai-watermarks>=0.26.0",
    "visible": "remove-ai-watermarks[visible]>=0.26.0",
    # The learned fill backends need onnxruntime + huggingface-hub; the
    # package's own migan extra is the supported combination for both.
    "onnxruntime": "remove-ai-watermarks[migan]>=0.26.0",
}

FEATURE_LABELS: dict[str, str] = {
    "provenance": "清理 AI Metadata",
    "visible": "去除可见水印",
    "onnxruntime": "migan/lama 后端支持",
}

SITE_DIR_NAME = "python-packages"


def feature_spec(feature: str) -> str:
    try:
        return FEATURE_SPECS[feature]
    except KeyError:
        raise ValueError(f"unknown installable feature: {feature!r}") from None


def feature_label(feature: str) -> str:
    return FEATURE_LABELS.get(feature, feature)


def runtime_site_dir(portable_mode: bool = False) -> Path:
    """Writable directory runtime-installed packages live in (frozen apps)."""
    return user_data_dir(portable_mode) / SITE_DIR_NAME


def ensure_runtime_site(portable_mode: bool = False) -> Path:
    """Prepend the runtime site dir to sys.path so installs are importable.

    Safe to call repeatedly (deduplicated by path string); returns the dir.
    """
    site = runtime_site_dir(portable_mode)
    try:
        site.mkdir(parents=True, exist_ok=True)
    except OSError:
        return site
    text = str(site)
    if text not in sys.path:
        sys.path.insert(0, text)
    return site


# ----- pip invocation -----


def _frozen_version() -> str:
    return f"{sys.version_info[0]}.{sys.version_info[1]}"


def _base_command() -> list[str]:
    """Interpreter prefix for `python -m pip` (dev: the running one)."""
    return [sys.executable]


def _system_python_candidates() -> list[list[str]]:
    ver = _frozen_version()
    if sys.platform.startswith("win"):
        return [
            ["py", f"-{ver}"],
            [f"python{ver}"],
            ["python3"],
            ["python"],
        ]
    return [
        [f"python{ver}"],
        ["python3"],
        ["python"],
    ]


def _check_system_python(candidate: list[str]) -> bool:
    """True when candidate runs the frozen runtime version and has pip."""
    probe = "import sys; print('%d.%d' % sys.version_info[:2])"
    try:
        proc = subprocess.run(
            [*candidate, "-c", probe],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if proc.returncode != 0 or proc.stdout.strip() != _frozen_version():
        return False
    try:
        pip_check = subprocess.run(
            [*candidate, "-m", "pip", "--version"],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return pip_check.returncode == 0


def _find_system_python() -> list[str] | None:
    for candidate in _system_python_candidates():
        if _check_system_python(candidate):
            return candidate
    return None


def _pip_common_args() -> list[str]:
    return [
        "install",
        "--disable-pip-version-check",
        "--no-input",
    ]


def _target_args(target: Path) -> list[str]:
    # Wheel-only: no compiler/toolchain exists in a frozen app, and binary
    # wheels must match the runtime interpreter anyway.
    return [
        "--only-binary=:all:",
        "--upgrade",
        "--target",
        str(target),
    ]


def _emit(log: Callable[[str], None] | None, line: str) -> None:
    if log is not None and line.strip():
        log(line.rstrip())


def _run_pip_inprocess(specs: list[str], target: Path, log: Callable[[str], None] | None) -> None:
    """Run pip from inside the frozen bundle with --target.

    pip is bundled into the app (see build/ai-image-process.spec). Console
    streams may be None in windowed builds, so they are redirected to a
    buffer for the duration and pip's own --log file is kept as a fallback
    source for error details.
    """
    logfile = Path(tempfile.gettempdir()) / "ai-image-process-pip.log"
    args = [
        *_pip_common_args(),
        *_target_args(target),
        "--log",
        str(logfile),
        *specs,
    ]
    buf = io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout = buf
    sys.stderr = buf
    try:
        # Import inside the redirect: pip's logging handlers capture the
        # streams at import time, and windowed frozen apps may have none.
        from pip._internal.cli.main import main as pip_main

        rc = pip_main(args)
    finally:
        sys.stdout, sys.stderr = old_out, old_err

    if rc == 0:
        _emit(log, "pip 安装完成")
        return

    detail = ""
    try:
        detail = logfile.read_text(encoding="utf-8", errors="replace")[-2000:]
    except OSError:
        detail = buf.getvalue()[-2000:]
    raise RuntimeError(
        f"pip 退出码 {rc}，安装失败。详情：\n{detail or '（无输出）'}"
    )


def _run_pip_subprocess(
    base: list[str], specs: list[str], target: Path | None, log: Callable[[str], None] | None
) -> None:
    cmd = [
        *base,
        "-m",
        "pip",
        *_pip_common_args(),
        *(["--no-warn-script-location"] if target is not None else []),
        *(_target_args(target) if target is not None else []),
        *specs,
    ]
    env = dict(os.environ)
    env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            creationflags=CREATE_NO_WINDOW,
        )
    except OSError as exc:
        raise RuntimeError(f"无法启动 pip（{base}）：{exc}") from exc
    assert proc.stdout is not None
    with proc.stdout:
        for line in proc.stdout:
            _emit(log, line)
    rc = proc.wait()
    if rc != 0:
        raise RuntimeError(f"pip 退出码 {rc}，安装失败")


def install_specs(specs: list[str], log: Callable[[str], None] | None = None, portable_mode: bool = False) -> None:
    """Install the given pip requirement specs for this environment."""
    if not specs:
        return
    if not is_frozen():
        _run_pip_subprocess(_base_command(), specs, None, log)
        return

    target = ensure_runtime_site(portable_mode)
    try:
        import pip  # noqa: F401
    except Exception:  # noqa: BLE001
        base = _find_system_python()
        if base is None:
            raise RuntimeError(
                "软件内置安装器不可用，且未在系统中找到与运行时匹配的 Python "
                f"{_frozen_version()}（需含 pip）。请安装匹配版本的 Python 后重试，"
                "或手动执行：pip install " + " ".join(specs)
            ) from None
        _run_pip_subprocess(base, specs, target, log)
        return

    _run_pip_inprocess(specs, target, log)


def install_feature(feature: str, log: Callable[[str], None] | None = None, portable_mode: bool = False) -> None:
    """Install the dependency for one app feature (see FEATURE_SPECS)."""
    spec = feature_spec(feature)
    _emit(log, f"正在安装 {spec} …")
    install_specs([spec], log=log, portable_mode=portable_mode)
    ensure_runtime_site(portable_mode)
    _emit(log, f"{feature_label(feature)} 依赖安装完成")
