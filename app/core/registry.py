
"""Step registry."""
from __future__ import annotations

from typing import Iterable

from app.core.steps.base import Step


class StepRegistry:
    def __init__(self) -> None:
        self._steps: dict[str, Step] = {}

    def register(self, step: Step) -> None:
        self._steps[step.id] = step

    def get(self, step_id: str) -> Step:
        return self._steps[step_id]

    def all(self) -> list[Step]:
        return list(self._steps.values())

    def ordered(self, ids: Iterable[str]) -> list[Step]:
        return [self._steps[i] for i in ids if i in self._steps]
