"""Windows -> iPhone import helper (no iOS app; honest capability flags).

Guidance only: this package never reads or writes image files. It detects
爱思助手, tries to wake it, and prints the steps the user clicks through.
"""
from app.core.iphone_import.base import ImportCapability, ImportResult, IPhoneImporter
from app.core.iphone_import.i4tools import I4ToolsImporter

__all__ = ["ImportCapability", "ImportResult", "IPhoneImporter", "I4ToolsImporter"]