"""Headless explorer run with text-pace metrics (no window, no Tk, no HTTP): the ROM check for defined interactions.

    uv run python tools/explore_headless.py --steps 3000 [--adaptive] [--fast-text] [--state baselines/bedroom.state]

Runs the explorer engine for N steps against a fresh maps file and prints one JSON object: emulator frames, presses made
with a text box open, text pages (a page = a press with the prompt up, or the press that closes the box), early presses
(box open, text still printing), frames per page, interaction types, re-talks, heal visits, option byte.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pokeagent.emulator import PyBoyEmulator  # noqa: E402
from pokeagent.explorer.context import ExplorerContext, ExplorerOptions  # noqa: E402
from pokeagent.explorer.decisions import DecisionLog  # noqa: E402
from pokeagent.explorer.engine import Engine  # noqa: E402
from pokeagent.explorer.memory import MapMemory  # noqa: E402
from pokeagent.explorer.perceive import TILEMAP, TILEMAP_LEN, box_open  # noqa: E402
from pokeagent.explorer.press import Presser  # noqa: E402
from pokeagent.explorer.seeding import idle_frames  # noqa: E402
from pokeagent.explorer.text_pace import prompt_waiting  # noqa: E402
from pokeagent.goals import check_goals  # noqa: E402
from pokeagent.legs import attach as legs_attach  # noqa: E402
from pokeagent.segment_names import state_goal  # noqa: E402


FRAMES_PER_STEP, BOX_PACE = 4, 6  # explore_demo --headless: decisions every 4 frames, every 6 while a box is open


def run(args) -> dict:
    random.seed(args.seed)
    drill_plan = legs_attach.plan(args.drill_leg, args.drill_grind, args.drill_steps, args.leg_states_dir, args.rom,
                                  args.state if args.state != "baselines/bedroom.state" else None)
    if drill_plan:
        args.state, args.steps = str(drill_plan.state), drill_plan.steps + 2
    work = Path(tempfile.mkdtemp(prefix="headless-"))
    if args.maps_copy:
        import shutil
        shutil.copy(args.maps_copy, work / "maps.json")
    mem = MapMemory(work / "maps.json", record_paths=False)
    emu = PyBoyEmulator(Path(args.rom), headless=True)
    emu.tick(60); emu.load_state(Path(args.state)); emu.tick(30)
    emu.tick(idle_frames(args.seed))  # --seed shifts the game's RNG (seed 0/None: unchanged)
    if args.hurt:  # lead mon at 3 HP: the party needs healing from the first step
        emu._pyboy.memory[0xD16C], emu._pyboy.memory[0xD16D] = 0, args.hurt
    count = {"frames": 0}
    tick, press = emu.tick, emu.press
    emu.tick = lambda n: (count.__setitem__("frames", count["frames"] + n), tick(n))[1]
    emu.press = lambda b, hold=8, settle=16: (count.__setitem__("frames", count["frames"] + hold), press(b, hold, settle))[1]
    trans = (work / "transitions.jsonl").open("a", encoding="utf-8")
    ctx = ExplorerContext(emu=emu, mem=mem, log=lambda t, tag=None: print(t) if args.verbose else None, run_dir=work, trans=trans,
                          explore_run=False, opts=ExplorerOptions(starter=args.starter, steps=args.steps, headless=True, state_stem=state_goal(Path(args.state).stem), stop_at_goal=args.stop_at_goal, frames_per_step=4,
                                                                   maps_path=str(work / "maps.json"),
                                                                   adaptive_pace=args.adaptive, fast_text=args.fast_text,
                                                                   bandit=args.bandit, bandit_path=args.bandit_path, par_follow=args.par_follow,
                                                                   role=args.role, novelty=args.novelty, novelty_path=args.novelty_path))
    from pokeagent.atlas.walkgrid import rom_cave_planner
    from pokeagent.explorer.world import SHIP_MAPS
    legs_attach.attach(ctx, drill_plan, args.save_leg_states, args.leg_states_dir, args.state, drills_log=args.drills_log or work / "drills.jsonl",
                       grind_log=args.grind_drills_log or work / "grind_drills.jsonl")  # a check never writes the shared logs
    ctx.ship_plan = rom_cave_planner(args.rom, maps=SHIP_MAPS)  # ship_gate's walk-off route (the swarm's explore_demo sets it too)
    if args.bandit:
        from pokeagent.bandit.driver import attach
        attach(ctx, args.bandit_path, work / "bandit_delta.json", args.seed)
    if args.novelty:
        from pokeagent.novelty.tracker import attach as attach_novelty
        ctx.opts.novelty_delta = str(work / "novelty_delta.json")
        attach_novelty(ctx, runs_dir=work)  # discoveries and the delta stay in the temp work dir: a check never writes runs/
        ctx.log = lambda t, tag=None: print(t) if "novelty" in t or args.verbose else None
        ctx.novelty.log = ctx.log
    presser = Presser(ctx)
    engine = Engine(ctx, presser, decision_log=DecisionLog(work / "decisions.jsonl"))
    m = {"box_presses": 0, "box_frames": 0, "pages": 0, "early_presses": 0}
    inner = presser.press

    def counted(name, source, why):
        tm = emu.read_range(TILEMAP, TILEMAP_LEN)
        was_box, prompt, f0 = box_open(tm), prompt_waiting(tm), count["frames"]
        inner(name, source, why)
        if was_box and name == "A":
            still = box_open(emu.read_range(TILEMAP, TILEMAP_LEN))
            m["box_presses"] += 1
            m["box_frames"] += count["frames"] - f0
            if prompt or not still:
                m["pages"] += 1
            else:
                m["early_presses"] += 1
    presser.press = counted
    ctx.box_open_now = False
    while not ctx.done and ctx.step < args.steps:  # the demo's headless loop: 1 frame per iteration, a decision every `pace`
        emu.tick(1); ctx.frame += 1
        tm = emu.read_range(TILEMAP, TILEMAP_LEN)
        ctx.box_open_now = box_open(tm)
        h = hash(tm)  # the demo's stillness tracking (Readiness waits for the screen to stop changing)
        ctx.stable_frames = ctx.stable_frames + 1 if h == ctx.last_hash else 0
        ctx.last_hash = h
        if ctx.box_open_now:
            m["box_frames"] += 1  # idle frames between decisions while a box is up count toward the text pace
        pace = (FRAMES_PER_STEP if args.adaptive else BOX_PACE) if ctx.box_open_now else FRAMES_PER_STEP
        if ctx.slow_until > ctx.step:
            pace = max(pace, 40)
        if ctx.frame % pace == 0:
            try:
                engine.step()
            except Exception as e:  # the demo never lets one bad step stop the run: log it and keep going
                m["step_errors"] = m.get("step_errors", 0) + 1
                ctx.log(f"[agent step error: {e!r}]", "res")
    mem.save(); trans.close()
    if ctx.bandit is not None:
        ctx.bandit.save()
        m["bandit"] = {"closed_episodes": ctx.bandit.closed, "open_episodes": len(ctx.bandit.open), "delta": str(ctx.bandit.delta_path)}
    if args.adaptive:  # the fast path waits for the prompt itself, so it counts its own pages
        tp = mem.data.get("text_press_stats", {"presses": 0, "pages": 0})
        m["box_presses"], m["pages"], m["early_presses"] = tp["presses"], tp["pages"], tp["presses"] - tp["pages"]
    stats = mem.data.get("interaction_stats", {})
    types, retalk = {}, []
    for mid, mp in mem.data["maps"].items():
        for key, e in list(mp.get("interactions", {}).items()) + [(f"npc:{k}", v.get("results", {})) for k, v in mp.get("npcs", {}).items()]:
            t = e.get("type")
            if t:
                types[t] = types.get(t, 0) + 1
                if t in ("info", "sign") and e.get("count", 0) > 1:
                    retalk.append(f"{mid}:{key}")
    out = {"steps": ctx.step, "frames": count["frames"], **m,
           "presses_per_page": round(m["box_presses"] / max(1, m["pages"]), 2),
           "frames_per_page": round(m["box_frames"] / max(1, m["pages"]), 1),
           "option_byte": emu.read(0xD355), "hp_end": [emu.read(0xD16D), emu.read(0xD18E)], "map_end": emu.read(0xD35E), "text_speed": mem.data.get("text_speed"), "types": types,
           "retalked_info_or_sign": retalk, "stats": stats, "goals": [g for g, v in check_goals(emu, ctx).items() if v], "goal_steps": dict(ctx.goal_steps), "starter_species": emu.read(0xD16B),
           "pace": mem.data.get("text_pace"), "drill_result": getattr(ctx.drill, "result", None), "leg_states_saved": getattr(ctx.leg_saver, "saved", 0), "work": str(work)}
    emu.close()
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rom", default="roms/Pokemon Red.gb")
    ap.add_argument("--state", default="baselines/bedroom.state")
    ap.add_argument("--steps", type=int, default=3000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--adaptive", action="store_true", help="learned A pacing (text_press)")
    ap.add_argument("--fast-text", action="store_true", help="run the set_text_speed_fast procedure first")
    ap.add_argument("--maps-copy", default=None, help="start from a copy of this maps.json (default: fresh)")
    ap.add_argument("--hurt", type=int, default=0, help="set the lead mon's HP to this value after loading (heal check)")
    ap.add_argument("--stop-at-goal", default=None, help="end the run when this goal lands (a segment run, as the swarm launches it)")
    ap.add_argument("--starter", default="bulbasaur")
    ap.add_argument("--bandit", action="store_true", help="behaviour bandit on (reads --bandit-path, writes <work>/bandit_delta.json)")
    ap.add_argument("--bandit-path", default="runs/bandit.json", help="shared bandit table loaded at start")
    ap.add_argument("--par-follow", action="store_true", help="walk purposeful trips (goal travel, heal, mart) along the ROM par path")
    ap.add_argument("--role", default="", help="swarm role; with --novelty only explorer is steered and paid by novelty")
    ap.add_argument("--novelty", action="store_true", help="novelty tracking on (reads --novelty-path; delta and discoveries stay in the work dir)")
    ap.add_argument("--novelty-path", default="runs/novelty.json", help="shared novelty table loaded at start (read-only here)")
    ap.add_argument("--verbose", action="store_true")
    legs_attach.add_args(ap)
    print(json.dumps(run(ap.parse_args(argv)), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
