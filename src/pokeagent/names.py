"""Named-address registry: JSON-backed map of WRAM addresses to names.

Every entry is a claim, not a fact: ``verified`` stays false until a
calibration run on the real ROM flips it, with ``evidence`` recording what
confirmed it. Lives in data/ram_names.json so the map can grow without
touching code.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from pokeagent.emulator import Emulator
from pokeagent.ram import decode_bcd
from pokeagent.screentext import decode_text

REGISTRY_RESOURCE = "ram_names.json"


@dataclass(frozen=True)
class Entry:
    """One named RAM region read from the registry file."""

    name: str
    addr: int
    size: int
    encoding: str
    verified: bool = False
    note: str = ""
    evidence: str | None = None

    def covers(self, addr: int) -> bool:
        return self.addr <= addr < self.addr + self.size


class Registry:
    """Lookup and decode for the named addresses."""

    def __init__(self, entries: list[Entry]) -> None:
        self.entries = list(entries)
        self.by_name: dict[str, Entry] = {e.name: e for e in self.entries}

    def by_addr(self, addr: int) -> Entry | None:
        """The entry whose range holds addr (0xC3A5 resolves inside wTileMap)."""
        for e in self.entries:
            if e.covers(addr):
                return e
        return None

    def name_at(self, addr: int) -> str | None:
        """Display name for an address: ``wXCoord``, ``wTileMap+5``, or None."""
        e = self.by_addr(addr)
        if e is None:
            return None
        offset = addr - e.addr
        return e.name if offset == 0 else f"{e.name}+{offset}"

    @staticmethod
    def decode(entry: Entry, raw: bytes) -> Any:
        """Decode raw bytes read at entry.addr per its encoding."""
        enc = entry.encoding
        if enc == "u8":
            return raw[0]
        if enc == "u16le":
            return int.from_bytes(raw, "little")
        if enc == "u16be":
            return int.from_bytes(raw, "big")
        if enc == "bcd":
            return decode_bcd(raw)
        if enc == "bitmask":
            return [i for i in range(len(raw) * 8) if raw[i // 8] & (1 << (i % 8))]
        if enc == "bool":
            return any(raw)
        if enc == "text":
            return decode_text(raw)
        if enc == "bytes":
            return bytes(raw)
        raise ValueError(f"unknown encoding {enc!r} on {entry.name}")

    def read(self, emu: Emulator, name: str) -> Any:
        """Read the named entry's bytes through the emulator, decoded."""
        e = self.by_name[name]
        return self.decode(e, emu.read_range(e.addr, e.size))


def load_registry(path: str | Path | None = None) -> Registry:
    """Load the registry: the packaged JSON, or an explicit path."""
    if path is None:
        text = (
            resources.files("pokeagent.data")
            .joinpath(REGISTRY_RESOURCE)
            .read_text(encoding="utf-8")
        )
    else:
        text = Path(path).read_text(encoding="utf-8")
    return Registry(
        [
            Entry(
                name=d["name"],
                addr=int(d["addr"], 16),
                size=d["size"],
                encoding=d["encoding"],
                verified=d.get("verified", False),
                note=d.get("note", ""),
                evidence=d.get("evidence"),
            )
            for d in json.loads(text)
        ]
    )
