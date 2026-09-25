"""Processing pipeline orchestration (with preflight + bundle-aware commit)."""
from __future__ import annotations

import random
import uuid
from pathlib import Path
from typing import Sequence

from app.config.paths import default_temp_dir, icc_profile_path, phones_json_path
from app.config.schema import AppConfig
from app.core.device_library import DeviceLibrary
from app.core.errors import to_user_message
from app.core.exiftool_runner import ExifToolRunner
from app.core.hidden_images import delete_hidden_image
from app.core.models import (
    CancelToken,
    FileResult,
    JobResult,
    ProgressCallback,
    ProgressEvent,
    ProgressKind,
    StepResult,
)
from app.core.registry import StepRegistry
from app.core.steps.base import StepContext
from app.core.steps.deduplicate import DeduplicateStep, deduplicate_records
from app.core.steps.device_metadata import DeviceMetadataStep
from app.core.steps.hidden_image import HiddenImageStep
from app.core.steps.input_normalize import collect_inputs, to_records
from app.core.steps.live_photo import LivePhotoStep
from app.core.steps.output_write import OutputWriteStep
from app.core.steps.provenance_cleanup import ProvenanceCleanupStep
from app.core.steps.reencode import ReencodeStep
from app.core.steps.rename import RenameStep
from app.core.steps.rotate_crop import RotateCropStep
from app.core.steps.visible_watermark import VisibleWatermarkStep
from app.core.temp_manager import TempManager


DEFAULT_STEP_ORDER = [
    "deduplicate",
    "rename",
    "provenance_cleanup",
    "visible_watermark",
    "reencode",
    "device_metadata",
    "rotate_crop",
    "hidden_image",
    "live_photo",
    "output_write",
]


def build_default_registry() -> StepRegistry:
    reg = StepRegistry()
    for step in (
        DeduplicateStep(),
        RenameStep(),
        ProvenanceCleanupStep(),
        VisibleWatermarkStep(),
        ReencodeStep(),
        DeviceMetadataStep(),
        RotateCropStep(),
        HiddenImageStep(),
        LivePhotoStep(),
        OutputWriteStep(),
    ):
        reg.register(step)
    return reg


def run_job(
    config: AppConfig,
    inputs: Sequence[Path | str],
    output_dir: Path | str | None = None,
    *,
    progress_cb: ProgressCallback | None = None,
    cancel_token: CancelToken | None = None,
    seed: int | None = None,
    registry: StepRegistry | None = None,
    temp_base: Path | None = None,
) -> JobResult:
    """Run a full processing job.

    Cancel is cooperative and checked between files only (v1).
    Preflight runs before any output/deletion; failure returns
    JobResult(preflight_failed=True) with no side effects.
    """
    cancel_token = cancel_token or CancelToken()
    registry = registry or build_default_registry()
    job_id = uuid.uuid4().hex[:12]
    portable = config.runtime.portable_mode
    temp_base = Path(temp_base) if temp_base else (
        Path(config.paths.temp_dir) if config.paths.temp_dir else default_temp_dir(portable)
    )
    temp_mgr = TempManager(temp_base)
    if config.runtime.cleanup_temp_on_startup:
        temp_mgr.cleanup_orphans()

    workspace = temp_mgr.create_job_workspace(job_id)
    files = collect_inputs([Path(p) for p in inputs], config)
    records = to_records(files)

    result = JobResult(job_id=job_id)

    def emit(kind: ProgressKind, **kwargs) -> None:
        if progress_cb:
            progress_cb(
                ProgressEvent(
                    kind=kind,
                    job_id=job_id,
                    total=len(records),
                    success_count=len(result.success),
                    failure_count=len(result.failed),
                    **kwargs,
                )
            )

    emit(ProgressKind.JOB_STARTED, message=f"job {job_id} started", index=0)

    if config.steps.deduplicate.enabled:
        records, dup_count = deduplicate_records(records, config.steps.deduplicate.algorithm)
        if dup_count > 0:
            emit(ProgressKind.LOG, message=f"Deduplication: removed {dup_count} duplicate file(s)")

    if not records:
        emit(ProgressKind.JOB_FINISHED, message="no input files")
        if config.runtime.cleanup_temp_on_success:
            temp_mgr.cleanup_job(workspace)
        return result

    # resolve output dir
    if output_dir is not None:
        out = Path(output_dir)
    elif config.output.use_source_directory and records:
        out = records[0].source_path.parent
    elif config.output.directory:
        out = Path(config.output.directory)
    else:
        out = Path.cwd() / "output"

    rng = random.Random(seed)

    # ---- Preflight (no IO side effects: no outputs, no deletions) ----
    from app.core.preflight import run_preflight

    preflight = run_preflight(
        config, [Path(p) for p in inputs], records, out, rng,
        emit=lambda m: emit(ProgressKind.LOG, message=m),
    )
    if not preflight.ok:
        result.preflight_failed = True
        result.preflight_error = preflight.error
        result.preflight_extra = preflight.extra
        emit(ProgressKind.LOG, message=f"[Preflight] FAILED: {preflight.error}")
        emit(ProgressKind.JOB_FINISHED, message="preflight failed")
        if config.runtime.cleanup_temp_on_success:
            try:
                temp_mgr.cleanup_job(workspace)
            except Exception:
                pass
        return result
    # Apply preflight decisions: shared basenames + hidden assignments.
    for rec in records:
        stem = preflight.basenames.get(str(rec.source_path))
        if stem:
            rec.output_stem = stem
            rec.output_name = f"{stem}.jpg"
        hpath = preflight.hidden_mapping.get(str(rec.source_path))
        if hpath is not None:
            rec.assigned_hidden_image = hpath
            rec.hidden_metadata_source = dict(preflight.hidden_metadata.get(str(rec.source_path), {}) or {})
    emit(ProgressKind.LOG, message="[Preflight] OK")

    resources = {
        "rng": rng,
        "output_dir": out,
        "icc_path": icc_profile_path(),
        "device_library": DeviceLibrary.load(phones_json_path()) if phones_json_path().exists() else None,
        "exiftool": ExifToolRunner(),
        "created_outputs": [],
        "hidden_mapping": {str(k): v for k, v in preflight.hidden_mapping.items()},
        "hidden_metadata": {str(k): v for k, v in preflight.hidden_metadata.items()},
        "hidden_library_dir": (config.steps.hidden_image.library_dir or ""),
    }

    steps = [s for s in registry.ordered(DEFAULT_STEP_ORDER) if s.enabled(config)]
    per_file_steps = [s for s in steps if s.id != "deduplicate"]
    for step in steps:
        for issue in step.validate(config):
            emit(ProgressKind.LOG, message=f"validation [{step.id}]: {issue}")

    hidden_lib = (config.steps.hidden_image.library_dir or "").strip()
    hidden_on = bool(config.steps.hidden_image.enabled)

    for idx, record in enumerate(records, start=1):
        if cancel_token.is_cancelled():
            result.cancelled = True
            emit(ProgressKind.JOB_CANCELLED, message="cancelled", index=idx - 1)
            break

        emit(ProgressKind.FILE_STARTED, file_path=record.source_path, index=idx, message=record.source_path.name)
        file_result = FileResult(source_path=record.source_path, ok=True)
        file_ok = False
        try:
            # copy source into workspace incoming first
            incoming = workspace.incoming / f"{idx:04d}_{record.source_path.name}"
            incoming.write_bytes(record.source_path.read_bytes())
            record.current_path = incoming

            for step in per_file_steps:
                emit(ProgressKind.STEP_STARTED, file_path=record.source_path, step_id=step.id, index=idx)
                step_res = step.run(StepContext(config=config, workspace=workspace, record=record, resources=resources))
                file_result.step_results.append(step_res)
                emit(
                    ProgressKind.STEP_FINISHED,
                    file_path=record.source_path,
                    step_id=step.id,
                    index=idx,
                    message=step_res.message or (step_res.error or ""),
                )
                if not step_res.ok:
                    raise RuntimeError(step_res.error or "step failed")
            file_result.output_path = record.output_path
            result.success.append(file_result)
            file_ok = True
            emit(ProgressKind.FILE_SUCCEEDED, file_path=record.source_path, index=idx, message=str(record.output_path or ""))
        except Exception as exc:  # noqa: BLE001
            file_result.ok = False
            file_result.error = to_user_message(exc, str(record.source_path))
            result.failed.append(file_result)
            emit(ProgressKind.FILE_FAILED, file_path=record.source_path, index=idx, message=file_result.error)

        # Hidden-image lifecycle: delete ONLY after all enabled steps +
        # Live Photo + final commit succeeded AND outputs exist on disk.
        # output_write OFF (or skipped bundle) commits nothing -> retain.
        # Failures/cancel retain it. A failed reservation is never
        # reassigned within this batch.
        committed = [p for p in (getattr(record, "output_paths", None) or [])
                     if p is not None]
        outputs_on_disk = bool(file_ok and committed and all(
            Path(p).exists() for p in committed))
        if hidden_on and outputs_on_disk and record.assigned_hidden_image is not None:
            try:
                delete_hidden_image(Path(record.assigned_hidden_image), Path(hidden_lib))
                emit(ProgressKind.LOG, file_path=record.source_path, index=idx,
                     message=f"[HiddenImage] cleaned {Path(record.assigned_hidden_image).name}")
            except Exception as exc:  # noqa: BLE001
                record.hidden_cleanup_failed = str(exc)
                file_result.step_results.append(
                    StepResult(
                        "hidden_image_cleanup", True,
                        message=f"处理成功，但隐藏素材清理失败：{exc}"))
                emit(ProgressKind.LOG, file_path=record.source_path, index=idx,
                     message=f"[HiddenImage] cleanup failed (outputs kept): {exc}")
        elif hidden_on and file_ok and record.assigned_hidden_image is not None:
            emit(ProgressKind.LOG, file_path=record.source_path, index=idx,
                 message="[HiddenImage] retained (no committed output; output step off or skipped)")

    if not result.cancelled:
        emit(ProgressKind.JOB_FINISHED, message="done", index=len(records))

    # Guarantee: Live Photo OFF produces no .mov anywhere in outputs.
    # (Intermediate staging is under temp and cleaned below.)
    if config.runtime.cleanup_temp_on_success and not result.cancelled:
        # keep temps on failures for debugging? plan: cleanup on success path
        if not result.failed:
            temp_mgr.cleanup_job(workspace)

    return result
