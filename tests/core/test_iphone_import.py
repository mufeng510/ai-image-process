"""iPhone import via i4Tools only: detect/prepare/guided steps, never fake auto-import."""
from pathlib import Path

from PIL import Image

from app.core.iphone_import.i4tools import I4ToolsImporter


def test_i4tools_prepare_and_capability(tmp_path):
    jpg = tmp_path / "001.jpg"; mov = tmp_path / "001.mov"
    Image.new("RGB", (32, 32), (1, 2, 3)).save(jpg)
    mov.write_bytes(b"\x00" * 8192)
    imp = I4ToolsImporter()
    det = imp.detect()
    assert "i4tools_installed" in det
    assert imp.capability().automatic is False
    assert imp.capability().requires_user_sync is True
    dest = imp.prepare([(jpg, mov)], tmp_path / "sync")
    assert (dest / "001.jpg").exists() and (dest / "001.mov").exists()
    # import dir must be independent (caller-provided, not the hidden library)
    res = imp.import_live_photos(dest)
    assert res.ok and "爱思助手" in res.message and "批量导入" in res.message


def test_i4tools_requires_paired_mov(tmp_path):
    jpg = tmp_path / "001.jpg"; mov = tmp_path / "001.mov"
    Image.new("RGB", (32, 32), (1, 2, 3)).save(jpg)
    mov.write_bytes(b"\x00" * 8192)
    imp = I4ToolsImporter()
    assert imp.validate([(jpg, mov)]) == []
    # still without MOV fails matching in 爱思批量导入
    assert imp.validate([(jpg, None)])
    bad = tmp_path / "002.mov"
    bad.write_bytes(b"\x00" * 8192)
    assert imp.validate([(jpg, bad)])
