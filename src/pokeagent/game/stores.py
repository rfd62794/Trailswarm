"""The one place a store path becomes a path: namespaced by memory family, or by game.

Only ``runs`` and ``kb`` are namespaced roots. A family-scope store (``scope="family"``) belongs to the
game's ``memory_family``: games in ``LEGACY_FAMILY`` (Red today, Blue/Yellow-class once they pass compat)
return ``rel`` unchanged, so Red's paths are byte-identical to today's and a sibling in the same family
shares them. A game in its own family gets the family inserted as the second path component
(``runs/maps.json`` -> ``runs/<family>/maps.json``).

A game-scope store (``scope="game"``, e.g. ``runs/checkpoints`` - a save state is bound to one ROM even
when memory is shared) belongs to the game itself: only ``owns_legacy_paths`` (Red) keeps ``rel``
unchanged; every other game gets its ``key`` inserted the same way.

Directories are never created here - callers ``mkdir(parents=True)`` where they write.
"""
from __future__ import annotations

from pathlib import Path

from pokeagent.game.select import resolve_game
from pokeagent.game.spec import LEGACY_FAMILY, GameSpec

_ROOTS = ("runs", "kb")
_SCOPES = ("family", "game")


def store_path(rel: str | Path, game: GameSpec | None = None,
               root: Path | None = None, scope: str = "family") -> Path:
    """The game's store path for ``rel`` (``/`` or ``\\`` separators, ``Path`` out).

    ``rel`` must start with ``runs`` or ``kb`` (the only namespaced roots) and ``scope`` must be
    ``"family"`` (the default) or ``"game"``. ``game=None`` resolves the selected game through
    ``resolve_game`` so ``$POKEAGENT_GAME`` is honoured. ``root`` prepends a checkout root.
    """
    parts = str(rel).replace("\\", "/").split("/")
    if parts[0] not in _ROOTS:
        raise ValueError(f"store_path: not a runs/ or kb/ path: {rel!r}")
    if scope not in _SCOPES:
        raise ValueError(f"store_path: unknown scope {scope!r} (family or game)")
    game = resolve_game(None) if game is None else game
    if scope == "family":
        out = Path(*parts) if game.memory_family == LEGACY_FAMILY \
            else Path(parts[0], game.memory_family, *parts[1:])
    else:
        out = Path(*parts) if game.owns_legacy_paths \
            else Path(parts[0], game.key, *parts[1:])
    return out if root is None else Path(root) / out
