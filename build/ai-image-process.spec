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

# Optional FFmpeg for Live Photo local motion (see build/README.md for
# licensing notes). Best-effort: packaging must not fail when absent.
ffmpeg_dir = repo / "Tools" / "ffmpeg"
if ffmpeg_dir.exists():
    datas.append((str(ffmpeg_dir), "Tools/ffmpeg"))

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
    "app.core.preflight",
    "app.core.hidden_images",
    "app.core.image_metadata",
    "app.core.finalize",
    "app.core.ffmpeg_resolver",
    "app.core.live_photo",
    "app.core.live_photo.builder",
    "app.core.live_photo.validator",
    "app.core.live_photo.metadata",
    "app.core.live_photo.movie",
    "app.core.live_photo.models",
    "app.core.live_photo.providers",
    "app.core.live_photo.providers.base",
    "app.core.live_photo.providers.local_motion",
    "app.core.live_photo.providers.ai_video",
    "app.core.iphone_import",
    "app.core.iphone_import.base",
    "app.core.iphone_import.manual_sync",
    "app.core.iphone_import.i4tools",
    "app.core.iphone_import.apple_devices",
    "app.core.iphone_import.itunes",
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

# ssl is required for urllib HTTPS (PyPI wheel downloads); sysconfig keeps
# packaging.tags happy. The wheel installer needs no bundled pip.
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