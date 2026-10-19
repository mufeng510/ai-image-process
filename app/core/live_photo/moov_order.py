"""Reorder top-level MOV boxes so `moov` follows `mdat`.

A real iPhone Live Photo capture is laid out `ftyp · wide · mdat · moov`.
normalize_movie() deliberately emits moov *after* mdat for exactly that shape,
so the timed-metadata track can later be spliced in without moving any existing
video chunk. ExifTool, however, rewrites the whole movie in place when it
writes `Keys:ContentIdentifier`, and it puts moov in front of mdat - silently
undoing that design and pushing the splice onto its stco-patching path.

Moving moov behind mdat restores the intended layout. Every media sample then
sits earlier by exactly the size of moov, so each stco/co64 entry inside moov is
rebased by that delta.
"""
from __future__ import annotations

from pathlib import Path

from app.core.live_photo.timed_track import _parse_boxes, _patch_chunk_offsets


def move_moov_after_mdat(mov_path: Path) -> bool:
    """Rewrite `mov_path` with moov last. True when the file was changed.

    Best-effort and never raises: a caller that cannot reorder must still be
    able to fall back to the previous layout rather than lose the movie.
    """
    try:
        path = Path(mov_path)
        raw = bytearray(path.read_bytes())
        tops = list(_parse_boxes(bytes(raw)))
        types = [t[0] for t in tops]
        if b"moov" not in types or b"mdat" not in types:
            return False
        moov_i = types.index(b"moov")
        mdat_i = types.index(b"mdat")
        if moov_i > mdat_i:
            return False  # already moov-after-mdat
        _, moov_off, moov_size, _ = tops[moov_i]
        _, mdat_off, _mdat_size, _ = tops[mdat_i]
        # Everything after moov slides left by moov_size, so media chunk
        # offsets must drop by the same amount.
        shift = (mdat_off - moov_size) - mdat_off
        moov_bytes = bytearray(raw[moov_off:moov_off + moov_size])
        _patch_chunk_offsets(moov_bytes, shift)
        out = bytearray()
        for i, (_t, o, s, _h) in enumerate(tops):
            if i != moov_i:
                out += raw[o:o + s]
        out += moov_bytes
        path.write_bytes(bytes(out))
        return True
    except Exception:
        return False