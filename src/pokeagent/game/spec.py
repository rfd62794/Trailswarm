"""The per-game spec: what the CLI needs to know about one supported game."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_KEY_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_SHA1_RE = re.compile(r"^[0-9A-F]{40}$")
KNOWN_BUTTONS = frozenset({"up", "down", "left", "right", "a", "b", "start", "select"})
LEGACY_FAMILY = "gen1-pokemon"  # the shared memory of Red/Blue/Yellow-class games: its stores keep today's paths


@dataclass(frozen=True)
class GameSpec:
    key: str                       # "pokemon-red": the stable name used by --game, POKEAGENT_GAME and later by store paths
    title: str                     # "Pokemon Red"
    rom_sha1: tuple[str, ...]      # accepted ROM hashes, uppercase hex, at least one
    default_rom: Path              # relative to the repo root, forward slashes, e.g. Path("roms/<game>.gb")
    screen: tuple[int, int]        # (width, height) in pixels
    buttons: tuple[str, ...]       # lowercase names of the buttons the game uses, in this order
    memory_family: str             # the family whose memory this game shares; LEGACY_FAMILY = the legacy root
    owns_legacy_paths: bool        # True for the one game (Red) whose per-game stores also stay on today's paths

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
        rom = Path(self.default_rom)
        if rom.is_absolute() or rom.drive or str(rom).startswith(("/", "\\")) or not rom.suffix:
            raise ValueError(
                f"{self.key}: default_rom must be a relative path with a suffix: {self.default_rom!r}"
            )
        if (not isinstance(self.screen, tuple) or len(self.screen) != 2
                or not all(type(v) is int and v > 0 for v in self.screen)):
            raise ValueError(f"{self.key}: screen must be two positive ints: {self.screen!r}")
        if not self.buttons or len(set(self.buttons)) != len(self.buttons):
            raise ValueError(f"{self.key}: buttons must be non-empty and unique: {self.buttons!r}")
        bad = [b for b in self.buttons
               if not isinstance(b, str) or b != b.lower() or b not in KNOWN_BUTTONS]
        if bad:
            raise ValueError(
                f"{self.key}: unknown buttons {bad!r} (this pad: {', '.join(sorted(KNOWN_BUTTONS))})"
            )
        if not _KEY_RE.fullmatch(self.memory_family):
            raise ValueError(f"bad memory_family: {self.memory_family!r}")
        if self.owns_legacy_paths and self.memory_family != LEGACY_FAMILY:
            raise ValueError(
                f"{self.key}: owns_legacy_paths requires memory_family == LEGACY_FAMILY"
            )
