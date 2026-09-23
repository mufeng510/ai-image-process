"""Wheel installer error hierarchy.

All user-facing messages are Chinese; callers may append manual-command hints.
"""

from __future__ import annotations


class WheelInstallError(RuntimeError):
    """Base error; str() is a user-facing Chinese message (no manual-command suffix — caller adds that)."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class PyPIError(WheelInstallError):
    """Raised for PyPI network/HTTP/JSON failures."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class ResolutionError(WheelInstallError):
    """Raised when dependency resolution fails (no compatible wheel, conflict, etc.)."""

    def __init__(self, message: str) -> None:
        super().__init__(message)