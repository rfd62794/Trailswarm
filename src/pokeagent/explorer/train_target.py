"""One place to train: keeps grind episodes and the team_ready / gym-hold train_route on the same map.

Slice 5 (real-ROM seed 12, Cerulean ping-pong): team_ready walked train_route to Route 24 while a grind episode
on Viridian Forest pinned frontier to the episode's maps, so frontier refused the Cerulean (20,0) UP crossing
and plan_goal walked back, 7.2% of all steps. The rule, both directions:

* a grind episode may START only on the map train_route trains at while team_ready is training (Route 24);
  no point there -> no episode. The gym hold alone does not narrow episodes;
* an episode already live (begun before the stage) wins: the retarget now lives with the episode
  (GrindDrill walks it).
"""
from __future__ import annotations

from pokeagent.explorer.planner_east import ROUTE24
from pokeagent.grind import stage_maps
from pokeagent.knowledge.encounters import TRAIN_MAP


def stage_target(ctx) -> int:
    """The map train_route walks to for the current stage: the pre-Brock stage map, else Route 24."""
    stage = getattr(ctx, "stage_goal", None)
    return TRAIN_MAP[stage] if stage_maps.allowed(stage) and stage in TRAIN_MAP else ROUTE24


def stage_training(ctx) -> bool:
    """True while team_ready trains (plan_goal's train_route_live). The gym hold alone does NOT narrow episodes:
    pre-Brock the Pewter hold must keep the full PRE_BROCK set (Viridian Forest), and later gyms must not be
    pinned to Route 24 (review of 376f738)."""
    return bool(getattr(ctx, "train_route_live", False))


def only_maps(ctx) -> frozenset | None:
    """``grind.points.choose``'s ``only_maps`` for a new episode: the stage list, narrowed to the train
    target while the stage is training (None = unrestricted)."""
    allowed = stage_maps.allowed(getattr(ctx, "stage_goal", None))
    if not stage_training(ctx):
        return allowed
    tgt = stage_target(ctx)
    return frozenset({tgt}) if allowed is None else frozenset(allowed & {tgt}) or frozenset({tgt})
