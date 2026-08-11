from datetime import datetime

import pytest

from app.core.naming import render_filename


def test_render_basic():
    name = render_filename(
        "{original_name}_{date}",
        original_name="IMG_001",
        original_ext="png",
        when=datetime(2026, 8, 10, 15, 30, 25),
        number=1,
    )
    assert name == "IMG_001_20260810"


def test_reject_path_traversal():
    with pytest.raises(ValueError):
        render_filename(
            "../{original_name}",
            original_name="x",
            original_ext="jpg",
            when=datetime.now(),
            number=1,
        )
