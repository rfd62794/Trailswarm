"""Grind budget: the training gate (planner: 'level < _train_level -> go grind') must not hold the run forever.

Lift the gate for a goal when grinding stops paying: N training battles or M training steps without a level gain on the lead,
the lead at or above the training route's top wild level + 6 (XP per fight is negligible), or blackouts in a row while training.
"""
from __future__ import annotations

from pokeagent.knowledge import blackout_tax

GRIND_BATTLES = 25
GRIND_BATTLES_GYARADOS = 120  # the gyarados stage only: a Magikarp level costs 60+ shared-XP fights past ~L15
GRIND_STEPS = 2500
GRIND_BLACKOUTS = 2
CEILING_MARGIN = 6   # lead this far above the route's top wild level: a fight there gives negligible XP


def best_level(lead: int, party) -> int:
    """The level the budget tracks: the strongest real slot (a weak lead would 'spend' the budget while the team levels).
    Fainted slots are not excluded: Combatant carries max HP only, no current HP, at the call site."""
    return max([lead, *(c.level for c in party or ())])


def stall_keeps_hold(reason: str) -> bool:
    """A lift for 'N battles/steps without a level gain' must not open the gym to an unready team: leave and grind.
    Ceiling and blackout lifts still release the hold (nothing left to gain / training is losing)."""
    return "without a level gain" in (reason or "")


STALL_HOLD_CAP = 6000  # plan steps the gym stays shut after a stall lift before the hold gives up


def stall_hold_holds(st: dict, reason: str, step: int, blackouts: int) -> bool:
    """True while a stall lift should keep the gym hold. Hard escapes so the run is never locked out forever:
    STALL_HOLD_CAP steps since the hold began, or a blackout while held (grinding is losing). ``st`` carries the
    hold's start (reset when the gate is not lifted: call ``st.pop('stall_hold', None)`` then)."""
    if not stall_keeps_hold(reason):
        return False
    start = st.setdefault("stall_hold", (step, blackouts))
    return step - start[0] < STALL_HOLD_CAP and blackouts <= start[1]


def battle_outcome(*, trainer: bool, start: tuple, end: tuple, party_count: int) -> tuple[bool, bool]:
    """(won, moved_away) from where the battle began and where it ended.
    A trainer battle cannot be fled, and a loss warps you to another MAP (a Pokecenter): so a trainer fight is won when we
    are still on the battle's map, even if the trainer walked us a tile or a door away (2026-11-06: five S.S. Anne wins were
    recorded as lost 'with HP left', and counted as blackouts). A wild fight keeps the exact-tile test: staying put is a win
    or a flee (not told apart here), moving off the tile is a blackout."""
    if trainer:
        gone = end[0] != start[0]
        return party_count > 0 and not gone, party_count > 0 and gone
    return party_count > 0 and end == start, party_count > 0 and end != start


def outcome_of(*, trainer: bool, won: bool, moved_away: bool, party_count: int) -> str:
    """One word for how the battle ended: "won" | "lost" | "fled" | "blackout".
    A loss that warped us away is a blackout; so is ending with no party standing (party_count == 0) even without a
    warp. A wild fight we survived without winning is a flee; a trainer fight we survived without winning is a "lost"
    (rare in Gen 1 - a script moved us - so it gets its own label instead of being folded into another)."""
    if won:
        return "won"
    if moved_away or party_count == 0:
        return "blackout"
    return "lost" if trainer else "fled"


def record_battle_result(ctx, *, won: bool, moved_away: bool, trainer: bool = False) -> None:
    """Blackouts in a row: a lost battle that warped us away counts, a win resets, a flee (same spot) changes nothing.
    The same outcome also feeds the stage's blackout tax in the shared learned data when ctx.stage_goal is set:
    ANY blackout counts against the stage, but only a won TRAINER battle decays it - wild wins are cheap and
    would erase the tax within a few steps (a flee changes nothing, as today)."""
    if won:
        ctx.blackouts_row = 0
    elif moved_away:
        ctx.blackouts_row = ctx.blackouts_row + 1
    goal = getattr(ctx, "stage_goal", None)
    if goal:
        if moved_away and not won:
            blackout_tax.on_blackout(ctx.mem.data, goal)
        elif won and trainer:
            blackout_tax.on_win(ctx.mem.data, goal)


class GrindBudget:
    """Per-goal counters of training effort since the lead last gained a level."""

    def __init__(self) -> None:
        self._s: dict[str, dict] = {}
        self._lifted: dict[str, str] = {}

    def lifted(self, goal: str) -> bool:
        return goal in self._lifted

    def reason(self, goal: str) -> str:
        return self._lifted.get(goal, "")

    def update(self, goal: str, *, level: int, step: int, battles: int, blackouts: int, training: bool,
               ceiling: int | None = None, max_battles: int = GRIND_BATTLES) -> str | None:
        """Feed one planning step; returns the reason the first time the gate for `goal` is lifted, else None."""
        if goal in self._lifted:
            return None
        s = self._s.setdefault(goal, {"level": level, "step": step, "battles": battles, "steps_in": 0, "battles_in": 0})
        if level > s["level"]:
            s.update(level=level, steps_in=0, battles_in=0)
        if training:
            s["steps_in"] += max(0, step - s["step"])
            s["battles_in"] += max(0, battles - s["battles"])
        s["step"], s["battles"] = step, battles
        if not training:
            return None
        why = None
        if s["battles_in"] >= max_battles:
            why = f"{max_battles} battles without a level gain (stuck at L{level})"
        elif s["steps_in"] >= GRIND_STEPS:
            why = f"{GRIND_STEPS} steps without a level gain (stuck at L{level})"
        elif ceiling is not None and level >= ceiling + CEILING_MARGIN:
            why = f"lead L{level} is {CEILING_MARGIN}+ levels above the route's wild ceiling L{ceiling}: no XP left to grind"
        elif blackouts >= GRIND_BLACKOUTS:
            why = f"{blackouts} blackouts in a row while training"
        if why:
            self._lifted[goal] = why
        return why
