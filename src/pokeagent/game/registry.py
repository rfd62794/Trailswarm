"""The games table: every supported game keyed by GameSpec.key.

Registration is by editing GAMES below; no plugin discovery.
"""

from pokeagent.game.pokemon_red import RED
from pokeagent.game.spec import GameSpec

GAMES: dict[str, GameSpec] = {RED.key: RED}
DEFAULT_GAME = "pokemon-red"


def get_game(key: str) -> GameSpec:
    """Return the spec for key; KeyError names the known keys."""
    try:
        return GAMES[key]
    except KeyError:
        raise KeyError(
            f"unknown game {key!r}; known: {', '.join(sorted(GAMES))}"
        ) from None
