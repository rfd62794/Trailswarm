"""catch_list: which wild species are worth a ball. Pure functions; behaviours/catch.py consults ``catch_wanted``.

Wanted species: (a) one that can learn an HM the campaign still needs (cut, flash, surf, strength) when nobody in the
party can; (b) any unowned species while fewer than 10 are owned and a goal needing ``dex10`` is still ahead.
The HM-learnability table is kb/hm_compat.json (gitignored: ROM-derived), built from the ROM's BaseStats TM/HM bitfield by
pokeagent.knowledge.hm_compat / tools/hm_compat.py.
"""
from __future__ import annotations

import logging

from pokeagent.campaign import load_campaign
from pokeagent.knowledge import hm_compat
from pokeagent.knowledge.cut_learner import LearnerTarget, pick_target

log = logging.getLogger(__name__)

DEX_OWNED, DEX_BYTES, DEX_TARGET = 0xD2F7, 19, 10  # wPokedexOwned (verified in ram_map.json): one bit per species
HM_MOVE = {"cut": "CUT", "flash": "FLASH", "surf": "SURF", "strength": "STRENGTH"}
# Never worth a ball (Robert, 2026-11-14): a wild KAKUNA knows only Harden, while a WEEDLE trained to evolve keeps
# Poison Sting. Evolving a Weedle also registers Kakuna in the Pokedex, so the dex loses nothing.
NEVER_CATCH = frozenset({"KAKUNA"})


def wild_never_catch(name: str | None, moves) -> bool:
    """A NEVER_CATCH member that still knows only Harden (a wild catch). A KAKUNA evolved from our own
    WEEDLE keeps Poison Sting / String Shot, so it is ours to train, not the deposit pick."""
    return name in NEVER_CATCH and {m for m in moves or () if m} <= {"HARDEN"}


_warned = False


def hm_table() -> dict[str, frozenset]:
    """{hm: species names that can learn it} from kb/hm_compat.json; {} (and one log line) when there is no ROM data."""
    global _warned
    t = hm_compat.load()
    if t is None:
        if not _warned:
            _warned = True
            log.warning("catch_list: no kb/hm_compat.json and no ROM to build it - HM-learner catching is off (new-species catching still works)")
        return {}
    return t


def upcoming_needs(goals: dict) -> list[str]:
    """Capability tags (cut, flash, dex10 ...) of the campaign goals not yet met, in ladder order, without repeats."""
    out: list[str] = []
    for g in load_campaign():
        if not goals.get(g["id"]):
            out += [n for n in g.get("needs", ()) if n not in out]
    return out


def dex_owned_count(emu) -> int:
    return sum(bin(b).count("1") for b in emu.read_range(DEX_OWNED, DEX_BYTES))


def _members(party) -> list[tuple[str, tuple]]:
    """Accepts names or Combatant-like objects (``name``, ``moves``)."""
    return [(p, ()) if isinstance(p, str) else (p.name, tuple(getattr(p, "moves", ()))) for p in party]


def _party_covers(hm: str, party) -> bool:
    can = hm_table().get(hm, frozenset())
    return any(name in can or HM_MOVE[hm] in moves for name, moves in _members(party))


def catch_wanted(species: str, party, dex_owned: int, upcoming: list[str], owned: bool = False,
                 wants: dict[str, str] | None = None) -> str | None:
    """Why a ball should go on ``species`` (a reason string), or None. ``owned``: the species is already in the dex.
    ``wants``: the catch plan's species -> reason map (knowledge.catch_plan via ctx.team_wants); a planned species
    reports its plan reason after the HM check and before the dex check. A NEVER_CATCH species is never wanted."""
    if species in NEVER_CATCH:
        return None
    for hm in HM_MOVE:
        if hm in upcoming and species in hm_table().get(hm, ()) and not _party_covers(hm, party):
            return f"can learn {hm.upper()} (needed ahead, nobody in the party can)"
    if wants and species in wants:
        return wants[species]
    if not owned and dex_owned < DEX_TARGET and "dex10" in upcoming:
        return f"new species for the Pokedex ({dex_owned}/{DEX_TARGET} owned, dex10 ahead)"
    return None


def _covers(need: str, party, hm: dict) -> bool:
    """Someone in the party answers ``need`` under the given HM table (can learn it, or already knows the move)."""
    return need in HM_MOVE and any(name in (hm or {}).get(need, ()) or HM_MOVE[need] in moves
                                   for name, moves in _members(party))


def catch_target_map(goals: dict, party, hm: dict, wild_by_map: dict, here_map: int, known_maps, distance=None) -> LearnerTarget | None:
    """The map to hunt a CUT learner on (knowledge.cut_learner.pick_target): None unless ``cut`` is the first
    upcoming need that nobody in the party covers; else the nearest grass map holding a Cut-compatible species."""
    first = next((n for n in upcoming_needs(goals) if not _covers(n, party, hm)), None)
    return pick_target(here_map, known_maps, hm, wild_by_map, distance=distance) if first == "cut" else None
