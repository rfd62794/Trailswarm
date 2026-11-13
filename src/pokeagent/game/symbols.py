"""The RAM-symbol table seam: a game spec names its table (``GameSpec.symbols``); Red and Blue share today's.

Modules that import ``pokeagent.ram_symbols`` constants directly keep working unchanged (Red/Blue). New or
game-aware code asks ``symbol_table(game)`` for ``{NAME: address}``. Yellow's table is deliberately absent
until pokeyellow.sym is imported: asking for it raises ``SymbolTableMissing`` instead of returning Red's addresses.
"""
from __future__ import annotations

from importlib import resources

from pokeagent import ram_symbols
from pokeagent.game.spec import GameSpec


class SymbolTableMissing(LookupError):
    """The game's symbol table has not been written yet."""


def _gen1_rb() -> dict[str, int]:
    return {k: v for k, v in vars(ram_symbols).items() if k.isupper() and isinstance(v, int)}


SYMBOL_TABLES = {"gen1-rb": _gen1_rb}   # "gen1-yellow" is intentionally unregistered: see Yellow_Prep.md


def symbol_table(game: GameSpec) -> dict[str, int]:
    """The game's WRAM symbol addresses (a fresh dict)."""
    try:
        return SYMBOL_TABLES[game.symbols]()
    except KeyError:
        raise SymbolTableMissing(f"{game.key}: no symbol table {game.symbols!r} yet") from None


def ram_table_text(game: GameSpec) -> str:
    """The game's pret label map (data/<ram_table>) text; raises SymbolTableMissing when the file is absent."""
    res = resources.files("pokeagent.data").joinpath(game.ram_table)
    if not res.is_file():
        raise SymbolTableMissing(f"{game.key}: data/{game.ram_table} not written yet")
    return res.read_text(encoding="utf-8")
