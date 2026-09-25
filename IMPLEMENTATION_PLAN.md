# IMPLEMENTATION_PLAN.md
## AI Image Process Desktop Client (revised after Architect REQUEST_CHANGES)

Status: implemented through v0.2.0 feature wave (preflight + hidden image + rotate/crop + live photo + iphone import)
Date: 2026-08-10 (plan) / 2026-09-25 (v0.2.0 implementation note)
Sources: interview-complete spec; architect substitute review; process.ps1

## 0. Summary
Port DoubaoProcessor PowerShell workflow to Python + PySide6.
Preserve metadata cleanup, device EXIF, JPEG re-encode, batch output.
Windows-first v1.0; cross-platform core + CI stubs now.
Hard gate: user confirms this plan before product code.

## 0.1 v0.2.0 implementation note (this wave)

Pipeline order now (each step independently enabled; new steps default OFF):

```text
1. deduplicate → 2. rename → 3. provenance_cleanup → 4. visible_watermark
→ 5. reencode → 6. device_metadata → 7. rotate_crop → 8. hidden_image
→ 9. live_photo → 10. output_write
```

Key design conclusions from the repo audit:

- `rename` was pure-compute (`output_name`) running after `device_metadata`; it now
  runs right after `deduplicate`, with basenames fixed once in Preflight and shared
  by JPG+MOV bundles (`output_stem`). Date-template edge: `capture_dt` is not yet
  known at rename time, so date variables fall back to job-start time (documented).
- `device_metadata` writes EXIF via bundled ExifTool onto the current JPEG; pixel
  steps after it (`rotate_crop`, `hidden_image`) re-apply final tags + sRGB ICC via
  `app/core/finalize.py` so Pillow saves never drop metadata.
- `output_write` remains the only writer to the user dir; Live Photo bundles commit
  atomically (temp names + rename; rename/skip/overwrite applied to the pair as one).
- Config is now v2 with migration; `app/version.py` is the version source of truth
  (0.2.0, `pyproject.toml` aligned; README no longer caches a divergent version).
- iPhone import is a standalone tool (`app/core/iphone_import/`), honestly flagged
  `requires_user_sync=True`; Stage-2 device validation is still pending
  (see `docs/live-photo-testing.md`).

## 1. RALPLAN-DR
Principles: preserve capability as steps; core not depend on GUI; no end-user toolchain; xplat core with Windows release-block; safe temp/originals.
Drivers: parity, ordinary-user UX, delivery risk.
Options: A Python+PySide6 SELECT; B PowerShell+GUI INVALID; C Electron INVALID unless packaging fails.

## 2. Locked decisions
D1 Python + PySide6 + PyInstaller-class
D2 remove-ai-watermarks metadata mode only
D3 windows_first v1.0
D4 xplat_core_ci_stubs
D5 user plan confirm before code
D6 preserve originals; app-owned temp only
D7 PowerShell reference only

Planner defaults: Pillow+ICC (behind S2); ExifTool writer; conflict rename; UI zh-CN; workers 1 serial; pytest.

## 3. Legacy parity inventory (normative)
From DoubaoProcessor/process.ps1:
1. Folder batch input
2. remove-ai-watermarks batch --mode metadata
3. Random device from 28 profiles
4. Datetime offset minutes in [10, 10000) PowerShell semantics
5. Re-encode JPEG + sRGB ICC, quality in [96, 100) i.e. 96-99
6. ExifTool tags: Make Model LensMake LensModel DateTimeOriginal CreateDate FNumber ExposureTime ISO FocalLength Flash Software
7. Output basename.jpg
8. Legacy hazard not to copy: recursive temp deletes under package dir; PATH Magick; PATH remove-ai-watermarks

Parity lock decisions:
- Quality range 96-99 inclusive
- Software tag default remains "iOS Camera" for v1 parity (even non-Apple devices); documented quirk; settings may override later
- No Magick byte-identical requirement; structural JPEG + ICC + tags + source untouched

## 4. Architecture and dependency direction
Composition root wires:
- gui -> core.run_job
- core uses abstract BinaryResolver / ResourcePaths / Clock / Rng interfaces
- platform implements path/binary resolution only (dev, frozen _MEIPASS, portable Tools/)
- config_app loads/saves settings; core does not import gui or PySide6

Packages:
app/main_gui.py, app/main_cli.py, app/version.py
app/core/{models,pipeline,steps/*,naming,conflicts,temp_manager,device_library,exiftool_runner,errors,registry}
app/config/{schema,manager,paths,migrate}
app/gui/...
app/platform/{windows,macos,linux,runtime_paths}
tests, build, scripts, assets, Tools/exiftool (bundled; legacy DoubaoProcessor removed)
.github/workflows ci.yml release.yml

## 5. Core API contracts
### run_job
run_job(config, paths, progress_cb, cancel_token) -> JobResult

### models
- ProgressEvent: kind, job_id, file_path, step_id, index, total, message, counts
- CancelToken: is_cancelled(); cooperative cancel checked between files only in v1 (not mid-step)
- StepResult / FileResult / JobResult with success/fail lists and errors
- JobWorkspace: job_id, temp_root, incoming, work, staging
- FileRecord: source_path, current_path, original_name/ext, index, device, quality, datetime, errors

### Step interface
id, title
enabled(config) -> bool
validate(config) -> list[ValidationIssue]
run(ctx: StepContext) -> StepResult
purity notes; failure mode per file vs abort

### Step registry
register built-in steps; GUI lists from registry; future steps without GUI rewrite

### Default step order and I/O (v0.2.0 canonical — supersedes the v1 order below)

```text
1. deduplicate → 2. rename → 3. provenance_cleanup → 4. visible_watermark
→ 5. reencode → 6. device_metadata → 7. rotate_crop → 8. hidden_image
→ 9. live_photo → 10. output_write
```

- Preflight gate runs before any per-file work (dedup count → basenames →
  hidden count/safety/assignment → Live Photo resources); failure = no
  outputs, no deletions, structured error.
- `rename` is pure-compute; preflight fixes basenames once (shared JPG+MOV
  stem). Date-template variables fall back to job-start time since rename now
  precedes `device_metadata`.
- `output_write` is the only writer to the user dir; Live Photo JPG+MOV commit
  as one atomic bundle. `output_write` OFF (or skipped) commits nothing, and
  hidden images are then retained, never deleted.

### Original v1 order (historical; kept for reference — see §0.1 for deltas)
1. input_normalize: inputs -> FileRecords; filter images; recursion policy default non-recursive folders unless enabled
2. provenance_cleanup: current file -> cleaned work file (metadata mode)
3. reencode: work file -> jpeg work file + quality + icc flag
4. device_metadata: write tags onto current jpeg via ExifTool
5. rename: pure compute output basename from template (no IO)
6. output_write: only step that writes into user output dir; applies conflict policy
7. cleanup_temp: delete only under verified temp_root/job_id prefix

## 6. Config schema v2 (canonical; v1 historical below)
config_version: 2 (v1 configs auto-migrate; new steps default OFF)
ui_language: zh-CN
output: directory, use_source_directory, auto_create_directory, conflict_policy (rename|skip|overwrite), preserve_originals true, allow_overwrite_originals false
naming: preset, template, number_start, number_width
steps:
  deduplicate, provenance_cleanup, visible_watermark, reencode, device_metadata, rename, output_write (as v1)
  rotate_crop: enabled false, min_angle -2.0, max_angle 2.0
  hidden_image: enabled false, library_dir "", opacity 0.02
  live_photo: enabled false, video_source local_motion|ai_video, local_motion {duration 3s, fps 30, strength 0.06}, ai_video {provider/model/endpoint/api_key/prompt/extra/duration/timeout/retry}
ui_language: zh-CN
output: directory, use_source_directory, auto_create_directory, conflict_policy (rename|skip|overwrite), preserve_originals true, allow_overwrite_originals false
naming: preset, template, number_start, number_width
steps:
  provenance_cleanup: enabled true, mode metadata
  reencode: enabled true, format jpeg, quality_min 96, quality_max 99, apply_srgb_icc true
  device_metadata: enabled true, selection random|fixed, fixed_device_id, randomize_datetime true, offset_min_minutes 10, offset_max_minutes 10000, software_tag "iOS Camera"
  rename: enabled true
  output_write: enabled true
input: recurse_folders false, extensions [jpg jpeg png webp tim tiff bmp]
runtime: cleanup_temp_on_success true, cleanup_temp_on_startup true, worker_count 1, log_level info, portable_mode false
paths overrides optional: temp_dir, log_dir

Storage: OS app config dir; portable_mode beside exe.
Import/export/reset with migrate(config_version).

## 7. Runtime path resolution order
For ExifTool, ICC, phones.json:
1. explicit config override if set
2. portable/app Tools or assets next to executable
3. frozen bundle resources
4. dev repo Tools/exiftool / assets
Never require user PATH in release builds. No PATH Magick fallback for end users.

## 8. GUI
Main: drop zone files+folders, output dir, step toggles from registry, start/cancel, progress/counts, log, errors/retry, settings/about.
Settings: General Processing Advanced About.
PipelineWorker QThread calls run_job; signals only.
v1 cancel between files only.

## 9. Dependencies and failure ladders
remove-ai-watermarks: metadata only; prefer library API; else in-app module invocation; Apache notice; S1 size budget spike.
Pillow: re-encode+ICC; S2 parity gate; if fail: fix Pillow or document tolerance; only last resort consider bundling Magick (still no PATH).
ExifTool: bundled; arg-list subprocess; S3 tag parity gate.
pyproject + lockfile.

## 10. Safety
Allow-list deletes under app temp_root/job_* only.
Never wipe user output dir.
Never mutate sources in place.
Naming rejects path separators, abs paths, .. 
Startup cleanup only orphan job temps under app temp root.
Human-readable errors; details optional.

## 11. Packaging
Prefer onedir portable zip for Windows v1 (exe + Tools/exiftool + assets + licenses).
Installer stretch.
README: Windows-first; unsigned SmartScreen expectation possible.
Release publishes portable artifact not source-as-primary.
CI stubs macOS/Linux non-blocking; core tests run; binary gates skip cleanly.

## 12. Spikes with pass/fail
S1 provenance freeze size: measure onedir size contribution; document budget; fail if unexplained multi-hundred-MB without mitigation plan.
S2 Pillow parity: structural jpeg, icc present, quality 96-99, source untouched on fixtures; fail blocks dropping magick discussion.
S3 ExifTool: required tags present on sample outputs with Windows bundle; fail blocks device_metadata release.

## 13. Phases
1 plan consensus + user confirm
2 core contracts + steps + CLI run_job; spikes S1-S3
3 pytest green including layer import guard
4 PySide6 UI worker
5 config persistence settings
6 batch UX + manual 100-file checklist
7 Windows onedir portable build
8 GHA ci/release stubs
9 broader OS validation as available
10 docs

## 14. v1 non-behavior
No mid-file cancel
No multi-worker parallelism (worker_count fixed 1)
No visible/diffusion watermark modes
No PATH dependency for Magick/ExifTool/remove-ai-watermarks in release
Default folder recursion off

## 15. Non-goals
Cloud; end-user Python; all-OS blocking release; Electron default rewrite

## 16. Acceptance of plan
User confirms architecture, windows-first boundary, deps, contracts, and authorizes implementation or requests changes.
