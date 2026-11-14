"""Thin ctx readers: the OLD flags as a TrainingState, and the same values re-derived through the EXISTING functions.

Neither side writes the training flags on ctx (gate_level would set ctx.gate_lvl, so trainee_band_level is used).
Not strictly read-only: ctx.goals() (check_goals) mutates sticky state (setdefault seen_maps, seen.add, had_parcel,
healed_cerulean, through_mt_moon). Those writes are idempotent within a step, so observing does not change decisions."""
from __future__ import annotations

from pokeagent.explorer import grind_episode, training
from pokeagent.explorer.perceive import lead_level, trainee_band_level
from pokeagent.explorer.training_ctl.state import TrainingState
from pokeagent.goals import GOALS
from pokeagent.knowledge import team_floor, trainers
from pokeagent.knowledge.party import our_party


def old_flags(ctx) -> TrainingState:
    """What plan_goal / grind_episode / training wrote onto ctx this step."""
    seen = getattr(ctx, "gym_hold_seen", None)
    return TrainingState(
        train_route_live=bool(getattr(ctx, "train_route_live", False)),
        episode_live=grind_episode.active(ctx) is not None,
        gym_hold=bool(seen[1]) if seen and seen[0] == ctx.step else None,
        floor_unmet=bool(ctx.__dict__.get("floor_unmet")),
        train_member=getattr(ctx, "train_member", None),
        train_need=getattr(ctx, "train_need", 0) or 0)


def derived(ctx) -> TrainingState:
    """The same six values from goals + party through the existing pure functions (stall-hold escapes aside:
    the gym hold is the BASE hold, so an escaped hold shows as a known, logged difference)."""
    goals, party = ctx.goals(), (our_party(ctx.emu) if not ctx.view.battling else [])
    team_ready = next((g for g in GOALS if not goals.get(g)), None) == "team_ready"
    need = getattr(ctx, "train_need", 0) or 0
    level = trainee_band_level(ctx.emu) if team_ready else lead_level(ctx.emu)
    nv, floor = training.boss_need_for(goals, party), training.floor_for(goals, party)
    gym = (trainers.GYM_BOSSES.get(getattr(ctx, "stage_goal", None)) or (None, None, None))[2]
    return TrainingState(
        train_route_live=team_ready and 0 < level < need,
        episode_live=grind_episode.boundary(ctx) is not None,
        gym_hold=nv is not None and gym is not None and not team_floor.ready(nv, floor),
        floor_unmet=floor is not None and not floor.met,
        train_member=training.train_member_for(nv, training.team_for(goals, party), floor),
        train_need=need)
