"""Goal milestones: first-reached steps, checkpoints and runs/milestones.json (moved from the demo's do_press)."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.demos import shutdown
from pokeagent.explorer.press_frame import PressFrame
from pokeagent.explorer.press_stop import save_end_state, stop_at_map_reached
from pokeagent.checkpoint_goals import completed_goals, write_completed
from pokeagent.goals import GOALS, check_goals


def record_goals(ctx: ExplorerContext, fr: PressFrame) -> bool:
    """Detect goals first reached in this run, checkpoint and persist them. True = the run ended headless (stop here)."""
    goals = check_goals(ctx.emu, ctx)
    if goals["left_house"]:
        ctx.goal_left_house = True
    if not ctx.initial_goals_ready:
        ctx.initial_goals_ready = True  # goals already true when the run began (segment runs start from a checkpoint)
        ctx.initial_goals = {g for g in GOALS if goals[g]}
        # A checkpoint named after a goal implies every earlier goal too (a used potion must not send a run that
        # starts in Viridian City all the way home to the PC - seen 2026-11-03 06:00).
        stem = ctx.opts.state_stem
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
    for g in GOALS:  # first time each goal is reached IN THIS RUN: remember the step and persist it
        if goals[g] and g not in ctx.goal_steps and g not in ctx.initial_goals:
            ctx.goal_steps[g] = ctx.step; ctx.log(f"*** GOAL REACHED: {g} at step {ctx.step} frame {ctx.frame} ***", "res")
            with (ctx.run_dir / "goal_frames.jsonl").open("a", encoding="utf-8") as fh:  # frames are what pacing changes
                fh.write(json.dumps({"goal": g, "step": ctx.step, "frame": ctx.frame}) + chr(10))
            try:  # checkpoint: the swarm re-runs the NEXT segment from here (tools/swarm.py --segment)
                cp = Path("runs/checkpoints"); cp.mkdir(parents=True, exist_ok=True)
                tmp = cp / f"{g}.{os.getpid()}.tmp"; ctx.emu.save_state(tmp); os.replace(tmp, cp / f"{g}.state")
                write_completed(cp / f"{g}.state", completed_goals(goals, ctx.initial_goals, GOALS))  # curriculum order check
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
            tmp = gp.with_suffix(f".{os.getpid()}.tmp"); tmp.write_text(json.dumps(hist, indent=1))
            for _try in range(5):  # Windows: another agent may hold the file for a moment
                try:
                    os.replace(tmp, gp); break
                except PermissionError:
                    time.sleep(0.2)
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
