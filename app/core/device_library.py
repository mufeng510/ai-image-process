
"""Phone device profiles."""
from __future__ import annotations

import json
import random
from pathlib import Path

from app.core.models import DeviceProfile


class DeviceLibrary:
    def __init__(self, devices: list[DeviceProfile]) -> None:
        if not devices:
            raise ValueError("device library is empty")
        self.devices = devices
        self._by_id = {d.id: d for d in devices}

    @classmethod
    def load(cls, path: Path) -> "DeviceLibrary":
        data = json.loads(path.read_text(encoding="utf-8"))
        devices = [
            DeviceProfile(id=d["id"], make=d["make"], model=d["model"], lens=d["lens"])
            for d in data.get("devices", [])
        ]
        return cls(devices)

    def get(self, device_id: str) -> DeviceProfile:
        return self._by_id[device_id]

    def choose(self, selection: str = "random", fixed_device_id: str | None = None, rng: random.Random | None = None) -> DeviceProfile:
        if selection == "fixed":
            if not fixed_device_id:
                raise ValueError("fixed_device_id required")
            return self.get(fixed_device_id)
        r = rng or random.Random()
        return r.choice(self.devices)
