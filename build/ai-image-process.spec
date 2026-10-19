# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir spec for AI Image Process.

Build from repo root:
  .venv/bin/pyinstaller build/ai-image-process.spec
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

import sys

block_cipher = None

# SPECPATH is the directory containing this spec file (build/)
_spec_dir = Path(SPECPATH).resolve()
if _spec_dir.is_file():
    _spec_dir = _spec_dir.parent
repo = _spec_dir.parent
# One entry script, two personalities. PyInstaller gives every EXE the same
# a.scripts, so the split has to happen at runtime on argv[0] -- see
# scripts/run_app.py. (Building a second Analysis + COLLECT would duplicate the
# whole dependency tree, ExifTool and FFmpeg included, for nothing.)
run_app = repo / "scripts" / "run_app.py"
if not run_app.exists():
    raise SystemExit(f"packaged entry not found: {run_app}")

datas = [
    (str(repo / "assets" / "devices" / "phones.json"), "assets/devices"),
    (str(repo / "assets" / "icc" / "sRGB-IEC61966-2.1.icc"), "assets/icc"),
]

# App icons: runtime window icon (PNG) + EXE icon (ICO/ICNS).
# Best-effort: packaging must not fail when absent.
_icons_dir = repo / "assets" / "icons"
for _name in ("icon.png", "icon-256.png", "icon.ico", "icon.icns"):
    _p = _icons_dir / _name
    if _p.is_file():
        datas.append((str(_p), "assets/icons"))

_icon_file = None
if sys.platform == "darwin":
    _icns = _icons_dir / "icon.icns"
    if _icns.is_file():
        _icon_file = str(_icns)
if _icon_file is None:
    _ico = _icons_dir / "icon.ico"
    if _ico.is_file():
        _icon_file = str(_ico)

# ExifTool: ship only the distribution that matches the target platform.
# The repo tracks the Windows one (exiftool.exe + exiftool_files/); unix builds
# get a native perl script + lib/ fetched by scripts/fetch_exiftool.sh. Mixing
# them wastes ~11 MB and, worse, means the app cannot find a usable ExifTool at
# all on macOS/Linux — device EXIF then silently writes nothing.
def _collect_tree(src: Path, dest: str) -> list[tuple[str, str]]:
    """Map every FILE under `src` into `dest`, preserving the tree.

    Two PyInstaller quirks bite here:
      - a (dir, dest) entry copies the directory's *contents* into dest, so
        passing `lib` flattens `lib/Image/ExifTool.pm`;
      - a (file, dest) entry appends the file's basename to dest, so dest
        must be the file's PARENT directory, never its full target path.
    Walking files ourselves avoids both.
    """
    out = []
    for path in sorted(src.rglob("*")):
        if not path.is_file():
            continue
        rel_dir = path.relative_to(src).parent.as_posix()
        target = dest if rel_dir in ("", ".") else f"{dest}/{rel_dir}"
        out.append((str(path), target))
    return out


exif_dir = repo / "Tools" / "exiftool"
_datas_exif = []
if sys.platform == "win32":
    # exiftool.exe + exiftool_files/ (the tracked Windows distribution)
    if (exif_dir / "exiftool.exe").is_file():
        _datas_exif.append((str(exif_dir / "exiftool.exe"), "Tools/exiftool"))
    if (exif_dir / "exiftool_files").is_dir():
        _datas_exif.extend(_collect_tree(exif_dir / "exiftool_files",
                                         "Tools/exiftool/exiftool_files"))
else:
    # fetch_exiftool.sh produces: exiftool (sh wrapper, execs Tools/perl/bin/perl
    # or the host perl), exiftool.pl (the actual perl script) and lib/ (its
    # modules). Shipping the wrapper without the script -- or the script without
    # lib/ -- produces an artifact that looks fine in a namelist check and is
    # dead on arrival at runtime, so assert the trio is really there.
    if (exif_dir / "exiftool").is_file():
        _datas_exif.append((str(exif_dir / "exiftool"), "Tools/exiftool"))
    if (exif_dir / "exiftool.pl").is_file():
        _datas_exif.append((str(exif_dir / "exiftool.pl"), "Tools/exiftool"))
    elif (exif_dir / "exiftool").is_file():
        raise SystemExit(
            "[spec] Tools/exiftool/exiftool exists but exiftool.pl does not; "
            "re-run scripts/fetch_exiftool.sh"
        )
    if (exif_dir / "lib").is_dir():
        # The perl script loads modules from ./lib/Image/..., so every level of
        # that tree has to survive packaging.
        _datas_exif.extend(_collect_tree(exif_dir / "lib", "Tools/exiftool/lib"))
if _datas_exif:
    # Per-file, not the whole directory: shipping both layouts would add
    # ~11MB of unusable foreign binaries to every artifact.
    datas.extend(_datas_exif)
else:
    print("[spec] WARNING: no ExifTool for this platform; device EXIF and "
          "Live Photo will not work. Run scripts/fetch_exiftool.sh.")

# Optional FFmpeg for Live Photo local motion (see build/README.md for
# licensing notes). Best-effort: packaging must not fail when absent.
ffmpeg_dir = repo / "Tools" / "ffmpeg"
if ffmpeg_dir.exists():
    datas.append((str(ffmpeg_dir), "Tools/ffmpeg"))

# A unix ExifTool is a perl script, so the interpreter is part of the product,
# not a host prerequisite. Tools/exiftool/exiftool is a sh wrapper that execs
# Tools/perl/bin/perl; without this tree it silently falls back to the host's
# perl and every artifact is at the mercy of whether the user has one.
perl_dir = repo / "Tools" / "perl"
if sys.platform != "win32" and (perl_dir / "bin" / "perl").is_file():
    # datas, not binaries: PyInstaller preserves the executable bit for data
    # entries, and the wrapper execs this by absolute path. Adding them to both
    # would duplicate every file in the artifact.
    _perl_files = _collect_tree(perl_dir, "Tools/perl")
    datas.extend(_perl_files)
    print(f"[spec] bundled {len(_perl_files)} perl files")
elif sys.platform != "win32":
    print("[spec] WARNING: Tools/perl missing (run scripts/fetch_perl.sh); "
          "the unix build will need a host perl")

hiddenimports = [
    "app",
    "app.main",
    "app.main_cli",
    "app.gui",
    "app.gui.app",
    "app.gui.icons",
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
    "app.core.live_photo.timed_track",
    "app.core.live_photo.providers",
    "app.core.live_photo.providers.base",
    "app.core.live_photo.providers.local_motion",
    "app.core.live_photo.providers.ai_video",
    "app.core.iphone_import",
    "app.core.iphone_import.base",
    "app.core.iphone_import.i4tools",
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
    [str(run_app)],
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
    icon=_icon_file,
)

# Console sibling of the GUI binary. Both share this one COLLECT, so the two
# entries cost a second bootloader + PYZ (~7 MB) and nothing else: every
# dependency, the bundled ExifTool and FFmpeg are read from the shared
# _internal/ tree.
#
# console=True is not cosmetic. On Windows a GUI-subsystem binary holds no
# console handle, so a parent cmd/PowerShell (or an agent's subprocess call)
# cannot capture stdout at all. Linux/macOS ignore the flag entirely -- keeping
# both entries identical across platforms is what makes the artifact layout
# predictable and lets one CI assertion cover all three jobs.
exe_cli = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AI-Image-Process-CLI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    exe_cli,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="AI-Image-Process",
)