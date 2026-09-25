"""iTunes compat backend (guided sync; kept for machines without Apple Devices)."""
from __future__ import annotations

from app.core.iphone_import.base import ImportCapability
from app.core.iphone_import.manual_sync import ManualSyncImporter


class ITunesImporter(ManualSyncImporter):
    name = "itunes"

    def capability(self) -> ImportCapability:
        return ImportCapability(
            automatic=False,
            requires_user_sync=True,
            transports=["usb", "wifi-sync"],
            notes="iTunes compat path; guided sync only",
        )
