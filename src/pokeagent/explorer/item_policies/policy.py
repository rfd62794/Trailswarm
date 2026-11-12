"""policy: the world snapshot -> the one item use to act on now (or None). The only module here that touches the context; every rule
it calls is a pure function with its own shield. Priority: HM / TM teaching, vitamins, stones, rare candy, repel, bicycle."""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path

from pokeagent.explorer import catch_list
from pokeagent.explorer.item_policies import hm_teach, ids, key_items, rare_candy, repel, stones, vitamins
from pokeagent.explorer.item_policies.hm_teach import HmPlan
from pokeagent.explorer.item_policies.moves_shield import default_chart, default_info, protected_moves
from pokeagent.explorer.item_policies.view import Mon, fighter_slot_of, read_mons
from pokeagent.goals import GOALS, bag_contents
from pokeagent.knowledge import trainers
from pokeagent.knowledge.party import Combatant, our_party, trainer_mon
from pokeagent.party_view import read_party_view
from pokeagent.ram_symbols import SPECIES_MAGIKARP

EVOLVE_SCORE_SLACK = 0.02   # an evolved form may score this much below the unevolved one and still count as 'not worse'
CANDIDATES = frozenset({ids.RARE_CANDY, ids.BICYCLE, *ids.VITAMIN_STAT, *ids.STONES, *ids.REPELS, *ids.HM_BY_TAG.values()})


@dataclass(frozen=True)
class Pick:
    item: int
    category: str            # key_items.CATEGORIES-style: rare_candy / vitamin / stone / hm / tm / repel / key_item
    slot: int | None         # party target (None: the item takes none)
    reason: str
    kind: str                # "party" (item -> party pick), "self" (item acts alone), "teach" (item -> learner -> move flow)
    plan: HmPlan | None = None


def has_candidates(bag: dict[int, int], tms: bool) -> bool:
    return any(i in CANDIDATES or (tms and ids.is_tm(i)) for i, q in bag.items() if q > 0)


def tm_can_learn(tm_number: int, species: str) -> bool:
    """TM compatibility is not extracted from the ROM yet (kb/hm_compat.json holds the HM bits only): no TM is ever taught."""
    return False


def next_boss(goals: dict, party: list[Combatant]) -> list[Combatant]:
    from pokeagent.explorer.training import stage_goal
    goal = stage_goal(goals)
    if goal is None:
        return []
    boss = trainers.boss_party(goal, starter_names=[c.name for c in party]) or (trainers.strongest_on_mt_moon() if goal == "to_mt_moon" else [])
    return [c for lv, n in boss if (c := trainer_mon(n, lv))]


def boss_is_next(goals: dict) -> bool:
    from pokeagent.explorer.training import BOSS_LABEL
    unmet = next((g for g in GOALS if not goals.get(g)), None)
    return unmet in BOSS_LABEL and unmet != "to_mt_moon"


def _grind_minutes(ctx, goals: dict, party: list[Combatant]) -> float | None:
    try:
        from pokeagent.explorer.training import stage_goal
        atlas = json.loads((Path(ctx.run_dir).parent / "grind_atlas.json").read_text(encoding="utf-8")).get("atlas") or {}
        goal = stage_goal(goals)
        view = read_party_view(ctx.emu)
        f = view.fighter()   # the lead, or the strongest non-Magikarp while a trainee is in the party
        pos = sum(1 for s in view.slots[:f.index] if s.species != SPECIES_MAGIKARP) if f is not None else 0
        c = party[pos] if pos < len(party) else party[0]  # the fighter's entry in the Magikarp-filtered list
        return rare_candy.atlas_minutes(atlas, c.name, goal, c.level, rare_candy.STEPS_PER_MIN) if goal and party else None
    except (OSError, ValueError, KeyError, IndexError):
        return None


def _compare(goals: dict, party: list[Combatant]):
    from pokeagent.explorer.training import readiness_for
    before = readiness_for(goals, party)

    def compare(mon: Mon, into: str):
        evo = trainer_mon(into, mon.level)
        i = next((k for k, c in enumerate(party) if c.name == mon.species and c.level == mon.level), None)
        if before is None or evo is None or i is None:
            return None
        after = readiness_for(goals, [*party[:i], replace(evo, moves=party[i].moves), *party[i + 1:]])
        return None if after is None else after.score >= before.score - EVOLVE_SCORE_SLACK
    return compare


def _learns_at(species: str, level: int) -> list:
    from pokeagent.knowledge.kb import table
    return [m for lv, m in (table(None, "learnsets").get(species) or {}).get("learnset", []) if lv == level]


def trip_kind(ctx) -> str | None:
    """'goal' while par_follow is walking a purposeful goal leg (its press was made last step); the planner's why-string is not kept anywhere."""
    from pokeagent.explorer.par_follow import training
    st = ctx.par
    if st is None or st.last is None or ctx.step - st.last[2] > 3 or ctx.center_intent or ctx.shop_intent or training(ctx):
        return None
    return "goal"


def choose(ctx) -> Pick | None:
    emu = ctx.emu
    bag = {i: q for i, q in bag_contents(emu).items() if ctx.item_cooldown.get(i, 0) <= ctx.step}
    if not has_candidates(bag, ctx.opts.item_tms):
        return None
    party = read_mons(emu)
    if not party:
        return None
    goals = ctx.goals()
    combatants = [c for c in our_party(emu) if c.name != "MAGIKARP"]
    boss = next_boss(goals, combatants)
    boss_types, info, chart = [c.types for c in boss], default_info, default_chart()
    needs = catch_list.upcoming_needs(goals)
    if goals.get("hm01_cut") and not goals.get("cut_taught") and "cut" not in needs:
        needs.append("cut")  # HM01 acquired and CUT not known yet: teach it even when no later goal lists the capability
    needed_hm = {ids.HM_MOVE[t] for t in needs if t in ids.HM_MOVE}

    plan = hm_teach.plan_hm(bag=bag, party=party, needs=needs, learners=catch_list.hm_table(), boss_types=boss_types, info=info, chart=chart)
    if plan:
        return Pick(plan.item, "hm", plan.learner, plan.reason, "teach", plan)
    for tag in hm_teach.stranded_hms(bag=bag, party=party, needs=needs, learners=catch_list.hm_table()):
        if tag not in ctx.item_notes:
            ctx.item_notes.add(tag)
            ctx.log(f"[use_items: {ids.name_of(ids.HM_BY_TAG[tag])} ({tag.upper()}) is in the bag but no party member can learn it; "
                    f"the catch list now wants a {tag.upper()}-capable species]", "res")
    plan = hm_teach.plan_tm(enabled=ctx.opts.item_tms, bag=bag, party=party, can_learn=tm_can_learn, needed_hm_moves=needed_hm,
                            boss_types=boss_types, info=info, chart=chart)
    if plan:
        return Pick(plan.item, "tm", plan.learner, plan.reason, "teach", plan)

    if (hit := vitamins.should_use(bag=bag, party=party)):
        return Pick(hit[0], "vitamin", hit[1], hit[2], "party")

    needed = {m.slot: protected_moves(m.moves, needed_hm, boss_types, info, chart) for m in party}
    if (hit := stones.should_use(bag=bag, party=party, evolutions=stones.evolve_table(), needed=needed,
                                 compare=_compare(goals, combatants), learns_at=_learns_at)):
        return Pick(hit[0], "stone", hit[1], hit[2], "party")

    from pokeagent.explorer.training import under_level
    gap = under_level(goals, combatants, ctx.opts.train_level)
    if (hit := rare_candy.should_use(candies=bag.get(ids.RARE_CANDY, 0), party=party, gap=gap, boss_next=boss_is_next(goals),
                                     grind_minutes=_grind_minutes(ctx, goals, combatants) if bag.get(ids.RARE_CANDY) else None)):
        return Pick(hit[0], "rare_candy", hit[1], hit[2], "party")

    trip = trip_kind(ctx)
    from pokeagent.explorer.par_follow import training
    from pokeagent.magikarp import trainee_slot
    if (hit := repel.should_use(bag=bag, trip=trip, ready=gap is None, training=training(ctx), active_steps=emu.read(repel.REPEL_ACTIVE),
                                has_trainee=trainee_slot(emu) is not None, battle=ctx.view.battling)):
        return Pick(hit[0], "repel", None, hit[2], "self")
    if trip == "goal" and (hit := key_items.bicycle_decision(
            owned=bag.get(ids.BICYCLE, 0) > 0, state=emu.read(key_items.WALK_BIKE_SURF_STATE),
            outdoor=emu.read(key_items.CUR_TILESET) == key_items.TILESET_OVERWORLD, battle=ctx.view.battling, leg_tiles=None)):
        return Pick(hit[0], "key_item", None, hit[2], "self")
    return None
