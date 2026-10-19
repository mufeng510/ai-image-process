"""IPhoneImporter abstract interface.

The iPhone import feature is guidance, not transport: nothing in this package
reads, copies or writes image files. A session may process several batches and
the user still has to pick which folder to import inside 爱思助手, so the tool's
whole job is to wake the assistant and print what to click.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ImportCapability:
    automatic: bool = False
    requires_user_sync: bool = True
    transports: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class ImportResult:
    ok: bool
    message: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class IPhoneImporter(ABC):
    name: str = "base"

    @abstractmethod
    def detect(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def guidance(self, folder_hint: str | None = None) -> ImportResult:
        """Wake the assistant, return the click-by-click steps for the user.

        `folder_hint` is display text only (usually the configured output
        directory): it is shown in the steps, never opened.
        """
        raise NotImplementedError

    def capability(self) -> ImportCapability:
        return ImportCapability()