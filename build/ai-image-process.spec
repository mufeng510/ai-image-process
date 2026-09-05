# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir spec for AI Image Process.

Build from repo root:
  .venv/bin/pyinstaller build/ai-image-process.spec
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

block_cipher = None

# SPECPATH is the directory containing this spec file (build/)
_spec_dir = Path(SPECPATH).resolve()
if _spec_dir.is_file():
    _spec_dir = _spec_dir.parent
repo = _spec_dir.parent
run_gui = repo / "scripts" / "run_gui.py"
if not run_gui.exists():
    raise SystemExit(f"run_gui entry not found: {run_gui}")

datas = [
    (str(repo / "assets" / "devices" / "phones.json"), "assets/devices"),
    (str(repo / "assets" / "icc" / "sRGB-IEC61966-2.1.icc"), "assets/icc"),
]

exif_dir = repo / "Tools" / "exiftool"
if exif_dir.exists():
    datas.append((str(exif_dir), "Tools/exiftool"))

hiddenimports = [
    "app",
    "app.main",
    "app.main_cli",
    "app.gui",
    "app.gui.app",
    "app.gui.main_window",
    "app.gui.settings_dialog",
    "app.gui.workers.pipeline_worker",
    "app.gui.widgets.drop_zone",
    "app.gui.naming_presets",
    "app.core",
    "app.core.pipeline",
    "app.core.steps",
    "app.core.dependency_installer",
    "app.config",
    "PIL",
    "PIL.Image",
    "PIL.ImageCms",
]

binaries = []
for pkg in ("PySide6", "shiboken6"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

# Bundle pip so the app can install optional dependencies (e.g.
# remove-ai-watermarks) at runtime into a user-writable directory.
try:
    d, b, h = collect_all("pip")
    datas += d
    binaries += b
    hiddenimports += h
except Exception:
    pass

# TLS support and sysconfig are required by pip's network installs but
# may not be pulled in by the app's own imports.
hiddenimports += ["ssl", "sysconfig"]

a = Analysis(
    [str(run_gui)],
    pathex=[str(repo)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AI-Image-Process",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="AI-Image-Process",
)
