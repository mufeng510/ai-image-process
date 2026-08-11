"""Step protocol."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from app.config.schema import AppConfig
from app.core.models import FileRecord, JobWorkspace, StepResult


@dataclass
class StepContext:
    config: AppConfig
    workspace: JobWorkspace
    record: FileRecord
    resources: dict[str, Any]


class Step(ABC):
    id: str
    title: str

    def enabled(self, config: AppConfig) -> bool:
        return True

    def validate(self, config: AppConfig) -> list[str]:
        return []

    @abstractmethod
    def run(self, ctx: StepContext) -> StepResult:
        raise NotImplementedError
