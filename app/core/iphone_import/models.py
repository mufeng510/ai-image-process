"""Shared import models (re-exported via base for stable imports)."""
from app.core.iphone_import.base import ImportCapability, ImportResult

__all__ = ["ImportCapability", "ImportResult"]
