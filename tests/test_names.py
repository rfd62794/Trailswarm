import pytest

from pokeagent.emulator import FakeEmulator
from pokeagent.names import Entry, Registry, load_registry


def test_registry_loads_15_entries():
    reg = load_registry()
    assert len(reg.entries) == 15
    e = reg.by_name["wXCoord"]
    assert e.addr == 0xD362
    assert e.size == 1
    assert e.encoding == "u8"


def test_by_addr_resolves_inside_tilemap_range():
    reg = load_registry()
    e = reg.by_addr(0xC3A5)
    assert e is not None
    assert e.name == "wTileMap"
    assert reg.name_at(0xC3A5) == "wTileMap+5"
    assert reg.name_at(0xC3A0) == "wTileMap"


def test_by_addr_misses_unclaimed_bytes():
    reg = load_registry()
    assert reg.by_addr(0xB000) is None
    assert reg.name_at(0xB000) is None


def _entry(encoding, size=1):
    return Entry("t", 0xC000, size, encoding)


@pytest.mark.parametrize(
    "encoding,size,raw,expected",
    [
        ("u8", 1, b"\x07", 7),
        ("u16le", 2, b"\x01\x02", 0x0201),
        ("u16be", 2, b"\x01\x02", 0x0102),
        ("bcd", 3, b"\x01\x23\x45", 12345),
        ("bitmask", 1, b"\x81", [0, 7]),
        ("bitmask", 1, b"\x05", [0, 2]),
        ("bool", 1, b"\x00", False),
        ("bool", 1, b"\x02", True),
        ("text", 4, b"\x80\x81\x50\xff", "AB"),
        ("bytes", 2, b"\x01\xff", b"\x01\xff"),
    ],
)
def test_decode_encodings(encoding, size, raw, expected):
    assert Registry.decode(_entry(encoding, size), raw) == expected


def test_decode_unknown_encoding_raises():
    with pytest.raises(ValueError):
        Registry.decode(_entry("bogus"), b"\x00")


def test_read_decodes_through_emulator():
    reg = load_registry()
    fake = FakeEmulator({0xD362: 5, 0xD347: 0x00, 0xD348: 0x30, 0xD349: 0x00})
    assert reg.read(fake, "wXCoord") == 5
    assert reg.read(fake, "wPlayerMoney") == 3000


def test_load_registry_from_explicit_path(tmp_path):
    p = tmp_path / "r.json"
    p.write_text(
        '[{"name": "wFoo", "addr": "0xC100", "size": 1, "encoding": "u8",'
        ' "verified": false, "note": ""}]',
        encoding="utf-8",
    )
    reg = load_registry(p)
    assert reg.by_name["wFoo"].addr == 0xC100
