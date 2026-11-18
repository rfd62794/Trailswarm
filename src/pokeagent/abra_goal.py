"""The --build abra goal: catch an Abra-line member and keep it in the party.

Opt-in team build (ExplorerOptions.build == "abra"; the tools expose --build / POKEAGENT_BUILD).
Pure settle function over RAM + run state, the same shape as magikarp.magikarp_goal_settled:
sticky once an ABRA/KADABRA/ALAKAZAM is in the party, settled when the stage's step cap is spent
(plan_goal latches ``abra_skipped``) or when there is no way left to throw a ball - fewer than
BALLS_MIN balls in the bag and not enough money for the cheapest one. For every other build the
goal reads settled, so it never blocks the default route.
"""
from __future__ import annotations

from pokeagent.knowledge import team_plan
from pokeagent.knowledge.catch_math import BALLS, FALLBACK_PRICE
from pokeagent.knowledge.flee_catch import ABRA_LINE
from pokeagent.magikarp import party_species
from pokeagent.ramworld import read_money

ABRA_STEP_CAP = 3000    # steps with catch_abra open before it is settled for this run (named; tune from runs)
BALLS_MIN = 12          # under this many balls, with no money to restock, the goal is settled for this run (named; tune from runs)
BUILDS = ("", "abra")
ENV_BUILD = "POKEAGENT_BUILD"


def resolve_build(cli_build: str | None, env_build: str | None) -> str:
    """The team build: the CLI flag wins over the env var; anything else is a clear error."""
    build = cli_build if cli_build is not None else (env_build or "")
    if build not in BUILDS:
        raise ValueError(f"build must be one of {BUILDS}, got {build!r}")
    return build


def _ball_count(emu) -> int:
    """Balls in the bag by kind (the goals.bag_contents read, inlined: goals.py imports this module)."""
    n = emu.read(0xD31D)
    if not 0 < n < 21:
        return 0
    raw = emu.read_range(0xD31E, 2 * n)
    items = {raw[i]: raw[i + 1] for i in range(0, len(raw), 2)}
    return sum(items.get(i, 0) for i in BALLS.values())


def _cheapest_ball(kb) -> int:
    items = (kb or {}).get("items") or {}
    return min(int((items.get(str(i)) or {}).get("price") or FALLBACK_PRICE.get(name, 200))
               for name, i in BALLS.items())


def catch_abra_settled(emu, st: dict, seen: set, kb=None) -> bool:
    """catch_abra: settled for any build but "abra"; under it, an Abra-line species in the party
    (sticky ``had_abra``), the stage's step cap spent (``abra_skipped``), no name table to judge
    by, or fewer than BALLS_MIN balls and not enough money for the cheapest one."""
    if getattr(st.get("opts"), "build", "") != "abra":
        return True
    if st.get("had_abra") or st.get("abra_skipped"):
        return True
    names = (kb or {}).get("name_of_internal")
    if not names:
        return True  # no ROM name table: cannot judge, never block
    if any(names.get(str(s), str(s)) in ABRA_LINE for s in party_species(emu)):
        st["had_abra"] = True
        return True
    return _ball_count(emu) < BALLS_MIN and read_money(emu) < _cheapest_ball(kb)  # no balls left and no money for one


def abra_stage(ctx, goals_now_all: dict) -> dict:
    """The catch_abra stage's per-step bookkeeping (plan_goal calls it while ``--build abra`` is on):
    count the open steps, latch ``abra_skipped`` at ABRA_STEP_CAP, and log the settlement once.
    Returns the refreshed goal map when the goal's state may have changed."""
    st = team_plan.of(ctx)
    if not goals_now_all["catch_abra"]:
        ctx.abra_steps += 1
        if ctx.abra_steps > ABRA_STEP_CAP:
            ctx.abra_skipped = True
            ctx.log(f"[catch_abra: {ABRA_STEP_CAP} steps without an Abra - settled for this run]", "res")
        goals_now_all = ctx.goals()
    if st.get("catch_abra_open") and goals_now_all["catch_abra"]:
        why = "caught" if ctx.had_abra else ("step cap" if ctx.abra_skipped else "no balls")
        ctx.log(f"[catch_abra: settled - {why} after {ctx.abra_steps} steps, "
                f"{ctx.abra_encounters} Abra encounters]", "res")
    st["catch_abra_open"] = not goals_now_all["catch_abra"]
    return goals_now_all
