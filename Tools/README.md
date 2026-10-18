# Tools

Platform binaries bundled with the app.

## ExifTool

Required for device EXIF (step 6) and for the Live Photo pairing identifiers
(step 9). Without it the app still runs, but device EXIF is silently not
written and every Live Photo fails Stage-1 validation.

Two layouts, one per platform — never mix them:

| Platform | Files | Tracked? | Fetched by |
|----------|-------|----------|-----------|
| Windows | `exiftool.exe` + `exiftool_files/` | yes (in git) | — |
| Linux/macOS | `exiftool` (perl script) + `lib/` | no (gitignored) | `scripts/fetch_exiftool.sh` |

Fetch the native one before dev on unix or before packaging:

```bash
bash scripts/fetch_exiftool.sh
```

It downloads the official GitHub mirror archive (exiftool.org redirects to
SourceForge, which is not reachable from every network), verifies sha256,
writes `SOURCE-UNIX.txt`, and fails the build if the result does not run.
Unix ExifTool needs `perl` on PATH.

To upgrade, either bump `EXIFTOOL_VERSION` / `EXIFTOOL_SHA256` in
`scripts/fetch_exiftool.sh`, or replace `Tools/exiftool/` by hand (keep the
layout: the perl script and `lib/` must sit side by side).

Discovery order is bundled → runtime-installed → system PATH; see
`app/core/runtime_tools.py`. The spec bundles only the layout matching the
target platform, so a Windows PE never ends up in a Linux/macOS artifact.

## FFmpeg

`Tools/ffmpeg/` holds `ffmpeg.exe` (+ `ffprobe.exe` when available) for Live
Photo local motion + AI movie normalization. Binaries are **gitignored**
(~80MB); only `SOURCE.txt` (pinned version + license) is tracked.

Fetch locally before dev/packaging:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\fetch_ffmpeg.ps1
```

Default source is the pinned `imageio-ffmpeg` wheel from PyPI (fast,
contains ffmpeg 7.1 essentials, no ffprobe — the app runs without ffprobe).
Use `-Source Gyan` for ffmpeg+ffprobe (slower, pass `-ExpectedSha256`).
GPL notice: static builds are `--enable-gpl`; see `build/README.md` before
release.
