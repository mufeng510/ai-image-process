"""Shared base for iPhone importers: pair-folder preparation.

Legacy Apple Devices/iTunes guided-sync was removed; Live Photo import goes
exclusively through i4Tools (爱思助手), see
app/core/iphone_import/i4tools.py. This module only keeps the shared
JPG+MOV pair-folder preparation logic.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from app.core.iphone_import.base import ImportCapability, ImportResult, IPhoneImporter


class ManualSyncImporter(IPhoneImporter):
    name = "manual_sync"

    def detect(self) -> dict[str, object]:
        raise NotImplementedError("use I4ToolsImporter.detect()")

    def validate(self, pairs: list[tuple[Path, Path | None]]) -> list[str]:
        issues: list[str] = []
        for jpg, mov in pairs:
            if not Path(jpg).exists():
                issues.append(f"photo missing: {jpg}")
            if mov is not None and not Path(mov).exists():
                issues.append(f"movie missing: {mov}")
        return issues

    def prepare(self, pairs: list[tuple[Path, Path | None]], dest: Path) -> Path:
        # Dedicated import dir, NEVER the hidden-image library.
        # JPG+MOV keep identical basenames so i4Tools 批量导入 can match pairs.
        dest.mkdir(parents=True, exist_ok=True)
        for jpg, mov in pairs:
            shutil.copy2(jpg, dest / Path(jpg).name)
            if mov is not None:
                shutil.copy2(mov, dest / Path(mov).name)
        return dest

    def import_live_photos(self, prepared: Path) -> ImportResult:
        raise NotImplementedError("use I4ToolsImporter.import_live_photos()")

    def capability(self) -> ImportCapability:
        raise NotImplementedError("use I4ToolsImporter.capability()")
