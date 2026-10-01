"""iPhone import via i4Tools only: detect/prepare/guided steps, never fake auto-import."""
from pathlib import Path

from PIL import Image

from app.core.iphone_import import i4tools as i4t
from app.core.iphone_import.i4tools import I4ToolsImporter


def test_i4tools_prepare_and_capability(tmp_path, monkeypatch):
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
    # import dir must be independent (caller-provided, not the hidden library);
    # stub the launcher so tests never pop UAC / real apps.
    # Simulate an installed iTools: CI runners have none, and without an exe
    # the launcher stub would never be reached (opened_app would stay False).
    monkeypatch.setattr(
        I4ToolsImporter, "detect",
        lambda self: {"i4tools_installed": True, "paths": {"i4tools": ["C:\\fake\\i4Tools.exe"]}},
    )
    monkeypatch.setattr(i4t, "_launch_i4tools", lambda exe: (True, "test-launched"))
    res = imp.import_live_photos(dest)
    assert res.ok and "爱思助手" in res.message and "批量导入" in res.message
    assert res.extra["opened_app"] is True


def test_i4tools_launch_fallback_on_elevation(tmp_path, monkeypatch):
    # Regression (WinError 740): plain Popen fails for iTools (needs admin),
    # so the importer must fall back to runas instead of silently doing nothing.
    # Fully hermetic: stub the module's own `os`/`subprocess` references so the
    # test behaves identically on Windows and on Linux/macOS CI (where the
    # runas fallback would otherwise be skipped via os.name, and no iTools
    # exists). _launch_i4tools only uses os.name and subprocess.Popen.
    import types

    calls: dict = {}

    def fake_popen(*a, **k):
        raise OSError(740, "elevation required")

    def fake_runas(exe: str) -> bool:
        calls["exe"] = exe
        return True

    monkeypatch.setattr(i4t, "os", types.SimpleNamespace(name="nt"))
    monkeypatch.setattr(i4t, "subprocess", types.SimpleNamespace(Popen=fake_popen))
    monkeypatch.setattr(i4t, "_runas_launch", fake_runas)
    opened, detail = i4t._launch_i4tools(r"C:\fake\i4Tools.exe")
    assert opened is True and calls.get("exe") == r"C:\fake\i4Tools.exe"

    monkeypatch.setattr(i4t, "_runas_launch", lambda exe: False)
    opened, detail = i4t._launch_i4tools(r"C:\fake\i4Tools.exe")
    assert opened is False and "手动" in detail


def test_i4tools_detect_versioned_dir(tmp_path, monkeypatch):
    # Regression: installs use versioned folders (i4Tools9, ...), not just i4Tools.
    fake_base = tmp_path / "PF"
    exe = fake_base / "i4Tools99" / "i4Tools.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    monkeypatch.setenv("ProgramFiles", str(fake_base))
    monkeypatch.setenv("ProgramW6432", str(fake_base))
    monkeypatch.setenv("ProgramFiles(x86)", str(fake_base))
    det = I4ToolsImporter().detect()
    assert det["i4tools_installed"] is True
    assert str(exe) in det["paths"]["i4tools"]


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
