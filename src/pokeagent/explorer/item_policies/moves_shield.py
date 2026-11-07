"""Which of a mon's moves a taught move may overwrite. Never an HM move the campaign still needs, never the only damaging move of
the type that hits the next boss best. Among the rest: a status move first, else the weakest by cartridge value."""
from __future__ import annotations

from typing import Callable, Iterable

Info = Callable[[str], "dict | None"]   # move name -> {"power", "type", "accuracy"} or None when unknown


def default_info(name: str) -> dict | None:
    from pokeagent.explorer.battle import move_by_name
    return move_by_name(name)


def default_chart() -> dict:
    from pokeagent.explorer.kb import ROM_KB
    return {(a, d): e for a, d, e in (ROM_KB or {}).get("type_chart", ())}


def _value(name: str, info: Info) -> float:
    mv = info(name)
    return mv["power"] * mv["accuracy"] if mv else 0.0


def _damaging(name: str, info: Info) -> bool:
    mv = info(name)
    return bool(mv and mv["power"] > 0)


def best_attack(moves: Iterable[str], boss_types: list[tuple[str, ...]], info: Info, chart: dict) -> str | None:
    """The damaging move with the most expected damage against the boss's mons (type multiplier summed); no boss = raw value."""
    from pokeagent.knowledge.damage import type_mult
    moves = [m for m in moves if _damaging(m, info)]

    def score(m: str) -> float:
        mv = info(m)
        mult = sum(type_mult(chart, mv["type"], list(t)) for t in boss_types) if boss_types else 1.0
        return _value(m, info) * mult
    return max(moves, key=score) if moves else None


def protected_moves(moves: tuple[str, ...], needed_hm_moves: set[str], boss_types: list[tuple[str, ...]], info: Info, chart: dict) -> set[str]:
    keep = {m for m in moves if m in needed_hm_moves}
    best = best_attack(moves, boss_types, info, chart)
    if best:
        best_type = info(best)["type"]
        same_type = [m for m in moves if _damaging(m, info) and info(m)["type"] == best_type]
        if len(same_type) == 1:
            keep.add(best)
    return keep


def choose_overwrite(moves: tuple[str, ...], protected: set[str], info: Info) -> int | None:
    """Index of the move slot to overwrite, or None when every move is protected. Status moves first, then the weakest."""
    free = [i for i, m in enumerate(moves) if m not in protected]
    if not free:
        return None
    return min(free, key=lambda i: (_damaging(moves[i], info), _value(moves[i], info), i))
