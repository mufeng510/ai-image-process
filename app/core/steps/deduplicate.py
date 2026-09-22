"""File deduplication step using content hash (MD5)."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from app.config.schema import AppConfig
from app.core.models import FileRecord, StepResult
from app.core.steps.base import Step, StepContext


class DeduplicateStep(Step):
    id = "deduplicate"
    title = "文件去重"

    def enabled(self, config: AppConfig) -> bool:
        return bool(config.steps.deduplicate.enabled)

    def run(self, ctx: StepContext) -> StepResult:
        # This step is run once per job before the per-file loop
        # The actual deduplication happens in the pipeline's run_job function
        # This run() method is kept for interface compliance but does nothing per-file
        return StepResult(self.id, True, message="deduplication handled at job level")


def compute_file_hash(file_path: Path, algorithm: str = "md5") -> str:
    """Compute hash of file content."""
    hasher = hashlib.new(algorithm)
    with file_path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def deduplicate_records(records: list[FileRecord], algorithm: str = "md5") -> tuple[list[FileRecord], int]:
    """
    Remove duplicate files based on content hash.

    Returns:
        Tuple of (deduplicated records, count of duplicates removed)
    """
    seen_hashes: dict[str, FileRecord] = {}
    unique_records: list[FileRecord] = []
    duplicates_removed = 0

    for record in records:
        try:
            file_hash = compute_file_hash(record.source_path, algorithm)
        except Exception:
            # If we can't read the file, keep it (fail later in pipeline)
            unique_records.append(record)
            continue

        if file_hash not in seen_hashes:
            seen_hashes[file_hash] = record
            unique_records.append(record)
        else:
            duplicates_removed += 1
            # Optionally log which file was removed
            # logger.info(f"Removed duplicate: {record.source_path} (same as {seen_hashes[file_hash].source_path})")

    # Re-index the records
    for i, record in enumerate(unique_records, start=1):
        record.index = i

    return unique_records, duplicates_removed