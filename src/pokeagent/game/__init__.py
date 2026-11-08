"""The game seam: a GameSpec per supported game, the GAMES table, and --game selection."""

from pokeagent.game.pokemon_red import RED
from pokeagent.game.registry import DEFAULT_GAME, GAMES, get_game
from pokeagent.game.select import UnknownGame, add_game_argument, resolve_game
from pokeagent.game.spec import GameSpec

__all__ = [
    "RED",
    "GameSpec",
    "GAMES",
    "DEFAULT_GAME",
    "get_game",
    "UnknownGame",
    "resolve_game",
    "add_game_argument",
]
