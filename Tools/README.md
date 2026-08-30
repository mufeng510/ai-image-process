# Tools

Platform binaries bundled with the app.

## ExifTool

`Tools/exiftool/` holds the Windows ExifTool distribution (`exiftool.exe`
+ `exiftool_files/`). It is tracked in git and packaged verbatim by
`build/ai-image-process.spec`; the app discovers it via
`app.config.paths.exiftool_candidates()`.

To upgrade, replace this directory with a fresh ExifTool Windows zip
contents (keep the same layout).
