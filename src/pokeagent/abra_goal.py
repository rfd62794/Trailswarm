"""The --build abra goal: catch an Abra-line member and keep it in the party.

Opt-in team build (ExplorerOptions.build == "abra"; the tools expose --build / POKEAGENT_BUILD).
Pure settle function over RAM + run state, the same shape as magikarp.magikarp_goal_settled:
sticky once an ABRA/KADABRA/ALAKAZAM was GAINED this run (party or PC box - a full party's catch
lands in the box), settled when the stage's step cap is spent
(plan_goal latches ``abra_skipped``) or when there is no way left to throw a ball - an EMPTY ball
bag with no money for the cheapest one. Short of BALLS_MIN but able to buy, the run restocks at a
Mart first (abra_hunt arms the restock trip); broke with throws still in the bag, it hunts on.
For every other build the goal reads settled, so it never blocks the default route.
"""
from __future__ import annotations

from pokeagent.knowledge import team_plan
from pokeagent.knowledge.catch_math import BALLS, FALLBACK_PRICE
from pokeagent.knowledge.flee_catch import ABRA_LINE
from pokeagent.magikarp import party_species
from pokeagent.ram_symbols import BOX_COUNT_ADDR, BOX_SPECIES
from pokeagent.ramworld import read_money

ABRA_STEP_CAP = 3000    # steps with catch_abra open before it is settled for this run (named; tune from runs)
BALLS_MIN = 5           # under this many balls the goal buys Poke Balls at a Mart first. = the machinery's
                        # own low-water mark (explorer/restock.py + economy/shopping.py BALL_MIN): an armed
                        # trip always buys balls, and one trip's BALL_BUY lot (10) clears it - a 12 could
                        # never be reached by a single buy (2026-11-18 round-4 note; tune from runs)
BUILDS = ("", "abra")
ENV_BUILD = "POKEAGENT_BUILD"


def resolve_build(cli_build: str | None, env_build: str | None) -> str:
    """The team build: the CLI flag wins over the env var; anything else is a clear error."""
    build = cli_build if cli_build is not None else (env_build or "")
    if build not in BUILDS:
        raise ValueError(f"build must be one of {BUILDS}, got {build!r}")
    return build


def ball_count(emu) -> int:
    """Balls in the bag by kind (the goals.bag_contents read, inlined: goals.py imports this module)."""
    n = emu.read(0xD31D)
    if not 0 < n < 21:
        return 0
    raw = emu.read_range(0xD31E, 2 * n)
    items = {raw[i]: raw[i + 1] for i in range(0, len(raw), 2)}
    return sum(items.get(i, 0) for i in BALLS.values())


def cheapest_ball(kb) -> int:
    """Price of the cheapest ball kind (the POKE BALL): kb items table, else FALLBACK_PRICE."""
    items = (kb or {}).get("items") or {}
    return min(int((items.get(str(i)) or {}).get("price") or FALLBACK_PRICE.get(name, 200))
               for name, i in BALLS.items())


def can_afford_ball(emu, kb) -> bool:
    """The purse still buys one ball: the errand arm and the "no balls" settle both ask this."""
    return read_money(emu) >= cheapest_ball(kb)


BOX_CAPACITY = 20      # MONS_PER_BOX (pokered)


def box_species(emu) -> list[int]:
    """Species ids in the current PC box: wBoxCount / wBoxSpecies, the 0xFF-terminated species LIST
    (verified in ram_map.json) - not wBoxMons, whose 33-byte structs put level/move/catch-rate bytes
    where a read like that sees species (2026-11-18 round-7 audit). A catch lands here when the
    party is full - RBY sends it over on its own, no deposit prompt - so a full party's caught
    Abra shows up in the box, not the party."""
    n = min(emu.read(BOX_COUNT_ADDR), BOX_CAPACITY)
    return [b for b in emu.read_range(BOX_SPECIES, n) if b != 0xFF] if n > 0 else []


def owned_species(emu) -> dict[int, int]:
    """The owned-mon pool as {internal species id: count}: party and current PC box together - a
    full party's catch lands in the box, and a deposit moves a member without gaining one."""
    counts: dict[int, int] = {}
    for s in party_species(emu) + box_species(emu):
        counts[s] = counts.get(s, 0) + 1
    return counts


def gained_abra(owned_now: dict[int, int], owned0: dict[int, int], names) -> bool:
    """The Abra LINE's total in ``owned_now`` tops the run-start snapshot ``owned0``: gained THIS
    run. One family total, not per species - a start-state Abra that EVOLVED into Kadabra keeps the
    total at 1 and must not settle the goal (2026-11-19 review); a pre-existing boxed/party Abra
    (equal count) never counts either."""
    names = names or {}
    line = lambda owned: sum(n for s, n in owned.items() if names.get(str(s), str(s)) in ABRA_LINE)
    return line(owned_now) > line(owned0)


def catch_abra_settled(emu, st: dict, seen: set, kb=None) -> bool:
    """catch_abra: settled for any build but "abra"; under it, an Abra-line species GAINED this run
    in the party or the PC box (sticky ``had_abra`` - a full party boxes the catch, still ours),
    the stage's step cap spent (``abra_skipped``), no name table to judge
    by, or an empty ball bag with no money for one - the ONLY "gave up" settle: short of balls but
    able to buy, the run restocks at a Mart first (abra_hunt arms the restock trip) and hunts on.
    ``abra_settle`` records why, so the run log and the give-up flag tell a catch from a failure.

    "Gained this run" is judged against ``abra_owned0`` - the party+box species counts snapshotted
    at this function's first call, which IS the startup goal scan (seed_initial_goals runs it
    before the first decision). A start state that already holds an Abra-line mon (the real
    nugget_bridge.state boxes one) must not satisfy the goal or seed it into initial_goals:
    the hunt still has to produce its own (2026-11-18 round-7)."""
    if getattr(st.get("opts"), "build", "") != "abra":
        return True
    if st.get("had_abra"):
        st["abra_settle"] = "caught"
        return True
    if st.get("abra_skipped"):
        st["abra_settle"] = "step cap"
        return True
    owned0 = st.get("abra_owned0")
    if owned0 is None:
        st["abra_owned0"] = owned0 = owned_species(emu)  # the baseline every later check compares against
    names = (kb or {}).get("name_of_internal")
    if not names:
        st["abra_settle"] = "no name table"
        log = st.get("log")   # check_goals hands in the ctx: under the build this is not a silent settle
        if callable(log) and not st.get("abra_no_kb_logged"):
            st["abra_no_kb_logged"] = True
            log("[catch_abra: no kb name table - an Abra catch cannot be judged; the goal settles open]", "res")
        return True  # no ROM name table: cannot judge, never block - but say so out loud under --build abra
    if gained_abra(owned_species(emu), owned0, names):
        st["had_abra"] = True
        st["abra_settle"] = ("caught" if any(names.get(str(s), str(s)) in ABRA_LINE
                                             for s in party_species(emu)) else "caught (boxed)")
        return True
    if ball_count(emu) == 0 and not can_afford_ball(emu, kb):
        st["abra_settle"] = "no balls and no money"
        return True  # nothing to throw and nothing to buy with: gave up
    return False


def abra_stage(ctx, goals_now_all: dict) -> dict:
    """The catch_abra stage's per-step bookkeeping (plan_goal calls it while ``--build abra`` is on):
    count the open steps, latch ``abra_skipped`` at ABRA_STEP_CAP, and log the settlement once - a
    settle without an Abra is a give-up (``abra_gave_up``), never a success. Returns the refreshed
    goal map when the goal's state may have changed."""
    st = team_plan.of(ctx)
    if not goals_now_all["catch_abra"]:
        ctx.abra_steps += 1
        if ctx.abra_steps > ABRA_STEP_CAP:
            ctx.abra_skipped = True
            ctx.log(f"[catch_abra: {ABRA_STEP_CAP} steps without an Abra - gave up for this run]", "res")
        goals_now_all = ctx.goals()
    if st.get("catch_abra_open") and goals_now_all["catch_abra"]:
        why = "caught" if ctx.had_abra else f"gave up - {getattr(ctx, 'abra_settle', '') or 'settled'}"
        ctx.log(f"[catch_abra: settled - {why} after {ctx.abra_steps} steps, "
                f"{ctx.abra_encounters} Abra encounters]", "res")
    if (goals_now_all["catch_abra"] and not ctx.had_abra
            and getattr(getattr(ctx, "opts", None), "build", "") == "abra"
            and "catch_abra" not in getattr(ctx, "initial_goals", ())):
        ctx.abra_gave_up = True  # settled for the build without an Abra: a give-up, not a success
                                # (a seeded-complete goal - the catch happened in an earlier segment)
    st["catch_abra_open"] = not goals_now_all["catch_abra"]
    return goals_now_all
