"""Goal milestones: first-reached steps, checkpoints and runs/milestones.json (moved from the demo's do_press)."""
from __future__ import annotations
from pokeagent.fsutil import atomic_write_text, replace_retry

import json
import os
import time
from pathlib import Path

from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.demos import shutdown
from pokeagent.explorer.press_frame import PressFrame
from pokeagent.explorer.press_stop import save_end_state, stop_at_map_reached
from pokeagent.checkpoint_goals import completed_goals, read_completed, stamp_fingerprint, write_completed
from pokeagent.goals import GOALS, check_goals, is_unverified, store_path
from pokeagent.segment_names import state_goal


def seed_initial_goals(ctx: ExplorerContext) -> None:
    """Goals already true when the run began (segment runs start from a checkpoint). Called before the FIRST decision as well as by
    record_goals: seeding only after the first press let step 1 plan against 'potion' and walk a 6/79 lead from Vermilion into Route 6."""
    if ctx.initial_goals_ready:
        return
    goals = check_goals(ctx.emu, ctx)
    ctx.initial_goals_ready = True
    ctx.initial_goals = {g for g in GOALS if goals[g]}
    # The start state's goals sidecar is the source of truth (it lists exactly what was complete when the state was written).
    # Only a state with no sidecar falls back to its NAME: a checkpoint named after a goal implies every earlier goal too (a used
    # potion must not send a run that starts in Viridian City all the way home to the PC - seen 2026-11-03 06:00).
    stem = ctx.opts.state_stem
    side = read_completed(Path(ctx.opts.state_path)) if getattr(ctx.opts, "state_path", "") else None
    if side is not None:
        ctx.initial_goals |= {g for g in side if g in GOALS}
    else:
        stem = state_goal(stem)  # 'x.best' -> 'x', 'g@63' -> the goal before g (also for callers that pass a raw stem)
        if stem in GOALS:
            ctx.initial_goals |= set(GOALS[:GOALS.index(stem) + 1])
        elif stem == "team_best":
            ctx.initial_goals |= set(GOALS[:GOALS.index("to_route1") + 1])
    if ctx.initial_goals:
        ctx.log(f"[starting from {stem or 'the baseline'}: goals assumed done: {sorted(ctx.initial_goals)}]", "res")
    try:  # the swarm orchestrator scores 'attempts' from this: a run cannot attempt a goal it already started past
        mp = ctx.run_dir / "meta.json"; meta = json.loads(mp.read_text()); meta["initial_goals"] = sorted(ctx.initial_goals)
        mp.write_text(json.dumps(meta))
    except Exception:
        pass


def record_goals(ctx: ExplorerContext, fr: PressFrame) -> bool:
    """Detect goals first reached in this run, checkpoint and persist them. True = the run ended headless (stop here)."""
    goals = check_goals(ctx.emu, ctx)
    if goals["left_house"]:
        ctx.goal_left_house = True
    seed_initial_goals(ctx)
    for g in GOALS:  # first time each goal is reached IN THIS RUN: remember the step and persist it
        if is_unverified(g):
            continue  # inferred from later goals (no detector of its own): never a goal_frames line, checkpoint or milestone
        if goals[g] and g not in ctx.goal_steps and g not in ctx.initial_goals:
            ctx.goal_steps[g] = ctx.step; ctx.log(f"*** GOAL REACHED: {g} at step {ctx.step} frame {ctx.frame} ***", "res")
            with (ctx.run_dir / "goal_frames.jsonl").open("a", encoding="utf-8") as fh:  # frames are what pacing changes
                fh.write(json.dumps({"goal": g, "step": ctx.step, "frame": ctx.frame}) + chr(10))
            try:  # checkpoint: the swarm re-runs the NEXT segment from here (tools/swarm.py --segment)
                cp = store_path("runs/checkpoints", scope="game"); cp.mkdir(parents=True, exist_ok=True)
                tmp = cp / f"{g}.{os.getpid()}.tmp"; ctx.emu.save_state(tmp); replace_retry(tmp, cp / f"{g}.state")
                write_completed(cp / f"{g}.state", completed_goals(goals, ctx.initial_goals, GOALS), ctx.emu.read(0xD719))  # curriculum order check + respawn point
                try:
                    stamp_fingerprint(ctx.emu, cp / f"{g}.state", ctx.run_dir.name,
                                      inherit=getattr(ctx.opts, "state_path", "") or None)  # a synthetic/promoted start's lineage carries into the checkpoint
                except Exception:  # noqa: BLE001  (a stamp failure must never lose the checkpoint)
                    pass
            except Exception as e:
                ctx.log(f"[checkpoint save failed: {e!r}]", "res")
            gp = Path("runs/milestones.json")
            try:
                hist = json.loads(gp.read_text()) if gp.exists() else {}
            except json.JSONDecodeError:
                hist = {}
            rec = {"run": ctx.run_dir.name, "step": ctx.step}
            if g == "first_pokemon":
                rec["species_byte"] = ctx.emu.read(0xD164)  # wPartySpecies[0] (unverified): 0xB0 Charmander? we learn it
                rec["wanted"] = ctx.opts.starter
            hist.setdefault(g, []).append(rec)
            try:  # Windows: another agent or the viewer may hold the file for a moment
                atomic_write_text(gp, json.dumps(hist, indent=1))
            except OSError as e:
                ctx.log(f"[milestones save failed: {e!r}]", "res")
            if ctx.opts.stop_at_goal == g:  # AFTER the milestone is persisted (it used to return before recording it)
                save_end_state(ctx)
                ctx.done = True; shutdown(ctx); ctx.log(f"segment done: {g} at step {ctx.step}", "hdr")
                if ctx.opts.headless:
                    fr.goals = goals
                    return True
    fr.goals = goals
    if stop_at_map_reached(ctx):
        return bool(ctx.opts.headless)
    return False
