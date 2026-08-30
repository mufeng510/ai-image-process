"""Platform path and binary helpers."""
from __future__ import annotations

import subprocess

# Windows-only creation flag. When the windowed GUI spawns a console
# executable (exiftool.exe, `python -m ...`), Windows allocates a new
# console that flashes on screen for every call; CREATE_NO_WINDOW keeps
# it hidden. The attribute does not exist on other platforms, where 0
# is accepted as a no-op.
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
