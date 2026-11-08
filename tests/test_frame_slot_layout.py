"""Frame-slot layout detection: v2 needs layout AND magic, and the reader heartbeat is v2-only.

A v1 slot's size cannot prove its layout (shared memory is page-rounded on the attaching side,
so a v1 buffer can report a v2 size) and its header offsets are pixel data - a v1 frame whose
first pixel bytes spell ``02 00 00 00`` must still read as v1 (frame at offset 16, no heartbeat).
"""
import os
import time
from multiprocessing import shared_memory

from pokeagent import telemetry
from pokeagent.telemetry import (FRAME_H, FRAME_W, HEADER, HEADER_V1, LAYOUT, LAYOUT_OFF,
                                 MAGIC_OFF, READER_TS_OFF, SLOT_MAGIC, FramePublisher,
                                 FrameSubscriber, reader_ts, slot_layout)

FRAME_BYTES = FRAME_W * FRAME_H * 3
READER_LIVE_S = 2.0   # Agent_Footprint's publish gate: render only while a reader is this fresh


class Emu:
    def tick_rendered(self, n): pass
    def frame_rgb(self): return bytes([7]) * FRAME_BYTES


def _v1_slot(name: str, first_pixels: bytes = b"") -> shared_memory.SharedMemory:
    """A hand-built v1 slot: the 16-byte header (seq/w/h/pid) + frame bytes at offset 16."""
    shm = shared_memory.SharedMemory(name=name, create=True, size=HEADER_V1 + FRAME_BYTES)
    shm.buf[0:8] = (2).to_bytes(8, "little")          # even seq: one complete frame written
    shm.buf[8:10] = FRAME_W.to_bytes(2, "little")
    shm.buf[10:12] = FRAME_H.to_bytes(2, "little")
    shm.buf[12:16] = os.getpid().to_bytes(4, "little")
    frame = bytes(first_pixels) + bytes([9]) * (FRAME_BYTES - len(first_pixels))
    shm.buf[HEADER_V1:HEADER_V1 + FRAME_BYTES] = frame
    return shm


def test_v2_publisher_header_round_trip():
    p = FramePublisher("v2hdr", Emu())
    try:
        p.publish()
        b = p.shm.buf
        assert int.from_bytes(b[0:8], "little") == p.seq and p.seq % 2 == 0
        assert (int.from_bytes(b[8:10], "little"), int.from_bytes(b[10:12], "little")) == (160, 144)
        assert int.from_bytes(b[12:16], "little") == os.getpid()
        assert int.from_bytes(b[LAYOUT_OFF:LAYOUT_OFF + 4], "little") == LAYOUT
        assert int.from_bytes(b[MAGIC_OFF:MAGIC_OFF + 4], "little") == SLOT_MAGIC
        assert reader_ts(b) == 0.0                     # no reader yet
        assert slot_layout(b) == LAYOUT
        assert b[HEADER:HEADER + 4] == bytes([7]) * 4  # the frame starts at offset 32
    finally:
        p.close()


def test_v1_slot_with_layout_spelling_pixels_reads_as_v1():
    """First pixel bytes 02 00 00 00 (the LAYOUT word) must not turn a v1 slot into v2."""
    shm = _v1_slot(f"pokeagent_frames_v1fake_{os.getpid()}",
                   first_pixels=b"\x02\x00\x00\x00\x03\x00\x00\x00")
    try:
        s = FrameSubscriber(shm.name)
        fr = s.read()
        assert fr is not None
        data, w, h = fr
        assert (w, h) == (FRAME_W, FRAME_H)
        assert data[:4] == b"\x02\x00\x00\x00"         # read at offset 16, not the v2 offset 32
        assert slot_layout(s.shm.buf) == 1             # pixel bytes spelling LAYOUT do not fool it
        s.close()
    finally:
        shm.close()
        shm.unlink()


def test_heartbeat_written_on_v2_and_everything_else_untouched():
    p = FramePublisher("v2hb", Emu())
    try:
        p.publish()
        before = bytes(p.shm.buf)
        s = FrameSubscriber(p.name)
        t0 = time.time()
        fr = s.read()
        after = bytes(p.shm.buf)
        assert fr is not None and reader_ts(p.shm.buf) >= t0
        assert after[:READER_TS_OFF] == before[:READER_TS_OFF]   # seq, w/h, pid, layout, magic intact
        assert after[HEADER:] == before[HEADER:]                 # every frame byte intact
        s.close()
    finally:
        p.close()


def test_heartbeat_never_written_on_v1():
    """On a v1 slot the whole buffer - frame bytes included - is identical before and after."""
    shm = _v1_slot(f"pokeagent_frames_v1hb_{os.getpid()}")
    try:
        before = bytes(shm.buf)
        s = FrameSubscriber(shm.name)
        assert s.read() is not None
        assert bytes(shm.buf) == before                # the heartbeat write is a no-op on v1
        s.close()
    finally:
        shm.close()
        shm.unlink()


def test_stale_then_fresh_heartbeat_as_the_publisher_reads_it():
    """reader_ts is what FramePublisher gates rendering on (Agent_Footprint item 2): 0 = stale."""
    p = FramePublisher("v2stale", Emu())
    try:
        p.publish()
        assert reader_ts(p.shm.buf) == 0.0                                  # never read: always stale
        assert time.time() - reader_ts(p.shm.buf) >= READER_LIVE_S
        s = FrameSubscriber(p.name)
        s.read()
        assert 0.0 <= time.time() - reader_ts(p.shm.buf) < READER_LIVE_S    # fresh: the publisher renders
        s.close()
    finally:
        p.close()
