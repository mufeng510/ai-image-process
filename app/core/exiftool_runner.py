"""ExifTool runner (bundled, runtime-installed, or system PATH)."""
from __future__ import annotations

import subprocess
from pathlib import Path

from app.core import runtime_tools
from app.platform import CREATE_NO_WINDOW


class ExifToolRunner:
    def __init__(self, binary: Path | None = None) -> None:
        self.binary = binary or self._discover()

    @staticmethod
    def _looks_runnable(path: Path) -> bool:
        # Same rule as runtime_tools._looks_runnable (also self-heals the exec
        # bit), so a binary discovered earlier stays valid if permissions
        # change under us.
        return runtime_tools._looks_runnable(path)

    @classmethod
    def _discover(cls) -> Path | None:
        # Runtime discovery covers bundled -> runtime-installed -> system PATH,
        # and repairs a missing exec bit on unix. See app.core.runtime_tools:
        # the previous Tools-only lookup meant ExifTool could never be found
        # outside Windows, so device EXIF silently wrote nothing.
        status = runtime_tools.exiftool_status()
        return status.path

    def available(self) -> bool:
        return self.binary is not None and self._looks_runnable(self.binary)

    def run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        if not self.available():
            raise FileNotFoundError("ExifTool binary not found in app resources")
        cmd = [str(self.binary), *args]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            creationflags=CREATE_NO_WINDOW,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr or proc.stdout or "exiftool failed")
        return proc
