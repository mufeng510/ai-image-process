"""Hand-built QuickTime timed-metadata track carrying still-image-time.

Why this exists (no macOS APIs, no new binaries):
- iOS / iTools pair a Live Photo by (1) matching ContentIdentifier UUID on the
  still (MakerNote 0x0011) and the movie (moov/meta
  com.apple.quicktime.content.identifier), plus (2) a timed-metadata track
  carrying com.apple.quicktime.still-image-time. Without (2) the pair imports
  as a plain photo, or import is rejected outright.
- Neither ffmpeg nor ExifTool can author that timed track (ExifTool marks
  still-image-time non-writable; ffmpeg mangles the mebx sample description),
  so we splice one in with pure-Python BMFF surgery.

Layout (mirrors real iPhone captures byte-for-byte in structure; verified
with bundled ExifTool as oracle - `exiftool -G -s -ee` must report
`StillImageTime` after splicing):
- New trak (handler 'meta'): tkhd(flags 0xf) + edts(empty edit) + tref(cdsc
  -> video track) + mdia(mdhd timescale 600 duration 1, hdlr, minf(
  gmhd/gmin, dinf/dref, stbl(stsd/mebx entry [keys{keyd,dtyp}, btrt],
  stts, stsc, stsz, stco))).
- keys box carries entries IMMEDIATELY (no version/flags+count header -
  exactly like real captures): local ID 1 -> 'still-image-time',
  dtyp ns=0/code=65 (int8s).
- One timed sample appended to mdat: [size=9][localID=1][0xFF(-1)];
  per Apple convention the value is always -1 and the still moment is the
  sample's own timestamp (0 = anchor/first frame, matching our pipeline).
- normalize_movie() emits moov AFTER mdat (no faststart) precisely so this
  splice never moves existing video chunks (no stco patching in practice);
  a generic stco/co64 delta patch is still applied when moov precedes mdat.
"""
from __future__ import annotations

import struct
from pathlib import Path

META_TIMESCALE = 600
STILL_KEY = b"com.apple.quicktime.still-image-time"
LOCAL_ID = 1
SAMPLE_VALUE = b"\xff"  # int8s -1, Apple convention (time comes from SampleTime)


def _box(typ: bytes, payload: bytes) -> bytes:
    assert len(typ) == 4
    return struct.pack(">I", 8 + len(payload)) + typ + payload


def _parse_boxes(buf: bytes, base: int = 0):
    """Yield (type, box_off, size, header_len) for direct children in buf."""
    off = 0
    n = len(buf)
    while off + 8 <= n:
        size = struct.unpack(">I", buf[off:off + 4])[0]
        typ = buf[off + 4:off + 8]
        hlen = 8
        if size == 1:
            if off + 16 > n:
                return
            size = struct.unpack(">Q", buf[off + 8:off + 16])[0]
            hlen = 16
        elif size == 0:
            size = n - off
        if size < hlen or off + size > n:
            return
        yield typ, base + off, size, hlen
        off += size


def _build_keys_box() -> bytes:
    keyd_val = b"mdta" + STILL_KEY
    keyd = _box(b"keyd", keyd_val)
    dtyp_val = struct.pack(">II", 0, 65)  # namespace 0 + type code 65 (int8s)
    dtyp = _box(b"dtyp", dtyp_val)
    entry = struct.pack(">I", LOCAL_ID) + keyd + dtyp
    # Entry layout is [size:4][localID:4][keyd][dtyp] - the local ID is NOT a
    # box header, so size is 4 + len(inner) (same pitfall as timed samples).
    entry = struct.pack(">I", 4 + len(entry)) + entry
    # NOTE: no version/flags+count header - real iPhone captures carry keys
    # entries immediately (ExifTool tolerates both layouts).
    return _box(b"keys", entry)


def _build_mebx_entry() -> bytes:
    keys = _build_keys_box()
    btrt = _box(b"btrt", b"\x00" * 12)
    payload = b"\x00" * 6 + struct.pack(">H", 1) + b"\x00" * 8 + keys + btrt
    return struct.pack(">I", 8 + len(payload)) + b"mebx" + payload


def _build_sample() -> bytes:
    # Timed sample layout is [size:4][localID:4][value] - the local ID doubles
    # as the box "type", so total size is 4 + len(body), NOT 8 + len(body).
    body = struct.pack(">I", LOCAL_ID) + SAMPLE_VALUE
    return struct.pack(">I", 4 + len(body)) + body


def _build_tref(video_track_id: int) -> bytes:
    """Track reference: this metadata describes the video track (cdsc)."""
    return _box(b"tref", _box(b"cdsc", struct.pack(">I", video_track_id)))


def _build_edts(movie_duration: int) -> bytes:
    """Edit list mirroring real captures: empty edit then 1 unit of media."""
    elst = (struct.pack(">II", 0, 2)
            + struct.pack(">IiI", max(0, movie_duration - 1), -1, 0x00010000)
            + struct.pack(">IiI", 1, 0, 0x00010000))
    return _box(b"edts", _box(b"elst", elst))


def _build_trak(track_id: int, movie_duration: int,
                sample_offset: int, video_track_id: int) -> bytes:
    # tkhd v0, flags 0xf (enabled/in-movie/in-preview/poster - real captures
    # mark even metadata tracks enabled; flags=0 risks the track being
    # skipped by strict Apple parsers).
    tkhd = struct.pack(
        ">IIIII", 0x00000f, 0, 0, track_id, 0,
    ) + struct.pack(">I", movie_duration) + b"\x00" * 8
    tkhd += struct.pack(">HHH", 0, 0, 0) + struct.pack(">h", 0) + b"\x00" * 2
    # Identity matrix: 9 x int32 fixed-point (16.16 for scale, 2.30 for w).
    tkhd += struct.pack(">lllllllll",
                        0x00010000, 0, 0,
                        0, 0x00010000, 0,
                        0, 0, 0x40000000)
    tkhd += struct.pack(">II", 0, 0)
    tkhd_box = _box(b"tkhd", tkhd)
    # mdhd v0: single-sample track, media duration 1 unit at 600 Hz
    # (mirrors real captures; presentation span comes from edts).
    mdhd = (struct.pack(">I", 0) + struct.pack(">I", 0)
            + struct.pack(">I", 0) + struct.pack(">I", META_TIMESCALE)
            + struct.pack(">I", 1) + struct.pack(">H", 0)
            + struct.pack(">H", 0))
    assert len(mdhd) == 24
    mdhd_box = _box(b"mdhd", mdhd)
    # hdlr name is a Pascal string in real captures ('Core Media Metadata').
    hdlr_name = bytes((len(b"Core Media Metadata"),)) + b"Core Media Metadata"
    hdlr = (struct.pack(">I", 0) + struct.pack(">I", 0) + b"meta"
            + b"\x00" * 12 + hdlr_name)
    hdlr_box = _box(b"hdlr", hdlr)
    # minf: gmhd/gmin + dinf/dref + stbl
    gmin = _box(b"gmin", struct.pack(">I", 0) + b"\x00" * 8)
    gmhd = _box(b"gmhd", gmin)
    url = _box(b"url ", struct.pack(">I", 1))
    dref = _box(b"dref", struct.pack(">I", 0) + struct.pack(">I", 1) + url)
    dinf = _box(b"dinf", dref)
    # stbl
    stsd = _box(b"stsd", struct.pack(">II", 0, 1) + _build_mebx_entry())
    stts = _box(b"stts", struct.pack(">II", 0, 1)
                + struct.pack(">II", 1, 1))
    stsc = _box(b"stsc", struct.pack(">II", 0, 1)
                + struct.pack(">III", 1, 1, 1))
    sample = _build_sample()
    stsz = _box(b"stsz", struct.pack(">III", 0, 0, 1)
                + struct.pack(">I", len(sample)))
    stco = _box(b"stco", struct.pack(">II", 0, 1)
                + struct.pack(">I", sample_offset))
    stbl = _box(b"stbl", stsd + stts + stsc + stsz + stco)
    minf = _box(b"minf", gmhd + dinf + stbl)
    mdia = _box(b"mdia", mdhd_box + hdlr_box + minf)
    trak = _box(b"trak", (tkhd_box + _build_edts(movie_duration)
                          + _build_tref(video_track_id) + mdia))
    return trak, sample


def _read_mvhd(moov_payload: bytes):
    """Return (timescale, duration, next_track_id, mvhd_end_rel, track_ids)."""
    timescale = duration = 0
    next_id = 0
    track_ids: list[int] = []
    mvhd_off = mvhd_size = 0
    for typ, off, size, hlen in _parse_boxes(moov_payload):
        body = moov_payload[off:off + size][hlen:]
        if typ == b"mvhd":
            mvhd_off, mvhd_size = off, size
            ver = body[0]
            if ver == 0 and len(body) >= 20:
                timescale = struct.unpack(">I", body[12:16])[0]
                duration = struct.unpack(">I", body[16:20])[0]
            elif ver == 1 and len(body) >= 32:
                timescale = struct.unpack(">I", body[20:24])[0]
                duration = struct.unpack(">Q", body[24:32])[0]
            if len(body) >= 4:
                next_id = struct.unpack(">I", body[-4:])[0]
        elif typ == b"trak":
            for t2, o2, s2, h2 in _parse_boxes(body):
                if t2 == b"tkhd":
                    tb = body[o2:o2 + s2][h2:]
                    if not tb:
                        continue
                    if tb[0] == 0 and len(tb) >= 16:
                        track_ids.append(struct.unpack(">I", tb[12:16])[0])
                    elif tb[0] == 1 and len(tb) >= 24:
                        track_ids.append(struct.unpack(">I", tb[20:24])[0])
    return timescale, duration, next_id, mvhd_off, mvhd_size, track_ids


def _patch_chunk_offsets(moov: bytearray, delta: int) -> None:
    """Shift every stco/co64 entry inside moov by delta (moov-before-mdat)."""
    containers = {b"moov", b"trak", b"mdia", b"minf", b"stbl"}

    def walk(buf: bytearray, start: int, end: int) -> None:
        off = start
        while off + 8 <= end:
            size = struct.unpack(">I", buf[off:off + 4])[0]
            typ = bytes(buf[off + 4:off + 8])
            hlen = 8
            if size == 1:
                if off + 16 > end:
                    return
                size = struct.unpack(">Q", buf[off + 8:off + 16])[0]
                hlen = 16
            elif size == 0:
                size = end - off
            if size < hlen or off + size > end:
                return
            if typ == b"stco" and size >= 16:
                count = struct.unpack(">I", buf[off + 12:off + 16])[0]
                for i in range(count):
                    p = off + 16 + i * 4
                    if p + 4 > off + size:
                        break
                    v = struct.unpack(">I", buf[p:p + 4])[0]
                    struct.pack_into(">I", buf, p, v + delta)
            elif typ == b"co64" and size >= 16:
                count = struct.unpack(">I", buf[off + 12:off + 16])[0]
                for i in range(count):
                    p = off + 16 + i * 8
                    if p + 8 > off + size:
                        break
                    v = struct.unpack(">Q", buf[p:p + 8])[0]
                    struct.pack_into(">Q", buf, p, v + delta)
            elif typ in containers:
                walk(buf, off + hlen, off + size)
            off += size

    walk(moov, 0, len(moov))


def add_still_image_time_track(mov_path: Path, still_ms: int = 0) -> bool:
    """Splice a mebx timed-metadata track into MOV. Never raises.

    Only still-at-0 is supported (our pipeline's anchor frame is always the
    first frame; callers pass still_time_ms=0). Returns True on success.
    """
    try:
        if int(still_ms) != 0:
            return False
        raw = bytearray(Path(mov_path).read_bytes())
        tops = list(_parse_boxes(bytes(raw)))
        mdat = next((t for t in tops if t[0] == b"mdat"), None)
        moov = next((t for t in tops if t[0] == b"moov"), None)
        if mdat is None or moov is None:
            return False
        _, mdat_off, mdat_size, mdat_hlen = mdat
        _, moov_off, moov_size, _ = moov
        moov_payload = bytes(raw[moov_off:moov_off + moov_size])[8:]
        ts, dur, next_id, _, _, track_ids = _read_mvhd(moov_payload)
        if not ts or dur == 0:
            return False
        new_id = (max(track_ids) if track_ids else 0) + 1
        if new_id < 2:
            new_id = 2
        video_ref = 1 if 1 in track_ids else (min(track_ids) if track_ids else 1)
        sample_off = mdat_off + mdat_size  # append at end of mdat data
        trak, sample = _build_trak(new_id, dur, sample_off, video_ref)
        # 1) grow mdat with the timed sample
        mdat_end = mdat_off + mdat_size
        raw[mdat_end:mdat_end] = sample
        new_mdat_size = mdat_size + len(sample)
        if mdat_hlen == 8:
            struct.pack_into(">I", raw, mdat_off, new_mdat_size)
        else:
            struct.pack_into(">Q", raw, mdat_off + 8, new_mdat_size)
        # moov shifted right by len(sample) when it follows mdat
        moov_off2 = moov_off + (len(sample) if moov_off >= mdat_off else 0)
        # 2) append trak to moov payload
        trak_off = moov_off2 + moov_size
        raw[trak_off:trak_off] = trak
        struct.pack_into(">I", raw, moov_off2, moov_size + len(trak))
        # 3) mvhd nextTrackID (last 4 bytes of mvhd box)
        for typ, off, size, hlen in _parse_boxes(
                bytes(raw[moov_off2:moov_off2 + moov_size + len(trak)])[8:]):
            if typ == b"mvhd":
                struct.pack_into(">I", raw, moov_off2 + 8 + off + size - 4,
                                 new_id + 1)
                break
        # 4) stco/co64 delta when moov precedes mdat
        if moov_off < mdat_off:
            moov_box = bytearray(
                raw[moov_off2:moov_off2 + moov_size + len(trak)])
            _patch_chunk_offsets(moov_box, len(trak))
            raw[moov_off2:moov_off2 + moov_size + len(trak)] = moov_box
        Path(mov_path).write_bytes(bytes(raw))
        return True
    except Exception:
        return False
