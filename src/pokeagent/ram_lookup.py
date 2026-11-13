"""Read-only lookup over data/ram_map.json (the full pret label map): by name, address or region."""
from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from typing import Any

from pokeagent.emulator import Emulator


@dataclass(frozen=True)
class MapEntry:
    name: str
    addr: int
    size: int
    region: str
    encoding: str = "bytes"
    verified: bool = False
    evidence: str = ""
    note: str = ""

    def covers(self, addr: int) -> bool:
        return self.addr <= addr < self.addr + self.size


def load_map(game=None) -> list[MapEntry]:
    """The label map; ``game`` (a GameSpec) selects its table, None is Red/Blue's today (``ram_map.json``)."""
    if game is None:
        text = resources.files("pokeagent.data").joinpath("ram_map.json").read_text(encoding="utf-8")
    else:
        from pokeagent.game.symbols import ram_table_text
        text = ram_table_text(game)
    return [MapEntry(d["name"], int(d["addr"], 16), d["size"], d["region"], d.get("encoding", "bytes"),
                     d.get("verified", False), d.get("evidence", ""), d.get("note", "")) for d in json.loads(text)]


def regions(entries: list[MapEntry]) -> dict[str, int]:
    out: dict[str, int] = {}
    for e in entries:
        out[e.region] = out.get(e.region, 0) + 1
    return dict(sorted(out.items()))


def query(entries: list[MapEntry], what: str) -> list[MapEntry]:
    """``what`` is an address (0xD16B / D16B-style hex), a region name, or a name substring.

    An address returns every label whose range covers it, tightest first."""
    w = what.strip()
    try:
        addr = int(w, 16) if w.lower().startswith("0x") or (len(w) == 4 and all(c in "0123456789abcdefABCDEF" for c in w)) else None
    except ValueError:
        addr = None
    if addr is not None:
        return sorted((e for e in entries if e.covers(addr)), key=lambda e: (e.size, e.name))
    by_region = [e for e in entries if e.region == w.lower()]
    if by_region:
        return by_region
    low = w.lower()
    exact = [e for e in entries if e.name.lower() == low]
    return exact or [e for e in entries if low in e.name.lower()]


def decode_value(e: MapEntry, raw: bytes) -> Any:
    """A short human value: the integer for 1-2 byte fields, hex bytes otherwise."""
    if e.size == 1:
        return raw[0]
    if e.size == 2 and e.encoding != "bytes":
        return int.from_bytes(raw, "big")
    return raw[:16].hex(" ") + (" ..." if len(raw) > 16 else "")


def describe(e: MapEntry, emu: Emulator | None = None) -> str:
    flag = "verified" if e.verified else "unverified"
    line = f"0x{e.addr:04X} +{e.size:<4d} {e.name:40s} [{e.region}] {flag}"
    if emu is not None:
        line += f"  = {decode_value(e, emu.read_range(e.addr, min(e.size, 64)))}"
    return line + (f"\n      evidence: {e.evidence}" if e.evidence else "")
