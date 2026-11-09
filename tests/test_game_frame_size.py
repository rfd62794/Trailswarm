"""Frame slots sized by the emulator's game: a non-Red screen still round-trips, a Red slot is byte-identical."""
from pathlib import Path

from pokeagent.emulator import FakeEmulator
from pokeagent.game import GameSpec
from pokeagent.telemetry import (FRAME_H, FRAME_W, HEADER, LAYOUT, LAYOUT_OFF, MAGIC_OFF,
                                 READER_TS_OFF, SLOT_MAGIC, FramePublisher, FrameSubscriber,
                                 slot_layout)

TINY = GameSpec(
    key="tiny-game",
    title="Tiny",
    rom_sha1=("B" * 40,),
    default_rom=Path("roms/Tiny.gb"),
    screen=(2, 2),
    buttons=("a", "b", "start"),
)


def test_fake_game_slot_round_trips_with_its_size():
    pub = FramePublisher("gsz_tiny", FakeEmulator(game=TINY))
    try:
        assert pub.dims() == (2, 2)
        assert pub.shm.size == HEADER + 2 * 2 * 3
        pub.publish()
        assert slot_layout(pub.shm.buf) == LAYOUT  # a smaller v2 slot is still v2
        sub = FrameSubscriber(pub.name)
        data, w, h = sub.read()
        assert (w, h) == (2, 2)
        assert data == bytes(2 * 2 * 3)
        sub.close()
    finally:
        pub.close()


def test_red_slot_size_and_header_bytes_unchanged():
    pub = FramePublisher("gsz_red", FakeEmulator())
    try:
        assert pub.dims() == (FRAME_W, FRAME_H) == (160, 144)
        assert pub.shm.size == HEADER + FRAME_W * FRAME_H * 3
        pub.publish()
        b = pub.shm.buf
        assert int.from_bytes(b[8:10], "little") == FRAME_W
        assert int.from_bytes(b[10:12], "little") == FRAME_H
        assert int.from_bytes(b[LAYOUT_OFF:LAYOUT_OFF + 4], "little") == LAYOUT
        assert int.from_bytes(b[MAGIC_OFF:MAGIC_OFF + 4], "little") == SLOT_MAGIC
        assert bytes(b[READER_TS_OFF:HEADER]) == bytes(HEADER - READER_TS_OFF)
        sub = FrameSubscriber(pub.name)
        data, w, h = sub.read()
        assert (w, h) == (FRAME_W, FRAME_H)
        assert len(data) == FRAME_W * FRAME_H * 3
        sub.close()
    finally:
        pub.close()


def test_publisher_falls_back_to_module_dims():
    class BareEmu:
        def tick_rendered(self, n): pass
        def frame_rgb(self): return bytes(FRAME_W * FRAME_H * 3)

    pub = FramePublisher("gsz_bare", BareEmu())
    try:
        assert pub.dims() == (FRAME_W, FRAME_H)
        assert pub.shm.size == HEADER + FRAME_W * FRAME_H * 3
    finally:
        pub.close()
