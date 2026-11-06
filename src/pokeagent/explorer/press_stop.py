"""Segment-run endings: the end-of-segment save state and the sub-segment stop (first entry into a map id)."""
from __future__ import annotations

import json
import os

from pokeagent.checkpoint_goals import completed_goals, write_completed
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.demos import shutdown
from pokeagent.goals import GOALS, check_goals

CUR_MAP = 0xD35E  # wCurMap


def save_end_state(ctx: ExplorerContext) -> None:
    """Write <run dir>/end.state: the curriculum copies it to <goal>.best.state when the solve is confirmed."""
    try:
        tmp = ctx.run_dir / f"end.{os.getpid()}.tmp"
        ctx.emu.save_state(tmp); os.replace(tmp, ctx.run_dir / "end.state")
        write_completed(ctx.run_dir / "end.state", completed_goals(check_goals(ctx.emu, ctx), ctx.initial_goals, GOALS))
    except Exception as e:
        ctx.log(f"[end state save failed: {e!r}]", "res")


def stop_at_map_reached(ctx: ExplorerContext) -> bool:
    """True once the run has entered ``opts.stop_at_map`` (a map it did not start in); records it like a goal."""
    want = ctx.opts.stop_at_map
    if want is None:
        return False
    here = ctx.emu.read(CUR_MAP)
    if getattr(ctx, "start_map", None) is None:
        ctx.start_map = here  # first look: the map the segment began in (an arrival there does not count)
    if here != want or ctx.start_map == want:
        return False
    with (ctx.run_dir / "goal_frames.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"goal": f"map:{want:#04x}", "step": ctx.step, "frame": ctx.frame}) + chr(10))
    save_end_state(ctx)
    ctx.done = True; shutdown(ctx); ctx.log(f"segment done: map {want:#04x} at step {ctx.step}", "hdr")
    return True
