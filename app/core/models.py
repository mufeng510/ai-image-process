
"""Core domain models and contracts."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional


class ProgressKind(str, Enum):
    JOB_STARTED = "job_started"
    FILE_STARTED = "file_started"
    STEP_STARTED = "step_started"
    STEP_FINISHED = "step_finished"
    FILE_SUCCEEDED = "file_succeeded"
    FILE_FAILED = "file_failed"
    JOB_FINISHED = "job_finished"
    JOB_CANCELLED = "job_cancelled"
    LOG = "log"


@dataclass
class ProgressEvent:
    kind: ProgressKind
    job_id: str
    message: str = ""
    file_path: Optional[Path] = None
    step_id: Optional[str] = None
    index: int = 0
    total: int = 0
    success_count: int = 0
    failure_count: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


class CancelToken:
    def __init__(self) -> None:
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled


@dataclass
class DeviceProfile:
    id: str
    make: str
    model: str
    lens: str


@dataclass
class HiddenImageAssignment:
    source_path: Path  # main image source
    hidden_path: Path  # resolved hidden library file
    hidden_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class LivePhotoBundle:
    photo_path: Path  # staging jpg
    video_path: Path  # staging mov
    asset_identifier: str
    still_image_time_ms: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class VideoGenerationResult:
    video_path: Path
    duration_seconds: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class FileRecord:
    source_path: Path
    current_path: Path
    original_name: str
    original_ext: str
    index: int
    device: Optional[DeviceProfile] = None
    quality: Optional[int] = None
    capture_dt: Optional[Any] = None  # datetime
    output_name: Optional[str] = None
    output_stem: Optional[str] = None  # basename shared by jpg+mov bundle
    output_path: Optional[Path] = None
    output_paths: list[Path] = field(default_factory=list)  # all committed outputs (bundle)
    assigned_hidden_image: Optional[Path] = None
    hidden_metadata_source: dict[str, Any] = field(default_factory=dict)
    live_photo_bundle: Optional["LivePhotoBundle"] = None
    hidden_cleanup_failed: Optional[str] = None
    errors: list[str] = field(default_factory=list)

    def with_current(self, path: Path) -> "FileRecord":
        return replace(self, current_path=path)


@dataclass
class JobWorkspace:
    job_id: str
    temp_root: Path
    incoming: Path
    work: Path
    staging: Path


@dataclass
class StepResult:
    step_id: str
    ok: bool
    message: str = ""
    error: Optional[str] = None


@dataclass
class FileResult:
    source_path: Path
    ok: bool
    output_path: Optional[Path] = None
    error: Optional[str] = None
    step_results: list[StepResult] = field(default_factory=list)


@dataclass
class JobResult:
    job_id: str
    success: list[FileResult] = field(default_factory=list)
    failed: list[FileResult] = field(default_factory=list)
    cancelled: bool = False
    preflight_failed: bool = False
    preflight_error: Optional[str] = None
    preflight_extra: dict[str, Any] = field(default_factory=dict)

    @property
    def success_count(self) -> int:
        return len(self.success)

    @property
    def failure_count(self) -> int:
        return len(self.failed)


ProgressCallback = Callable[[ProgressEvent], None]
