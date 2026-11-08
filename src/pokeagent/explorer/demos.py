"""Demonstrations: human/Claude presses recorded as episodes, replayed later and graded (moved from the demo)."""
from __future__ import annotations

import json
from pathlib import Path

from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.perceive import TILEMAP, TILEMAP_LEN, box_open, frame_lines
from pokeagent.goals import GOALS, check_goals


def record_intervention(ctx: ExplorerContext, name: str, source: str, before, tm, goals_before):
    """Human/Claude presses become demonstrations: a sequence from a situation, with what it achieved."""
    ep = ctx.episode
    if ep is None:
        ep = ctx.episode = {"source": source, "start": list(before), "facing": ctx.facing,
                              "screen": frame_lines(tm)[:3] if box_open(tm) else [], "buttons": [],
                              "goals_before": goals_before, "step": ctx.step}
    ep["buttons"].append(name)


def close_episode(ctx: ExplorerContext, after, goals_after):
    ep = ctx.pop("episode")
    if not ep or not ep["buttons"]:
        return
    ep["end"] = list(after); ep["goals_after"] = goals_after
    ep["achieved"] = [g for g in GOALS if goals_after.get(g) and not ep["goals_before"].get(g)]
    with Path("runs/interventions.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(ep) + "\n")
    demos = ctx.mem.m(ep["start"][0]).setdefault("demos", [])
    demos.append({"at": ep["start"][1:], "facing": ep["facing"], "screen": ep["screen"], "buttons": ep["buttons"],
                  "achieved": ep["achieved"], "source": ep["source"], "end": ep["end"], "grade": 0, "replays": 0})
    del demos[:-20]
    ctx.log(f"[learned a {ep['source']} demonstration: {len(ep['buttons'])} presses from {tuple(ep['start'])}"
        f"{' -> ' + ', '.join(ep['achieved']) if ep['achieved'] else ''}]", "res")


def matching_demo(ctx: ExplorerContext, m, x, y, tm):
    """A demonstration is a hypothesis, not an order: it is replayed only while its grade is >= 0, and only
    if it achieved a goal when recorded. Every replay is graded afterwards (see grade_replay)."""
    screen = frame_lines(tm)[:3] if box_open(tm) else []
    cands = [d for d in ctx.mem.m(m).get("demos", []) if d["at"] == [x, y] and d["screen"] == screen
             and d.get("achieved") and d.get("buttons") and d.get("grade", 0) >= 0]
    return max(cands, key=lambda d: (d.get("grade", 0), len(d["achieved"]))) if cands else None


def grade_replay(ctx: ExplorerContext):
    """Called when a replay finishes: did it make progress (a goal, a new map, a new tile)? Grade it."""
    rp = ctx.pop("replay_ctx")
    if not rp:
        return
    goals_now = check_goals(ctx.emu, ctx)
    progressed = any(goals_now[g] and not rp["goals"].get(g) for g in GOALS) or ctx.pos()[0] != rp["pos"][0] \
        or (ctx.pos() != rp["pos"] and not box_open(ctx.emu.read_range(TILEMAP, TILEMAP_LEN)))
    rp["demo"]["grade"] = rp["demo"].get("grade", 0) + (1 if progressed else -1)
    rp["demo"]["replays"] = rp["demo"].get("replays", 0) + 1
    ctx.log(f"[replay graded {'GOOD' if progressed else 'BAD'} -> grade {rp['demo']['grade']}"
        f"{'; this demonstration will not be used again' if rp['demo']['grade'] < 0 else ''}]", "res")


def shutdown(ctx: ExplorerContext):
    """Close any open demonstration episode and interaction, then persist the map memory."""
    if ctx.episode:
        close_episode(ctx, ctx.pos(), check_goals(ctx.emu, ctx))
    inter = ctx.inter
    if inter:  # keep what an unfinished interaction taught us
        ctx.mem.finish_interaction(inter["entry"], inter["presses"], inter["menus"], inter["choices"]); ctx.inter = None
    from pokeagent.explorer.trainee import record_trainee
    record_trainee(ctx)
    from pokeagent.explorer import trainer_ledger
    trainer_ledger.save_run(ctx)  # the run's beaten-trainer ledger goes to <run dir>/trainers.json
    ctx.mem.save()
    if ctx.ram_diff is not None:
        ctx.ram_diff.close()
