"""iPhone import: detect/prepare/guided steps, never fake auto-import."""
from pathlib import Path

from PIL import Image

from app.core.iphone_import.apple_devices import AppleDevicesImporter
from app.core.iphone_import.itunes import ITunesImporter
from app.core.iphone_import.manual_sync import ManualSyncImporter


def test_manual_prepare_and_capability(tmp_path):
    jpg = tmp_path / "001.jpg"; mov = tmp_path / "001.mov"
    Image.new("RGB", (32, 32), (1, 2, 3)).save(jpg)
    mov.write_bytes(b"\x00" * 8192)
    imp = ManualSyncImporter()
    det = imp.detect()
    assert "apple_devices_installed" in det
    assert imp.capability().automatic is False
    assert imp.capability().requires_user_sync is True
    dest = imp.prepare([(jpg, mov)], tmp_path / "sync")
    assert (dest / "001.jpg").exists() and (dest / "001.mov").exists()
    # sync dir must be independent (caller-provided, not the hidden library)
    res = imp.import_live_photos(dest)
    assert res.ok and "同步" in res.message


def test_backends_honest_flags():
    assert AppleDevicesImporter().capability().requires_user_sync is True
    assert ITunesImporter().capability().requires_user_sync is True
