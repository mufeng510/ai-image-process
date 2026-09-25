"""Windows -> iPhone import helpers (no iOS app; honest capability flags)."""
from app.core.iphone_import.base import ImportCapability, ImportResult, IPhoneImporter
from app.core.iphone_import.manual_sync import ManualSyncImporter

__all__ = ["ImportCapability", "ImportResult", "IPhoneImporter", "ManualSyncImporter"]
