"""iPhone import via i4Tools: detect, wake, guided steps -- and no file I/O.

The feature is a hint, not a transport: it never scans, copies or writes the
processed images, because the user still selects the folder inside 爱思助手.
The tests below pin that contract: the steps are complete, and asking for
guidance leaves the disk exactly as it was.
"""
from pathlib import Path

from PIL import Image

from app.core.iphone_import import i4tools as i4t
from app.core.iphone_import.i4tools import I4ToolsImporter


def _tree(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*")}


def test_i4tools_capability_is_honest_and_manual():
    cap = I4ToolsImporter().capability()
    assert cap.automatic is False
    assert cap.requires_user_sync is True
    assert "不复制任何文件" in cap.notes
    det = I4ToolsImporter().detect()
    assert "i4tools_installed" in det


def test_i4tools_guidance_covers_the_click_path(monkeypatch):
    # Simulate an installed iTools: CI runners have none, and without an exe
    # the launcher stub would never be reached (opened_app would stay False).
    monkeypatch.setattr(
        I4ToolsImporter, "detect",
        lambda self: {"i4tools_installed": True, "paths": {"i4tools": ["C:\\fake\\i4Tools.exe"]}},
    )
    monkeypatch.setattr(i4t, "_launch_i4tools", lambda exe: (True, "test-launched"))
    res = I4ToolsImporter().guidance(folder_hint="E:\\exports")
    assert res.ok
    assert res.extra["opened_app"] is True
    assert "爱思助手" in res.message and "批量导入" in res.message
    assert "导入实况照片" in res.message and "照片处理工具" in res.message
    assert "同名" in res.message  # the pairing rule the user has to rely on
    assert "E:\\exports" in res.message  # the folder hint is shown, not opened


def test_i4tools_guidance_without_a_folder_hint(monkeypatch):
    monkeypatch.setattr(
        I4ToolsImporter, "detect",
        lambda self: {"i4tools_installed": False, "paths": {"i4tools": []}},
    )
    res = I4ToolsImporter().guidance(folder_hint=None)
    assert res.ok
    assert "未检测到爱思助手" in res.message
    assert "批量导入" in res.message
    assert res.extra["opened_app"] is False


def test_i4tools_guidance_touches_no_files(tmp_path, monkeypatch):
    """The whole point: no scanning, no copying, no staging directory."""
    run = tmp_path / "exports" / "20261018-010101"
    run.mkdir(parents=True)
    Image.new("RGB", (16, 16), (1, 2, 3)).save(run / "001.jpg")
    (run / "001.mov").write_bytes(b"\x00" * 64)
    before = _tree(tmp_path)

    monkeypatch.setattr(
        I4ToolsImporter, "detect",
        lambda self: {"i4tools_installed": False, "paths": {"i4tools": []}},
    )
    I4ToolsImporter().guidance(folder_hint=str(run))
    assert _tree(tmp_path) == before


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