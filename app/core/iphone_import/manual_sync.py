"""Manual/guided sync importer: prepare dir + open Apple Devices, user syncs.

No fake 'auto import success': capability is honestly marked
requires_user_sync=True until a stable automated API is verified on a real
device (see docs/live-photo-testing.md matrix).
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from app.core.iphone_import.base import ImportCapability, ImportResult, IPhoneImporter


APPLE_DEVICES_HINTS = [
    r"C:\Program Files\Apple Devices\Apple Devices.exe",
    r"C:\Program Files (x86)\Apple Devices\Apple Devices.exe",
]
ITUNES_HINTS = [
    r"C:\Program Files\iTunes\iTunes.exe",
    r"C:\Program Files (x86)\iTunes\iTunes.exe",
]


class ManualSyncImporter(IPhoneImporter):
    name = "manual_sync"

    def detect(self) -> dict[str, object]:
        found = {
            "apple_devices": [p for p in APPLE_DEVICES_HINTS if Path(p).exists()],
            "itunes": [p for p in ITUNES_HINTS if Path(p).exists()],
        }
        return {
            "apple_devices_installed": bool(found["apple_devices"]),
            "itunes_installed": bool(found["itunes"]),
            "paths": found,
            "icloud_note": (
                "若 iPhone 开启了 iCloud Photos，Apple Devices/Windows 版照片同步选项不可用；"
                "此时请改用其他传输方式，导入器会明确提示而非显示可点击但必然失败的按钮。"
            ),
        }

    def validate(self, pairs: list[tuple[Path, Path | None]]) -> list[str]:
        issues: list[str] = []
        for jpg, mov in pairs:
            if not Path(jpg).exists():
                issues.append(f"photo missing: {jpg}")
            if mov is not None and not Path(mov).exists():
                issues.append(f"movie missing: {mov}")
        return issues

    def prepare(self, pairs: list[tuple[Path, Path | None]], dest: Path) -> Path:
        # Dedicated sync dir, NEVER the hidden-image library.
        dest.mkdir(parents=True, exist_ok=True)
        for jpg, mov in pairs:
            shutil.copy2(jpg, dest / Path(jpg).name)
            if mov is not None:
                shutil.copy2(mov, dest / Path(mov).name)
        return dest

    def import_live_photos(self, prepared: Path) -> ImportResult:
        det = self.detect()
        exe = (det["paths"]["apple_devices"] + det["paths"]["itunes"])
        if exe:
            try:
                subprocess.Popen([exe[0], str(prepared)])
                opened = True
            except Exception:
                opened = False
        else:
            opened = False
        steps = [
            "1. 用 USB 连接 iPhone 并在手机上信任此电脑（或使用同一 Wi-Fi 配对）。",
            f"2. 在 Apple Devices/iTunes 中选择设备 → 照片 → 从文件夹同步：{prepared}",
            "3. 勾选包含本次 JPG+MOV 的文件夹后点击 应用/同步。",
            "4. 在 iPhone 照片中确认识别为一张 Live Photo（长按可播放）；若显示为两个独立文件，说明配对未被识别，请保留样本并反馈。",
            "注意：若 iCloud Photos 已开启，Windows 端照片同步不可用，请先按提示处理；同步源目录请勿删除（镜像同步语义）。",
        ]
        if not (det["apple_devices_installed"] or det["itunes_installed"]):
            steps.insert(0, "未检测到 Apple Devices 或 iTunes：请先从微软商店/苹果官网安装后再同步（导入器不会伪造自动导入）。")
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
            transports=["usb", "wifi-sync"],
            notes="-guided sync via Apple Devices/iTunes; auto-import unverified, honestly flagged",
        )
