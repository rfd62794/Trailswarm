"""The one place that turns the selected game into a ROM path."""

from __future__ import annotations

from pathlib import Path

from pokeagent.game.select import resolve_game
from pokeagent.game.spec import GameSpec


def default_rom(game: GameSpec | None = None, root: Path | None = None) -> Path:
    """The game's ROM path, relative to the cwd, or under ``root`` when given.

    ``game=None`` means the selected game (``resolve_game``: ``$POKEAGENT_GAME``,
    else the default), so an unknown key fails the same way ``resolve_game`` does.
    Does not look at ``$POKEAGENT_ROM`` - ``cli._rom_path`` keeps that precedence
    (``--rom``, then the env, then this).
    """
    game = resolve_game(None) if game is None else game
    return game.default_rom if root is None else Path(root) / game.default_rom
