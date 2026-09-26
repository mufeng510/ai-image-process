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

import subprocess
from pathlib import Path

from app.core.iphone_import.base import ImportCapability, ImportResult
from app.core.iphone_import.manual_sync import ManualSyncImporter


I4TOOLS_HINTS = [
    r"C:\Program Files\i4Tools\i4Tools.exe",
    r"C:\Program Files (x86)\i4Tools\i4Tools.exe",
    # Older installers used a Chinese folder name.
    r"C:\Program Files\爱思助手\i4Tools.exe",
    r"C:\Program Files (x86)\爱思助手\i4Tools.exe",
    r"C:\Program Files\i4Tools7\i4Tools.exe",
    r"C:\Program Files (x86)\i4Tools7\i4Tools.exe",
]


class I4ToolsImporter(ManualSyncImporter):
    name = "i4tools"

    def detect(self) -> dict[str, object]:
        found = [p for p in I4TOOLS_HINTS if Path(p).exists()]
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
            steps.insert(
                0,
                "未检测到爱思助手（默认路径 C:\\Program Files (x86)\\i4Tools\\i4Tools.exe）："
                "请先从 i4.cn 官网安装后再导入（导入器不会伪造自动导入）。",
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
