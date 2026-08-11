
"""Safe app-owned temporary directories."""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from app.core.models import JobWorkspace


class TempManager:
    def __init__(self, base_temp: Path) -> None:
        self.base_temp = base_temp.resolve()
        self.base_temp.mkdir(parents=True, exist_ok=True)

    def create_job_workspace(self, job_id: str | None = None) -> JobWorkspace:
        jid = job_id or uuid.uuid4().hex
        root = (self.base_temp / f"job_{jid}").resolve()
        self._ensure_under_base(root)
        incoming = root / "incoming"
        work = root / "work"
        staging = root / "staging"
        for p in (incoming, work, staging):
            p.mkdir(parents=True, exist_ok=True)
        return JobWorkspace(job_id=jid, temp_root=root, incoming=incoming, work=work, staging=staging)

    def cleanup_job(self, workspace: JobWorkspace) -> None:
        root = workspace.temp_root.resolve()
        self._ensure_under_base(root)
        if root.exists():
            shutil.rmtree(root)

    def cleanup_orphans(self) -> int:
        removed = 0
        if not self.base_temp.exists():
            return 0
        for child in self.base_temp.iterdir():
            if child.is_dir() and child.name.startswith("job_"):
                path = child.resolve()
                self._ensure_under_base(path)
                shutil.rmtree(path, ignore_errors=True)
                removed += 1
        return removed

    def _ensure_under_base(self, path: Path) -> None:
        try:
            path.relative_to(self.base_temp)
        except ValueError as exc:
            raise PermissionError(f"refusing unsafe temp path outside base: {path}") from exc
