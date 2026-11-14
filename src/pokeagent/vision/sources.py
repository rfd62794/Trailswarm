"""The game registry for label sources; adding a game is one module plus one line here."""
from __future__ import annotations

from pokeagent.vision.labels import LabelSource
from pokeagent.vision.source_red import SOURCE as POKEMON_RED

SOURCES: dict[str, LabelSource] = {"pokemon-red": POKEMON_RED}


def get_source(game: str) -> LabelSource:
    """The label source for a game key; a clear error for names this build does not record."""
    try:
        return SOURCES[game]
    except KeyError:
        known = ", ".join(sorted(SOURCES))
        raise ValueError(f"no vision label source for {game!r}; known games: {known}") from None
