"""Gen 1 stats awareness: DVs, stat experience and the stat formula.

A Gen 1 Pokemon's stats come from base stats + DVs (0-15, fixed at birth) + stat exp (earned by
defeating mons; each defeat awards the victim's base stats) + level. The HP DV is not stored: it is
the low bit of each of the other four DVs (Atk, Def, Spd, Spc), in that order from the top.
"""
from __future__ import annotations

import math
from typing import Any

from pokeagent.explorer.kb import ROM_KB
from pokeagent.ramstructs import BattleMon, PartyMon

DV_KEYS = ("attack", "defense", "speed", "special")
STAT_KEYS = ("hp", "attack", "defense", "speed", "special")
KB_KEYS = {"hp": "hp", "attack": "atk", "defense": "def", "speed": "spd", "special": "spc"}


def dvs(mon: PartyMon | BattleMon | int) -> dict[str, int]:
    """DVs 0-15 for attack/defense/speed/special, plus hp (low bits of the other four).

    The 2-byte word is Atk<<12 | Def<<8 | Spd<<4 | Spc.
    """
    word = mon if isinstance(mon, int) else mon.dv_word
    out = {"attack": (word >> 12) & 15, "defense": (word >> 8) & 15, "speed": (word >> 4) & 15, "special": word & 15}
    out["hp"] = ((out["attack"] & 1) << 3) | ((out["defense"] & 1) << 2) | ((out["speed"] & 1) << 1) | (out["special"] & 1)
    return out


def dv_total(d: dict[str, int]) -> int:
    """Sum of the five DVs (0-75): the keep-best score."""
    return sum(d[k] for k in STAT_KEYS)


def stat_exp(mon: PartyMon) -> dict[str, int]:
    """Stat experience (0-65535 each) keyed by hp/attack/defense/speed/special."""
    return dict(zip(STAT_KEYS, mon.stat_exp))


def stat_value(base: int, dv: int, stat_exp_value: int, level: int, *, hp: bool = False) -> int:
    """Gen 1 stat: floor(((base+dv)*2 + floor(ceil(sqrt(statexp))/4)) * level / 100) + (level+10 | 5)."""
    bonus = min(math.ceil(math.sqrt(max(stat_exp_value, 0))), 255) // 4
    core = ((base + dv) * 2 + bonus) * level // 100
    return core + level + 10 if hp else core + 5


def base_stats_of(species: int) -> dict[str, int] | None:
    """Species base stats (internal species id) from the ROM-drained kb, or None without it."""
    if not ROM_KB:
        return None
    dex = int(ROM_KB.get("dex_of_internal", {}).get(str(species), 0) or 0)
    row = ROM_KB.get("species_by_dex", {}).get(str(dex))
    return {k: int(row[v]) for k, v in KB_KEYS.items()} if row else None


def computed_stats(mon: PartyMon, base: dict[str, int]) -> dict[str, int]:
    """The five stats the formula predicts for this mon; compare with mon.max_hp / mon.stats."""
    d, sx = dvs(mon), stat_exp(mon)
    return {k: stat_value(base[k], d[k], sx[k], mon.level, hp=(k == "hp")) for k in STAT_KEYS}


def ram_stats(mon: PartyMon) -> dict[str, int]:
    return dict(zip(STAT_KEYS, (mon.max_hp, *mon.stats)))


def stat_exp_yield(base: dict[str, int] | None) -> int:
    """Stat exp a defeat of this species awards across all five stats: the sum of its base stats."""
    return sum(base[k] for k in STAT_KEYS) if base else 0


def dv_text(mon: PartyMon | BattleMon) -> str:
    d = dvs(mon)
    return f"A{d['attack']} D{d['defense']} S{d['speed']} P{d['special']} H{d['hp']}"


def stat_exp_text(mon: PartyMon) -> str:
    return "/".join(str(v) for v in mon.stat_exp)


def party_summary(mon: PartyMon) -> dict[str, Any]:
    """Level, HP, DVs and stat exp for one party mon (the party-panel row)."""
    return {"species": mon.species, "level": mon.level, "hp": mon.hp, "max_hp": mon.max_hp,
            "dvs": dvs(mon), "dv_total": dv_total(dvs(mon)), "stat_exp": stat_exp(mon)}
