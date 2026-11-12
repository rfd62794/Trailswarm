"""stable-retro variable types and the ``data.json`` dict built from a measured address table. Pure.

Type strings follow stable-retro's convention (endianness, then i/u/d/n, then byte count, e.g. ``|u1``,
``>u2``, ``>d2``). The ``{"info": {name: {"address", "type"}}}`` wrapper is taken from stable-retro's
integration docs and is UNVERIFIED: nobody has loaded this output in a real stable-retro install.
``address`` is the Game Boy CPU address from ram_map.json, written in decimal; whether stable-retro's
Game Boy integration uses the same address base is also unverified.
"""
from __future__ import annotations

from typing import Any, Iterable

from pokeagent.ram_lookup import MapEntry


def _enc_size(entry: Any) -> tuple[str, int]:
    if isinstance(entry, MapEntry):
        return entry.encoding, entry.size
    return entry["type"], entry["width"]


def retro_type(entry: MapEntry | dict) -> str | None:
    """A MapEntry or a table row; None when there is no honest scalar type (bytes, text, wide fields)."""
    enc, size = _enc_size(entry)
    if enc in ("u8", "bitmask") and size == 1:
        return "|u1"
    if enc == "u16be" and size == 2:
        return ">u2"
    if enc == "bcd" and 1 <= size <= 4:
        return f">d{size}"
    return None


def selected_rows(table: dict, game: str, include: Iterable[str]) -> list[dict]:
    keep = set(include)
    return [r for r in table["entries"] if r["games"][game]["status"] in keep]


def build_retro_data(table: dict, game: str, include: Iterable[str] = ("measured",)) -> dict:
    info: dict[str, dict] = {}
    for row in selected_rows(table, game, include):
        t = retro_type(row)
        if t is not None:
            info[row["label"]] = {"address": int(row["addr"], 16), "type": t}
    return {"info": info}


def untyped_count(table: dict, game: str, include: Iterable[str] = ("measured",)) -> int:
    """Selected rows skipped from data.json because they have no scalar type."""
    return sum(1 for r in selected_rows(table, game, include) if retro_type(r) is None)
