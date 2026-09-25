"""Manual Stage-2 helper: validate real iPhone reference pairs + our outputs.

Runs only when AIP_LP_REF_DIR points at an external directory containing
<stem>.jpg + <stem>.mov pairs (never commit personal photos to Git).
Otherwise skipped in normal CI.
"""
import os
from pathlib import Path

import pytest

from app.core.live_photo.validator import LivePhotoValidator

ref_dir = os.environ.get("AIP_LP_REF_DIR", "").strip()


def _pairs(root: Path):
    for jpg in sorted(root.glob("*.jpg")):
        mov = jpg.with_suffix(".mov")
        if mov.exists():
            yield jpg, mov


@pytest.mark.skipif(not ref_dir, reason="AIP_LP_REF_DIR not set (manual Stage-2 only)")
def test_reference_pairs_validate():
    root = Path(ref_dir)
    pairs = list(_pairs(root))
    assert pairs, f"no jpg+mov pairs in {root}"
    v = LivePhotoValidator()
    for jpg, mov in pairs:
        rep = v.validate(jpg, mov)
        assert rep.ok, f"{jpg.name}: {rep.errors}"
