"""Compute compatible wheel tags for the current interpreter."""

from __future__ import annotations

import packaging.tags


def compute_compatible_tags() -> list[packaging.tags.Tag]:
    """Return ordered list of compatible tags (most preferred first).

    This is simply ``list(packaging.tags.sys_tags())`` which returns tags
    ordered by interpreter preference (implementation, version, abi, platform).
    """
    return list(packaging.tags.sys_tags())