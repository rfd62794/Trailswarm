"""The --build abra goal: catch an Abra-line member and keep it in the party.

Opt-in team build (ExplorerOptions.build == "abra"; the tools expose --build / POKEAGENT_BUILD).
Pure settle function over RAM + run state, the same shape as magikarp.magikarp_goal_settled:
sticky once an ABRA/KADABRA/ALAKAZAM is in the party, settled when the stage's step cap is spent
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
from pokeagent.ramworld import read_money

ABRA_STEP_CAP = 3000    # steps with catch_abra open before it is settled for this run (named; tune from runs)
BALLS_MIN = 12          # under this many balls the goal buys Poke Balls at a Mart first (restock machinery; tune from runs)
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


def catch_abra_settled(emu, st: dict, seen: set, kb=None) -> bool:
    """catch_abra: settled for any build but "abra"; under it, an Abra-line species in the party
    (sticky ``had_abra``), the stage's step cap spent (``abra_skipped``), no name table to judge
    by, or an empty ball bag with no money for one - the ONLY "gave up" settle: short of balls but
    able to buy, the run restocks at a Mart first (abra_hunt arms the restock trip) and hunts on.
    ``abra_settle`` records why, so the run log and the give-up flag tell a catch from a failure."""
    if getattr(st.get("opts"), "build", "") != "abra":
        return True
    if st.get("had_abra"):
        st["abra_settle"] = "caught"
        return True
    if st.get("abra_skipped"):
        st["abra_settle"] = "step cap"
        return True
    names = (kb or {}).get("name_of_internal")
    if not names:
        st["abra_settle"] = "no name table"
        log = st.get("log")   # check_goals hands in the ctx: under the build this is not a silent settle
        if callable(log) and not st.get("abra_no_kb_logged"):
            st["abra_no_kb_logged"] = True
            log("[catch_abra: no kb name table - an Abra catch cannot be judged; the goal settles open]", "res")
        return True  # no ROM name table: cannot judge, never block - but say so out loud under --build abra
    if any(names.get(str(s), str(s)) in ABRA_LINE for s in party_species(emu)):
        st["had_abra"] = True
        st["abra_settle"] = "caught"
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
