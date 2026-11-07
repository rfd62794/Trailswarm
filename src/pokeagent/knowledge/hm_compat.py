"""Which species can learn each HM, read from the ROM's BaseStats TM/HM bitfield -> kb/hm_compat.json (gitignored, ROM-derived).

BaseStats (pokered.sym 0e:43de, file offset 0x383DE) is 28 bytes per species in POKEDEX order; bytes 20..26 are the TM/HM
learnability bitfield (bit n = byte n//8, bit n%8). TM01..50 are bits 0..49; HM01..05 are bits 50..54: Cut, Fly, Surf, Strength, Flash.
``load()`` reads the kb file, builds it from the ROM on first use when the ROM + kb/rom_tables.json exist, else returns None.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
KB_PATH, ROM_PATH = ROOT / "kb" / "hm_compat.json", ROOT / "roms" / "Pokemon Red.gb"
BASE_STATS, REC, TMHM_AT = 0x0E * 0x4000 + (0x43DE - 0x4000), 28, 20
HM_BITS = {"cut": 50, "fly": 51, "surf": 52, "strength": 53, "flash": 54}


def extract(rom: bytes, names: dict[int, str]) -> dict[str, list[str]]:
    """{hm: [species names]} for dex 1..150 (Mew is stored elsewhere); raises AssertionError if the ROM looks wrong."""
    hms: dict[str, list[str]] = {h: [] for h in HM_BITS}
    for dex in range(1, 151):
        rec = rom[BASE_STATS + (dex - 1) * REC: BASE_STATS + dex * REC]
        assert rec[0] == dex, f"BaseStats misaligned at dex {dex}"
        flags = rec[TMHM_AT:TMHM_AT + 7]
        for hm, bit in HM_BITS.items():
            if flags[bit // 8] >> (bit % 8) & 1:
                hms[hm].append(names[dex])
    assert "BULBASAUR" in hms["cut"] and "SQUIRTLE" not in hms["cut"] and "PIKACHU" in hms["flash"], "sanity checks failed"
    return hms


def build(rom_path: Path = ROM_PATH, kb_rom: Path = ROOT / "kb" / "rom_tables.json", out: Path = KB_PATH) -> dict[str, list[str]]:
    names = {int(k): v["name"] for k, v in json.loads(kb_rom.read_text(encoding="utf-8"))["species_by_dex"].items()}
    hms = extract(Path(rom_path).read_bytes(), names)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"source": "ROM BaseStats TM/HM bitfield (0e:43de +20, bits 50-54); generated, not committed", "hms": hms}, indent=1) + "\n", encoding="utf-8")
    return hms


@lru_cache(maxsize=1)
def load() -> dict[str, frozenset] | None:
    """The HM table, or None when there is neither a kb file nor a ROM to build it from."""
    try:
        if not KB_PATH.exists() and ROM_PATH.exists():
            build()
        raw = json.loads(KB_PATH.read_text(encoding="utf-8"))["hms"]
    except (OSError, ValueError, KeyError, AssertionError):
        return None
    return {hm: frozenset(v) for hm, v in raw.items()}
