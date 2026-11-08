"""Game selection: --game beats $POKEAGENT_GAME beats the default."""

from __future__ import annotations

import argparse
import os
from collections.abc import Mapping

from pokeagent.game.registry import DEFAULT_GAME, get_game
from pokeagent.game.spec import GameSpec


class UnknownGame(ValueError):
    """Raised when --game or POKEAGENT_GAME names a game not in GAMES."""


def resolve_game(arg: str | None, env: Mapping[str, str] | None = None) -> GameSpec:
    """--game if given, else $POKEAGENT_GAME if set and non-empty, else DEFAULT_GAME."""
    if env is None:
        env = os.environ
    key = arg if arg is not None else (env.get("POKEAGENT_GAME") or DEFAULT_GAME)
    try:
        return get_game(key)
    except KeyError as e:
        raise UnknownGame(e.args[0]) from None


def add_game_argument(parser: argparse.ArgumentParser) -> None:
    """Add --game KEY; the default stays None so resolve_game sees 'not given'."""
    parser.add_argument(
        "--game",
        default=None,
        metavar="KEY",
        help=f"game to play (default {DEFAULT_GAME}; also $POKEAGENT_GAME)",
    )
