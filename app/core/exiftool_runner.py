"""Bundled ExifTool runner."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from app.config.paths import exiftool_candidates
from app.platform import CREATE_NO_WINDOW


class ExifToolRunner:
    def __init__(self, binary: Path | None = None) -> None:
        self.binary = binary or self._discover()

    @staticmethod
    def _looks_runnable(path: Path) -> bool:
        if not path.exists() or not path.is_file():
            return False
        # Avoid executing Windows PE on Linux/macOS
        if path.suffix.lower() == ".exe" and not sys.platform.startswith("win"):
            return False
        return os.access(path, os.X_OK) or path.suffix.lower() == ".exe"

    @classmethod
    def _discover(cls) -> Path | None:
        for c in exiftool_candidates():
            if cls._looks_runnable(c):
                return c
        return None

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
