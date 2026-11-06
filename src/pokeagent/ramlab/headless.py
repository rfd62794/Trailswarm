"""Run the explorer agent with no window and no tk (seeding RAM discovery, overhead measurement).

Mirrors the frame loop of tools/explore_demo.py (pace, box pacing, stable-screen hash) without the window,
control server or viewer registration, so it opens nothing and listens on no port.
"""
from __future__ import annotations

import random
import time
from pathlib import Path

from pokeagent.emulator import PyBoyEmulator
from pokeagent.explorer.context import ExplorerContext, ExplorerOptions
from pokeagent.explorer.decisions import DecisionLog
from pokeagent.explorer.demos import shutdown
from pokeagent.explorer.engine import Engine
from pokeagent.explorer.memory import MapMemory
from pokeagent.explorer.perceive import TILEMAP, TILEMAP_LEN, box_open
from pokeagent.explorer.press import Presser


def run_agent(rom: Path, state: Path, maps: Path, run_dir: Path, steps: int, *, ram_diff: bool, seed: int = 1,
              starter: str = "any", frames_per_step: int = 4, box_pace: int = 6, max_frames: int = 400_000) -> dict:
    """Drive one explorer from ``state`` for ``steps`` presses. Returns {steps, secs, records, frames}."""
    random.seed(seed)
    run_dir = Path(run_dir); run_dir.mkdir(parents=True, exist_ok=True)
    emu = PyBoyEmulator(Path(rom), headless=True)
    emu.tick(60); emu.load_state(Path(state)); emu.tick(30)
    trans = (run_dir / "transitions.jsonl").open("a", encoding="utf-8")
    decisions = DecisionLog(run_dir / "decisions.jsonl")
    ctx = ExplorerContext(emu=emu, mem=MapMemory(Path(maps), record_paths=False), run_dir=run_dir, trans=trans,
                          explore_run=False,
                          opts=ExplorerOptions(starter=starter, state_stem=Path(state).stem, steps=steps, headless=True,
                                               box_pace=box_pace, frames_per_step=frames_per_step, maps_path=str(maps)))
    if ram_diff:
        from pokeagent.explorer.ram_diff import start_ram_diff
        start_ram_diff(ctx, emu, run_dir, str(state), str(rom))
    engine = Engine(ctx, Presser(ctx), decision_log=decisions)
    t0, frames = time.perf_counter(), 0
    while not ctx.done and frames < max_frames:
        emu.tick(1); ctx.frame += 1; frames += 1
        tm = emu.read_range(TILEMAP, TILEMAP_LEN)
        ctx.box_open_now = box_open(tm)
        h = hash(tm)
        ctx.stable_frames = ctx.stable_frames + 1 if h == ctx.last_hash else 0
        ctx.last_hash = h
        pace = box_pace if (box_pace and ctx.box_open_now) else frames_per_step
        if ctx.slow_until > ctx.step:
            pace = max(pace, 40)
        if ctx.frame % pace == 0:
            try:
                engine.step()
            except Exception as e:  # one bad step must not end the seed run
                ctx.log(f"[agent step error: {e!r}]", "res")
    secs = time.perf_counter() - t0
    records = ctx.ram_diff.records if ctx.ram_diff is not None else 0
    try:
        shutdown(ctx)
    finally:
        trans.close(); decisions.close()
        if ctx.ram_diff is not None:
            ctx.ram_diff.close()
        emu.close()
    return {"steps": ctx.step, "secs": secs, "records": records, "frames": frames}
