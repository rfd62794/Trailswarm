from pokeagent.emulator import FakeEmulator
from pokeagent.names import load_registry
from pokeagent.screentext import CHARMAP, decode_text, read_screen_text


def test_decode_text_basic_glyphs_and_end_marker():
    raw = bytes([0x80, 0x81, 0x82, 0x7F, 0xA0, 0x50, 0x99, 0x99])
    assert decode_text(raw) == "ABC a"


def test_decode_text_unknown_bytes_become_question_mark():
    assert decode_text(bytes([0x01, 0x80, 0x50])) == "?A"
    assert decode_text(bytes([0x50])) == ""
    assert decode_text(b"") == ""


def test_charmap_covers_seeded_ranges():
    assert CHARMAP[0x80] == "A"
    assert CHARMAP[0x99] == "Z"
    assert CHARMAP[0xA0] == "a"
    assert CHARMAP[0xB9] == "z"
    assert CHARMAP[0xF6] == "0"
    assert CHARMAP[0xFF] == "9"
    assert CHARMAP[0x7F] == " "


def test_read_screen_text_returns_only_text_rows():
    reg = load_registry()
    fake = FakeEmulator()
    # Row 3 of the tile map: "ABC ab" followed by blank spaces.
    tiles = [0x80, 0x81, 0x82, 0x7F, 0xA0, 0xA1] + [0x7F] * 14
    for i, t in enumerate(tiles):
        fake.set(0xC3A0 + 3 * 20 + i, t)
    assert read_screen_text(fake, reg) == ["ABC ab"]


def test_read_screen_text_graphics_decode_to_dots():
    reg = load_registry()
    fake = FakeEmulator()
    # Row 0: overworld tiles (no charmap glyphs) show as dots.
    for i in range(20):
        fake.set(0xC3A0 + i, 0x10)
    assert read_screen_text(fake, reg) == ["...................."]


def test_read_screen_text_blank_map_returns_nothing():
    reg = load_registry()
    assert read_screen_text(FakeEmulator(), reg) == []
