"""The per-game spec: what the CLI needs to know about one supported game."""

from __future__ import annotations

import re
from dataclasses import dataclass

_KEY_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_SHA1_RE = re.compile(r"^[0-9A-F]{40}$")


@dataclass(frozen=True)
class GameSpec:
    key: str                       # "pokemon-red": the stable name used by --game, POKEAGENT_GAME and later by store paths
    title: str                     # "Pokemon Red"
    rom_sha1: tuple[str, ...]      # accepted ROM hashes, uppercase hex, at least one

    def __post_init__(self) -> None:
        if not _KEY_RE.fullmatch(self.key):
            raise ValueError(f"bad game key: {self.key!r}")
        if not self.rom_sha1:
            raise ValueError(f"{self.key}: rom_sha1 needs at least one hash")
        for entry in self.rom_sha1:
            if not _SHA1_RE.fullmatch(entry):
                raise ValueError(
                    f"{self.key}: bad rom_sha1 entry (40 uppercase hex): {entry!r}"
                )
