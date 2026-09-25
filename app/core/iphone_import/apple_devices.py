"""Apple Devices backend (compat shim over manual guided sync).

Spike conclusion (Windows): Apple Devices exposes no stable public
third-party automation API for photo sync; driving it via coordinates/macros
is explicitly out of scope. This backend therefore reuses the guided-sync
flow and reports requires_user_sync=True.
"""
from __future__ import annotations

from pathlib import Path

from app.core.iphone_import.base import ImportCapability, ImportResult
from app.core.iphone_import.manual_sync import ManualSyncImporter


class AppleDevicesImporter(ManualSyncImporter):
    name = "apple_devices"

    def capability(self) -> ImportCapability:
        return ImportCapability(
            automatic=False,
            requires_user_sync=True,
            transports=["usb", "wifi-sync"],
            notes="Apple Devices preferred; no public automation API - guided sync",
        )
