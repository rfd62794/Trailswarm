"""The playable gate and ROM-to-game detection (hash only; ROM bytes are never kept or copied)."""
from __future__ import annotations

import hashlib
from pathlib import Path

from pokeagent.game.registry import GAMES
from pokeagent.game.spec import GameSpec


class NotPlayable(RuntimeError):
    """A prepared-but-gated game was asked to run."""


def require_playable(game: GameSpec) -> GameSpec:
    """Return ``game`` or raise ``NotPlayable`` with its gate message."""
    if not game.playable:
        raise NotPlayable(f"{game.key} is {game.gate}")
    return game


def rom_sha1(path: str | Path) -> str:
    return hashlib.sha1(Path(path).read_bytes()).hexdigest().upper()


def game_for_sha1(sha1: str) -> GameSpec | None:
    """The registered game accepting this (uppercase hex) hash, else None."""
    for g in GAMES.values():
        if sha1.upper() in g.rom_sha1:
            return g
    return None


def game_for_rom(path: str | Path) -> GameSpec | None:
    """The game a ROM file is, by hash; None for a missing or unknown file."""
    try:
        return game_for_sha1(rom_sha1(path))
    except OSError:
        return None


def find_rom(game: GameSpec, root: str | Path = ".") -> Path | None:
    """The game's default ROM under ``root`` when it exists there, else None."""
    p = Path(root) / game.default_rom
    return p if p.is_file() else None


def adopt_rom_game(argv: list[str], env: dict | None = None) -> GameSpec | None:
    """Select the game from a ``--rom`` argument's hash, BEFORE modules read ``$POKEAGENT_GAME`` at import.

    No ``--rom``, or a ROM that is missing/unknown, changes nothing (None). An explicit ``$POKEAGENT_GAME``
    that disagrees with the ROM's hash raises ``SystemExit`` (a Blue ROM must never write Red's game scope).
    """
    import os
    env = os.environ if env is None else env
    rom = None
    for i, a in enumerate(argv):
        if a == "--rom" and i + 1 < len(argv):
            rom = argv[i + 1]
        elif a.startswith("--rom="):
            rom = a[len("--rom="):]
    spec = game_for_rom(rom) if rom else None
    if spec is None:
        return None
    chosen = env.get("POKEAGENT_GAME")
    if chosen and chosen != spec.key:
        raise SystemExit(f"error: --rom is {spec.key} but POKEAGENT_GAME={chosen}")
    env["POKEAGENT_GAME"] = spec.key
    return spec
