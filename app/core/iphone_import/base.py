"""IPhoneImporter abstract interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
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
    prepared_dir: Path | None = None
    imported: list[Path] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


class IPhoneImporter(ABC):
    name: str = "base"

    @abstractmethod
    def detect(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def validate(self, pairs: list[tuple[Path, Path | None]]) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def prepare(self, pairs: list[tuple[Path, Path | None]], dest: Path) -> Path:
        raise NotImplementedError

    @abstractmethod
    def import_live_photos(self, prepared: Path) -> ImportResult:
        raise NotImplementedError

    def capability(self) -> ImportCapability:
        return ImportCapability()
