"""Stadium strip content (pure): which battles get a panel, capped so the strip never overflows."""
from __future__ import annotations

from pokeagent.world.model import BattleCard

MAX_CARDS = 8


def strip(entries: list[tuple[str, BattleCard]], max_cards: int = MAX_CARDS) -> tuple[list[tuple[str, BattleCard]], int]:
    """At most ``max_cards`` panels (open battles first) and the count of battles that did not fit."""
    ordered = sorted(entries, key=lambda e: e[1].ended_at is not None)
    return ordered[:max_cards], max(0, len(ordered) - max_cards)


def lines(c: BattleCard) -> list[str]:
    """Text rows of one battle card."""
    out = [f"{c.own_species or '?'} L{c.own_level}  vs  {c.species or '?'} L{c.enemy_level}",
           f"you {c.hp}/{c.max_hp}   enemy {c.enemy_hp}/{c.enemy_max_hp}",
           f"turn {c.turn}   last: {c.move or '-'} {c.effect}".rstrip()]
    if c.plan:
        out.append(f"plan: {c.plan[:40]}")
    if c.result:
        out.append(f"RESULT: {c.result}")
    return out


def hp_frac(hp: int, max_hp: int) -> float:
    return 0.0 if max_hp <= 0 else max(0.0, min(1.0, hp / max_hp))
