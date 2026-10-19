"""i4Tools (爱思助手) backend: guided Live Photo import.

Research conclusion (see docs/live-photo-testing.md):
- Apple Devices/iTunes folder-sync treats JPG+MOV as two separate media and
  is unavailable when iCloud Photos is on -> poor fit for Live Photo.
- i4Tools has a dedicated flow: 我的设备 -> 照片 -> 相机胶卷 -> 导入实况照片
  -> 单张导入/批量导入, requiring JPG (or HEIC) + MOV with identical basenames
  in one folder, then confirming on the phone via 照片处理工具/极速版. The pair
  then shows as a single LIVE photo instead of two files.
- The extension check is CASE-SENSITIVE: a bundle whose bytes are otherwise
  valid is silently skipped when written lowercase "x.jpg + x.mov". Device
  exports are "x.JPG + x.MOV" and so is everything this project commits
  (see output_format.OUTPUT_JPG_EXT / OUTPUT_MOV_EXT).
- i4Tools exposes no stable public CLI/automation API, so this backend stays
  honest: automatic=False, requires_user_sync=True (user confirms in i4Tools
  + on the phone).

It therefore touches no files at all: a run already publishes the pairing
shape i4Tools wants, a session may hold several batches, and the user picks
the folder inside 爱思助手 regardless. All this backend does is detect the
install, best-effort launch it, and spell out the steps.
"""
from __future__ import annotations

import glob
import os
import subprocess
from pathlib import Path

from app.core.iphone_import.base import ImportCapability, ImportResult, IPhoneImporter


# Known install folder names; new major versions use versioned folders
# (observed: i4Tools -> i4Tools7 -> i4Tools9), so detection also globs
# i4Tools* and consults the uninstall registry (covers custom install dirs).
_DIR_NAMES = ("i4Tools", "i4Tools7", "i4Tools9", "爱思助手")


def _program_files_dirs() -> list[Path]:
    dirs: list[Path] = []
    for var in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        v = os.environ.get(var)
        if v and Path(v) not in dirs:
            dirs.append(Path(v))
    for raw in (r"C:\Program Files", r"C:\Program Files (x86)"):
        if Path(raw) not in dirs:
            dirs.append(Path(raw))
    return dirs


def _registry_install_exe() -> str | None:
    """Find i4Tools.exe via uninstall registry (custom install locations)."""
    try:
        import winreg
    except ImportError:  # non-Windows
        return None
    roots = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    for root, sub in roots:
        try:
            with winreg.OpenKey(root, sub) as key:
                subkeys = [winreg.EnumKey(key, i) for i in range(winreg.QueryInfoKey(key)[0])]
        except OSError:
            continue
        for name in subkeys:
            try:
                with winreg.OpenKey(key, name) as sk:
                    disp = str(winreg.QueryValueEx(sk, "DisplayName")[0])
                    loc = ""
                    for value in ("DisplayIcon", "InstallLocation"):
                        try:
                            loc = str(winreg.QueryValueEx(sk, value)[0])
                            break
                        except OSError:
                            continue
            except OSError:
                continue
            if "爱思" not in disp and "i4Tools" not in disp:
                continue
            loc = loc.split(",")[0].strip().strip('"')
            if not loc:
                continue
            p = Path(loc)
            if p.is_dir():
                cand = p / "i4Tools.exe"
                if cand.exists():
                    return str(cand)
            elif p.name.lower() == "i4tools.exe" and p.exists():
                return str(p)
    return None


def _candidate_exes() -> list[str]:
    cands: list[str] = []

    def add(p: Path | str) -> None:
        s = str(p)
        if s and s not in cands:
            cands.append(s)

    for base in _program_files_dirs():
        for name in _DIR_NAMES:
            add(base / name / "i4Tools.exe")
        try:
            for hit in sorted(glob.glob(str(base / "i4Tools*" / "i4Tools.exe"))):
                add(hit)
            for hit in sorted(glob.glob(str(base / "*爱思*" / "i4Tools.exe"))):
                add(hit)
        except Exception:
            pass
    reg = _registry_install_exe()
    if reg:
        add(reg)
    return cands


def _runas_launch(exe: str) -> bool:
    """Launch exe requesting elevation (UAC prompt). Returns True if accepted."""
    import ctypes

    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, None, None, 1)
    return int(rc) > 32


def _launch_i4tools(exe: str) -> tuple[bool, str]:
    """Best-effort launch of iTools. Never raises; returns (opened, detail).

    i4Tools.exe requires elevation (plain Popen fails with WinError 740),
    so fall back to a runas/UAC launch before giving up.
    """
    try:
        subprocess.Popen([exe], cwd=str(Path(exe).parent))
        return True, "已拉起爱思助手"
    except OSError as exc:
        last = f"直接拉起失败({exc})"
    except Exception as exc:  # noqa: BLE001
        return False, f"拉起失败({exc})，请手动打开爱思助手"
    if os.name == "nt":
        try:
            if _runas_launch(exe):
                return True, "已通过管理员权限拉起爱思助手（请在 UAC 弹窗点“是”）"
            last = f"{last}；提权拉起被拒绝或失败"
        except Exception as exc:  # noqa: BLE001
            last = f"{last}；提权拉起失败({exc})"
    return False, last + "；请手动打开爱思助手继续"


class I4ToolsImporter(IPhoneImporter):
    name = "i4tools"

    def detect(self) -> dict[str, object]:
        found = [p for p in _candidate_exes() if Path(p).exists()]
        return {
            "i4tools_installed": bool(found),
            "paths": {"i4tools": found},
        }

    def guidance(self, folder_hint: str | None = None) -> ImportResult:
        """Launch 爱思助手 if installed and return the steps. Reads nothing."""
        det = self.detect()
        exe_list = det["paths"]["i4tools"]  # type: ignore[index]
        opened, launch_detail = _launch_i4tools(exe_list[0]) if exe_list else (False, "")
        steps = [
            "1. 用 USB 连接 iPhone 并在手机上信任此电脑，打开爱思助手并等待识别设备。",
            "2. 在爱思助手中进入：我的设备 → 照片 → 相机胶卷 → 导入实况照片 → 批量导入。",
            "3. 在弹出的对话框里选择**要导入的那一批处理结果目录**。该目录里的实况照片已经是"
            "「同名 x.JPG + x.MOV」成对存放（爱思助手按文件名配对，且对扩展名做**区分大小写**"
            "的检查，小写 .jpg/.mov 会被直接跳过；两者必须在同一目录、"
            "除扩展名外完全相同）；一次处理出多批时，选你要导入的那一批即可。",
        ]
        if folder_hint:
            steps.append(f"   参考：本软件当前输出目录为 {folder_hint}"
                         "（每次任务会在其下新建一个时间戳子文件夹，产物在那里）。")
        steps += [
            "4. 按爱思助手提示在手机上打开 照片处理工具/极速版（首次需安装并授予照片访问权限），"
            "等待导入完成。",
            "5. 在 iPhone 照片中确认显示为一张 Live Photo（左上角 LIVE，长按可播放）；"
            "若分裂为照片+视频两个文件，说明配对未被识别，请保留样本并反馈。",
        ]
        if det["i4tools_installed"]:
            steps.insert(0, f"爱思助手唤起状态：{launch_detail}。")
        else:
            checked = ", ".join(str(d) for d in _program_files_dirs())
            steps.insert(
                0,
                "未检测到爱思助手（已检查 Program Files 各版本目录与卸载注册表）："
                f"{checked}。请先从 i4.cn 官网安装后再导入（导入器不会伪造自动导入）。"
                "若安装在自定义位置仍提示未安装，请反馈安装路径。",
            )
        return ImportResult(
            ok=True,
            message="\n".join(steps),
            extra={"opened_app": opened, "launch_detail": launch_detail, **det},
        )

    def capability(self) -> ImportCapability:
        return ImportCapability(
            automatic=False,
            requires_user_sync=True,
            transports=["usb"],
            notes="i4Tools guided live-photo import (指引 + 唤起，不复制任何文件); no public automation API",
        )
