# Tools

Platform binaries bundled with the app.

## ExifTool

`Tools/exiftool/` holds the Windows ExifTool distribution (`exiftool.exe`
+ `exiftool_files/`). It is tracked in git and packaged verbatim by
`build/ai-image-process.spec`; the app discovers it via
`app.config.paths.exiftool_candidates()`.

To upgrade, replace this directory with a fresh ExifTool Windows zip
contents (keep the same layout).

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
