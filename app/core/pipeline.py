"""Processing pipeline orchestration."""
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
from app.core.models import (
    CancelToken,
    FileResult,
    JobResult,
    ProgressCallback,
    ProgressEvent,
    ProgressKind,
)
from app.core.registry import StepRegistry
from app.core.steps.base import StepContext
from app.core.steps.deduplicate import DeduplicateStep, deduplicate_records
from app.core.steps.device_metadata import DeviceMetadataStep
from app.core.steps.input_normalize import collect_inputs, to_records
from app.core.steps.output_write import OutputWriteStep
from app.core.steps.provenance_cleanup import ProvenanceCleanupStep
from app.core.steps.reencode import ReencodeStep
from app.core.steps.rename import RenameStep
from app.core.steps.visible_watermark import VisibleWatermarkStep
from app.core.temp_manager import TempManager


DEFAULT_STEP_ORDER = [
    "deduplicate",
    "provenance_cleanup",
    "visible_watermark",
    "reencode",
    "device_metadata",
    "rename",
    "output_write",
]


def build_default_registry() -> StepRegistry:
    reg = StepRegistry()
    for step in (
        DeduplicateStep(),
        ProvenanceCleanupStep(),
        VisibleWatermarkStep(),
        ReencodeStep(),
        DeviceMetadataStep(),
        RenameStep(),
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

    result = JobResult(job_id=job_id)
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
    resources = {
        "rng": rng,
        "output_dir": out,
        "icc_path": icc_profile_path(),
        "device_library": DeviceLibrary.load(phones_json_path()) if phones_json_path().exists() else None,
        "exiftool": ExifToolRunner(),
        "created_outputs": [],
    }

    steps = [s for s in registry.ordered(DEFAULT_STEP_ORDER) if s.enabled(config)]
    per_file_steps = [s for s in steps if s.id != "deduplicate"]
    for step in steps:
        for issue in step.validate(config):
            emit(ProgressKind.LOG, message=f"validation [{step.id}]: {issue}")

    for idx, record in enumerate(records, start=1):
        if cancel_token.is_cancelled():
            result.cancelled = True
            emit(ProgressKind.JOB_CANCELLED, message="cancelled", index=idx - 1)
            break

        emit(ProgressKind.FILE_STARTED, file_path=record.source_path, index=idx, message=record.source_path.name)
        file_result = FileResult(source_path=record.source_path, ok=True)
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
            emit(ProgressKind.FILE_SUCCEEDED, file_path=record.source_path, index=idx, message=str(record.output_path or ""))
        except Exception as exc:  # noqa: BLE001
            file_result.ok = False
            file_result.error = to_user_message(exc, str(record.source_path))
            result.failed.append(file_result)
            emit(ProgressKind.FILE_FAILED, file_path=record.source_path, index=idx, message=file_result.error)

    if not result.cancelled:
        emit(ProgressKind.JOB_FINISHED, message="done", index=len(records))

    if config.runtime.cleanup_temp_on_success and not result.cancelled:
        # keep temps on failures for debugging? plan: cleanup on success path
        if not result.failed:
            temp_mgr.cleanup_job(workspace)

    return result
