"""i4Tools (爱思助手) backend: guided Live Photo import.

Research conclusion (see docs/live-photo-testing.md):
- Apple Devices/iTunes folder-sync treats JPG+MOV as two separate media and
  is unavailable when iCloud Photos is on -> poor fit for Live Photo.
- i4Tools has a dedicated flow: 我的设备 -> 照片 -> 相机胶卷 -> 导入实况照片
  -> 单张导入/批量导入, requiring JPG (or HEIC) + MOV with identical basenames,
  then confirming on the phone via 照片处理工具/极速版. The pair then shows as
  a single LIVE photo instead of two files.
- i4Tools exposes no stable public CLI/automation API, so this backend stays
  honest: automatic=False, requires_user_sync=True (user confirms in i4Tools
  + on the phone). We only detect the install, prepare the batch folder with
  matching basenames, and best-effort launch i4Tools.
"""
from __future__ import annotations

import glob
import os
import subprocess
from pathlib import Path

from app.core.iphone_import.base import ImportCapability, ImportResult
from app.core.iphone_import.manual_sync import ManualSyncImporter


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


class I4ToolsImporter(ManualSyncImporter):
    name = "i4tools"

    def detect(self) -> dict[str, object]:
        found = [p for p in _candidate_exes() if Path(p).exists()]
        return {
            "i4tools_installed": bool(found),
            "paths": {"i4tools": found},
        }

    def validate(self, pairs: list[tuple[Path, Path | None]]) -> list[str]:
        issues: list[str] = []
        for jpg, mov in pairs:
            if not Path(jpg).exists():
                issues.append(f"photo missing: {jpg}")
                continue
            if mov is None or not Path(mov).exists():
                # i4Tools batch import matches JPG+MOV by identical basename;
                # a still without its MOV would fail matching / lose LIVE.
                issues.append(f"movie missing for live photo (need 同名 MOV): {jpg}")
            elif Path(jpg).stem != Path(mov).stem:
                issues.append(f"live photo basename mismatch: {jpg} vs {mov}")
        return issues

    def import_live_photos(self, prepared: Path) -> ImportResult:
        det = self.detect()
        exe_list = det["paths"]["i4tools"]  # type: ignore[index]
        opened = False
        if exe_list:
            try:
                subprocess.Popen([exe_list[0]])
                opened = True
            except Exception:
                opened = False
        steps = [
            "1. 用 USB 连接 iPhone 并在手机上信任此电脑，打开爱思助手并等待识别设备。",
            f"2. 在爱思助手中进入：我的设备 → 照片 → 相机胶卷 → 导入实况照片 → 批量导入，选择文件夹：{prepared}",
            "3. 批量导入要求同一目录下 JPG 与 MOV 文件名一致（除扩展名外完全相同），本工具已按此规则准备；若提示匹配失败请检查文件名。",
            "4. 按爱思助手提示在手机上打开 照片处理工具/极速版（首次需安装并授予照片访问权限），等待导入完成。",
            "5. 在 iPhone 照片中确认显示为一张 Live Photo（左上角 LIVE，长按可播放）；若分裂为照片+视频两个文件，说明配对未被识别，请保留样本并反馈。",
        ]
        if not det["i4tools_installed"]:
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
            prepared_dir=prepared,
            extra={"opened_app": opened, **det},
        )

    def capability(self) -> ImportCapability:
        return ImportCapability(
            automatic=False,
            requires_user_sync=True,
            transports=["usb"],
            notes="i4Tools guided live-photo import (批量导入 JPG+MOV 同名配对); no public automation API",
        )
