"""What the Explorer's behaviours call at the three decision points. Each returns the Explorer's own answer when the
bandit is off (ctx.bandit is None) or fails: a bandit error must never stop a run."""
from __future__ import annotations

from pokeagent.bandit import points as pt
from pokeagent.explorer.decisions import goal_stage
from pokeagent.explorer.perceive import party_hp
from pokeagent.goals import bag_contents


FIGHT_FLOOR = 0.25  # shield: the bandit never chooses fight below this lead HP fraction


def catch_target(ctx, species: int, balls: int) -> bool:
    """The catch rule's own test (lazy import: the behaviours package imports this module)."""
    from pokeagent.explorer.behaviours.battle_run import catch_target as rule
    return rule(ctx, species, balls)


def _safe(ctx, name: str, exc: Exception) -> None:
    ctx.log(f"[bandit {name} skipped: {exc!r}]", "res")


def wild_flee(ctx, rule_flee: bool) -> bool:
    """Flee this wild battle? ``rule_flee`` is the Explorer's own answer (weak, hurry, cave run)."""
    drv = ctx.bandit
    if drv is None:
        return rule_flee
    try:
        hp, mx = party_hp(ctx.emu)
        if mx and hp / mx < FIGHT_FLOOR:
            return True  # shield: too hurt to fight; no decision, no episode
        if catch_target(ctx, ctx.emu.read(0xCFE5), bag_contents(ctx.emu).get(0x04, 0)):
            return rule_flee  # the rules would try a catch here: not the bandit's call
        def key() -> str:
            return pt.context_key("wild_battle", goal_stage(ctx.goals()), ctx.view.m, hp, mx, pt.wild_gap(ctx))
        return drv.decide("wild_battle", ctx.battles, key, "flee" if rule_flee else "fight") == "flee"
    except Exception as exc:  # noqa: BLE001
        _safe(ctx, "wild_battle", exc)
        return rule_flee


def heal_push_on(ctx, goals: dict, hp: int, mx: int) -> bool:
    """Skip the planner's walk to a Pokecenter for this low-HP spell? Only where the planner's heal rule is live."""
    drv = ctx.bandit
    if drv is None:
        return False
    try:
        if not (goals.get("deliver_parcel") and pt.heal_eligible(ctx, hp, mx)):
            drv.clear("heal")
            return False
        def key() -> str:
            return pt.context_key("heal", goal_stage(goals), ctx.view.m, hp, mx, pt.train_gap(ctx, ctx.train_need))
        return drv.decide("heal", "low", key, "heal_now") == "push_on"
    except Exception as exc:  # noqa: BLE001
        _safe(ctx, "heal", exc)
        return False


def train_need(ctx, goals: dict, need: int) -> int:
    """The training target, or 0 (skip the gate) when the bandit says skip while the lead is below it."""
    drv = ctx.bandit
    if drv is None:
        return need
    try:
        if not pt.train_eligible(ctx, need):
            drv.clear("train")
            return need
        def key() -> str:
            hp, mx = party_hp(ctx.emu)
            return pt.context_key("train", goal_stage(goals), ctx.view.m, hp, mx, pt.train_gap(ctx, need))
        return 0 if drv.decide("train", "need", key, "grind") == "skip" else need
    except Exception as exc:  # noqa: BLE001
        _safe(ctx, "train", exc)
        return need
