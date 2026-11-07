"""HM and TM teaching: who learns it, and which move it overwrites. The screen flow (and its YES/NO guard) is teach_flow.py.

HMs: teach CUT / SURF / STRENGTH / FLASH when the campaign still needs the capability and nobody in the party knows the move.
Learner = a species that can learn it (kb/hm_compat.json); prefer a free move slot, then a mon that is not the fighter, then the
cheapest overwrite. Shield: the overwritten move is never an HM the campaign needs, never the only damaging move of the type that
hits the next boss best; if every move of a candidate is protected the candidate is skipped.
TMs: only with ``enabled`` (off by default), only on the fighter, only when the TM move is worth TM_GAIN times the move it replaces.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from pokeagent.explorer.item_policies import ids
from pokeagent.explorer.item_policies.moves_shield import Info, _value, choose_overwrite, protected_moves
from pokeagent.explorer.item_policies.view import MAGIKARP, Mon

TM_GAIN = 1.5
TM_NAME = (  # TM01..TM50 in order (pokered)
    "MEGA PUNCH", "RAZOR WIND", "SWORDS DANCE", "WHIRLWIND", "MEGA KICK", "TOXIC", "HORN DRILL", "BODY SLAM", "TAKE DOWN", "DOUBLE-EDGE",
    "BUBBLEBEAM", "WATER GUN", "ICE BEAM", "BLIZZARD", "HYPER BEAM", "PAY DAY", "SUBMISSION", "COUNTER", "SEISMIC TOSS", "RAGE",
    "MEGA DRAIN", "SOLARBEAM", "DRAGON RAGE", "THUNDERBOLT", "THUNDER", "EARTHQUAKE", "FISSURE", "DIG", "PSYCHIC", "TELEPORT",
    "MIMIC", "DOUBLE TEAM", "REFLECT", "BIDE", "METRONOME", "SELFDESTRUCT", "EGG BOMB", "FIRE BLAST", "SWIFT", "SKULL BASH",
    "SOFTBOILED", "DREAM EATER", "SKY ATTACK", "REST", "THUNDER WAVE", "PSYWAVE", "EXPLOSION", "ROCK SLIDE", "TRI ATTACK", "SUBSTITUTE")


@dataclass(frozen=True)
class HmPlan:
    item: int
    tag: str                 # "cut" / "surf" / ... or "tm"
    move: str
    learner: int             # party slot
    forget_slot: int | None  # move slot (0-3) to overwrite, None = a free slot exists
    forget_move: str | None
    reason: str

    def triple(self) -> tuple[int, int, str]:
        return self.item, self.learner, self.reason


def _best_candidate(party: list[Mon], eligible: Callable[[Mon], bool], needed_hm_moves: set[str], boss_types, info: Info, chart: dict,
                    fighter: int | None):
    """(mon, forget_slot|None) with the best rank, or None. Free slot > not the fighter > cheapest overwrite."""
    ranked = []
    for mon in party:
        if mon.species == MAGIKARP or not eligible(mon):
            continue
        if len(mon.moves) < 4:
            ranked.append(((0, mon.slot == fighter, 0.0), mon, None))
            continue
        slot = choose_overwrite(mon.moves, protected_moves(mon.moves, needed_hm_moves, boss_types, info, chart), info)
        if slot is not None:
            ranked.append(((1, mon.slot == fighter, _value(mon.moves[slot], info)), mon, slot))
    return min(ranked, key=lambda r: r[0], default=None)


def plan_hm(*, bag: dict[int, int], party: list[Mon], needs: list[str], learners: dict[str, frozenset], boss_types: list[tuple[str, ...]],
            info: Info, chart: dict) -> HmPlan | None:
    needed_moves = {ids.HM_MOVE[t] for t in needs if t in ids.HM_MOVE}
    fighter = _fighter(party)
    for tag in needs:
        item = ids.HM_BY_TAG.get(tag)
        if item is None or bag.get(item, 0) <= 0:
            continue
        move = ids.HM_MOVE[tag]
        if any(move in m.moves for m in party):
            continue  # somebody already knows it
        pick = _best_candidate(party, lambda m, t=tag: m.species in learners.get(t, ()), needed_moves, boss_types, info, chart, fighter)
        if pick:
            _, mon, slot = pick
            fm = mon.moves[slot] if slot is not None else None
            return HmPlan(item, tag, move, mon.slot, slot, fm,
                          f"campaign needs {tag.upper()}, nobody knows it: {ids.name_of(item)} -> {mon.species} L{mon.level}"
                          + (f", overwriting {fm}" if fm else ", free move slot"))
    return None


def _fighter(party: list[Mon]) -> int | None:
    from pokeagent.explorer.item_policies.view import fighter_slot_of
    return fighter_slot_of(party)


def should_use(**kw) -> tuple[int, int, str] | None:
    plan = plan_hm(**kw)
    return plan.triple() if plan else None


def plan_tm(*, enabled: bool, bag: dict[int, int], party: list[Mon], can_learn: Callable[[int, str], bool], needed_hm_moves: set[str],
            boss_types: list[tuple[str, ...]], info: Info, chart: dict) -> HmPlan | None:
    """A TM on the fighter, behind the flag. ``can_learn(tm_number, species)``: the ROM TM compatibility (not extracted yet: no TM
    teaching without it)."""
    fighter = _fighter(party)
    if not enabled or fighter is None:
        return None
    mon = party[fighter]
    if mon.species == MAGIKARP:
        return None
    best = None
    for item, qty in bag.items():
        if qty <= 0 or not ids.is_tm(item):
            continue
        n = item - ids.TM01 + 1
        move = TM_NAME[n - 1]
        if move in mon.moves or not can_learn(n, mon.species) or _value(move, info) <= 0:
            continue
        slot = None
        if len(mon.moves) >= 4:
            slot = choose_overwrite(mon.moves, protected_moves(mon.moves, needed_hm_moves, boss_types, info, chart), info)
            if slot is None or _value(move, info) < TM_GAIN * _value(mon.moves[slot], info):
                continue
        if best is None or _value(move, info) > best[0]:
            best = (_value(move, info), item, move, slot)
    if best is None:
        return None
    _, item, move, slot = best
    fm = mon.moves[slot] if slot is not None else None
    return HmPlan(item, "tm", move, mon.slot, slot, fm, f"{ids.name_of(item)} {move} on the fighter {mon.species}" + (f", overwriting {fm}" if fm else ""))
