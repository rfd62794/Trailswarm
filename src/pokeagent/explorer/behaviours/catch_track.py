"""catch_track: the per-(battle, species) catch-attempt record and everything written on it - the
Abra encounter's throw / no-throw / RNG notes, the flee-species jitter seeded ahead of the bag
walk, and the give-up counter for menu presses that never land a ball.

Split out of catch.py for the 300-line module cap (test_explorer_package_layering_and_size).
Everything here is behaviour-layer ctx machinery: ctx.catch_attempt, ctx.abra_pending,
ctx.cave_catch_balls, ctx.catch_switch, ctx.catch_flee.
"""
from __future__ import annotations

from pokeagent.explorer.behaviours.base import Decision
from pokeagent.explorer.context import ExplorerContext
from pokeagent.ramstructs import read_party

CATCH_BAG_PRESSES = 60   # bag presses without a throw landing before the catch sequence is abandoned (a throw is about 4 presses plus the scroll depth)
JITTER_MAX = 3           # spare B presses before a flee species' bag walk (RNG decorrelation; seeded per battle)
RNG_ADDRS = (0xFFD3, 0xFFD4, 0xFF04)  # hRandomAdd, hRandomSub, rDIV (ram_map.json): the bytes the ball's Random calls draw


def throw_jitter(battles: int, step: int, thrown: int) -> int:
    """0..JITTER_MAX spare B presses ahead of this throw's bag walk. The emulator replays the ROM's RNG:
    hRandomAdd folds rDIV in every frame, so the same press cadence lands the ball's Random calls on the
    same bytes (2026-11-18 real-ROM FAIL: 0/24 full-HP throws where ~30% each was expected - under 1%).
    A per-encounter count of do-nothing presses shifts the consuming frame; deterministic inside a run."""
    return (battles * 7 + step + thrown) % (JITTER_MAX + 1)


def abra_no_throw(ctx: ExplorerContext, why: str) -> None:
    """Why this Abra encounter will not get a ball (the last decision wins): abra_hunt's resolve line
    says it once - a reason for EVERY encounter that ends without a throw (2026-11-18 real-ROM FAIL:
    44 of 48 encounters had none and the log gave no clue why)."""
    pend = ctx.abra_pending
    if pend is not None:
        pend["no_throw"] = why


def note_thrown(ctx: ExplorerContext, ca: dict, pend) -> None:
    """A ball really left the bag this battle: the attempt record and the Abra encounter both count it."""
    ca["thrown"] = ca.get("thrown", 0) + 1
    if pend is not None:
        pend["thrown"] = pend.get("thrown", 0) + 1


def attempt(ctx: ExplorerContext, species: int, e_lvl: int, ratio: float, dex_no: int, ball: str | None,
            owned: bool) -> dict:
    """The one catch_attempt record per (battle, species): refreshed in place so its ``step`` (the turn signature's
    input) stays put, and carrying the bag-press count the cap and Battle's item_list_close yield read.
    ``owned0``/``party0`` pin what was true at the attempt's start: the dex bit says 'owned', never 'caught THIS
    battle' - an already-owned species (a boxed catch) read 'SUCCEEDED' on a battle where no ball was even thrown
    (2026-11-18 real-ROM FAIL)."""
    ca = ctx.catch_attempt
    if not ca or ca.get("battle") != ctx.battles or ca.get("species") != species:
        ca = ctx.catch_attempt = {"species": species, "level": e_lvl, "step": ctx.step, "dex": dex_no,
                                  "battle": ctx.battles, "presses": 0, "last": ctx.step,
                                  "owned0": owned,
                                  "party0": tuple(getattr(m, "species", None) for m in read_party(ctx.emu))}
    ca["hp_pct"] = round(ratio, 2)
    if ball is not None:
        ca["ball"] = ball
    return ca


def ball_landed(ctx: ExplorerContext, ca: dict, pend, species: int, sp_name: str, e_lvl: int,
                ratio: float, ball_name: str) -> None:
    """The A on the ball row landed: count the throw for the cave cap and the Abra record, log the
    line with the RNG bytes the roll draws from (hRandomAdd / hRandomSub / rDIV - per-encounter
    evidence for the cadence-correlation hypothesis), and re-arm the jitter for the next bag walk."""
    n = ctx.cave_catch_balls.get(species, 0) + 1
    ctx.cave_catch_balls[species] = n
    note_thrown(ctx, ca, pend)
    rng = tuple(ctx.emu.read(a) for a in RNG_ADDRS)
    if pend is not None:
        pend.setdefault("rng", []).append(rng)
    ctx.log(f"[catch: throwing {ball_name} {n} at {sp_name} L{e_lvl} ({ratio:.0%} HP) on map "
            f"0x{ctx.view.m:02X} - rng {rng[0]:02X}/{rng[1]:02X}/div{rng[2]:02X}]", "res")
    if "jitter" in ca:
        ca["jitter"] = throw_jitter(ctx.battles, ctx.step, n)


def bag_press(ctx: ExplorerContext, ca: dict, dec: Decision, key, sp_name) -> Decision:
    """Count a bag press; a throw landing resets the count; too many presses without one abandons the sequence."""
    ca["last"] = ctx.step
    ca["presses"] = 0 if dec.rule == "item_use" else ca["presses"] + 1
    if ca["presses"] > CATCH_BAG_PRESSES:
        ctx.catch_switch = (key, 10**6)   # the existing give-up marker: no new hint for the rest of this battle
        ctx.catch_flee = (key, False)     # the catch is off: potion / switch / flee are this battle's again
        abra_no_throw(ctx, f"bag sequence gave up after {CATCH_BAG_PRESSES} presses")
        ctx.catch_mode, ctx.catch_hint = False, None
        ctx.log(f"[catch: bag sequence gave up after {CATCH_BAG_PRESSES} presses without a throw on {sp_name}; fighting on]", "res")
        return Decision("B", "catch_bag_failed", "catch bag sequence abandoned: backing out of the menu")
    return dec
