import random
from pathlib import Path

from app.core.device_library import DeviceLibrary


def test_load_phones():
    lib = DeviceLibrary.load(Path("assets/devices/phones.json"))
    assert len(lib.devices) == 28
    assert all(d.make == "Apple" for d in lib.devices)
    assert all(d.model.startswith("iPhone") for d in lib.devices)
    d = lib.choose("random", rng=random.Random(0))
    assert d.make and d.model and d.lens
