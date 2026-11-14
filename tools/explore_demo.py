"""Learning explorer demo: one window (game left, console right), a rule-based agent that LEARNS the map.

    uv run python tools/explore_demo.py                  # from the repo root; needs baselines/bedroom.state
    uv run python tools/explore_demo.py --steps 400 --maps runs/maps.json

What it learns, and where it goes so the real framework can reuse it:
  runs/maps.json                 cumulative map memory (same schema Map_Memory_Directive adopts):
                                 per map id: visited tiles with counts, blocked (x,y,DIR), warps (x,y,DIR)->[map,x,y]
  runs/explore-<ts>/transitions.jsonl   one line per press: from, button, to, moved, textbox, source
Policy: if a text box is open (border tile 0x79 in the tile map) press A; otherwise pick the direction from the
current tile that is not known-blocked and leads to the least-visited tile. Human steering: click the window and
use arrows / a (A) / s (B) / Enter (START) / Shift (SELECT); p pauses the agent. Human presses are learned too.
"""
from __future__ import annotations

import argparse
import atexit
import json
import os
import queue
import random
import sys
import time
from concurrent.futures import Future
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pokeagent.game.gate import adopt_rom_game  # noqa: E402
adopt_rom_game(sys.argv[1:])  # --rom <blue> selects pokemon-blue BEFORE any store path is read at import
from pokeagent.emulator import Button, PyBoyEmulator  # noqa: E402
from pokeagent.explorer.context import ExplorerContext, ExplorerOptions  # noqa: E402
from pokeagent.explorer.decisions import DecisionLog  # noqa: E402
from pokeagent.explorer.demos import shutdown  # noqa: E402
from pokeagent.explorer.engine import Engine  # noqa: E402
from pokeagent.explorer.headless_loop import LogRing, run as run_headless  # noqa: E402
from pokeagent.explorer.jsonl_buf import JsonlBuffer  # noqa: E402
from pokeagent.explorer.memory import MapMemory  # noqa: E402
from pokeagent.explorer.perceive import (  # noqa: E402  (re-exported: tools/probe_pc.py imports these from here)
    DIRS, TILEMAP, TILEMAP_LEN, ascii_vision, battle_view, box_open, box_text, frame_lines, is_menu, npc_positions,
    party_hp,
)
from pokeagent.explorer.seeding import idle_frames
from pokeagent.explorer.press import Presser  # noqa: E402
from pokeagent.explorer.ram_diff import add_cli_flag as add_ram_diff_flag, start_ram_diff  # noqa: E402
from pokeagent.goals import GOALS, check_goals, goals_brief  # noqa: E402
from pokeagent.legs import attach as legs_attach  # noqa: E402
from pokeagent.ram import read_state  # noqa: E402
from pokeagent.segment_names import state_goal  # noqa: E402
from pokeagent.statemeta import _git_sha  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from explore_plan import ControlServer, png_bytes  # noqa: E402

__all__ = ["DIRS", "box_open", "box_text", "frame_lines", "is_menu", "main"]  # probe_pc.py's imports


KEYS = {"Up": "UP", "Down": "DOWN", "Left": "LEFT", "Right": "RIGHT", "a": "A", "s": "B",
        "Return": "START", "Shift_L": "SELECT", "Shift_R": "SELECT"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rom", default="roms/Pokemon Red.gb")
    ap.add_argument("--state", default="baselines/bedroom.state")
    ap.add_argument("--maps", default="runs/maps.json")
    ap.add_argument("--steps", type=int, default=300)
    ap.add_argument("--frames-per-step", type=int, default=10, help="frames between agent decisions in the window (was 30: too deliberate)")
    ap.add_argument("--control-port", type=int, default=8765, help="localhost HTTP control API for Claude/MCP")
    ap.add_argument("--starter", default="any", choices=["any", "random", "bulbasaur", "charmander", "squirtle"],
                    help="which ball to take on Oak's table (random picks one per run, for the starter sweep)")
    ap.add_argument("--headless", action="store_true", help="no window: run as fast as the emulator allows (swarm learners)")
    add_ram_diff_flag(ap)
    ap.add_argument("--frame-share", action="store_true",
                    help="publish rendered frames to shared memory pokeagent_frames_<control-port>_<pid> for tools/watch.py")
    ap.add_argument("--frame-every", type=int, default=2,
                    help="render+publish every Nth tick when frame-sharing (render cost only, no extra game frames)")
    ap.add_argument("--runs-dir", default="runs",
                    help="parent dir for the run output dir (default runs; probes redirect it to scratch)")
    ap.add_argument("--stop-at-goal", default=None, choices=GOALS, help="end the run when this goal lands (segment runs)")
    ap.add_argument("--stop-at-map", type=lambda v: int(v, 0), default=None,
                    help="end the run on first entry into this map id (a split sub-segment; see tools/segments.py)")
    ap.add_argument("--tag", default=None, help="opaque label stored in meta.json (the curriculum links a run to its job)")
    ap.add_argument("--box-pace", type=int, default=6,
                    help="frames between presses while a text box is open (A skips text faster); swarm agents vary it")
    ap.add_argument("--adaptive-pace", action=argparse.BooleanOptionalAction, default=True,
                    help="A through text boxes the moment the prompt shows, at the learned minimum settle (text_press); overrides --box-pace")
    ap.add_argument("--fast-text", action=argparse.BooleanOptionalAction, default=True,
                    help="set TEXT SPEED to FAST once at the start (START > OPTION), verified on the option byte")
    ap.add_argument("--seed", type=int, default=None, help="random seed (swarm learners get different ones)")
    ap.add_argument("--train-level", type=int, default=8,
                    help="planner trains on Route 1 until the lead reaches this level (Brock sweep: 8/10/12/14)")
    ap.add_argument("--explore-rate", type=float, default=0.2,
                    help="probability that a run ignores known demonstrations and partly ignores the planner, to try to beat the record")
    ap.add_argument("--bandit", action="store_true", help="behaviour bandit: fight/flee, heal/push on, grind/skip chosen by Thompson sampling")
    ap.add_argument("--par-follow", action="store_true", help="walk purposeful trips (goal travel, heal, mart) along the ROM par path")
    ap.add_argument("--bandit-path", default="runs/bandit.json", help="shared bandit table loaded at start")
    ap.add_argument("--bandit-delta", default="", help="where this run writes its bandit delta (default <run dir>/bandit_delta.json)")
    ap.add_argument("--role", default="", help="swarm role (explorer/exploiter/...); with --novelty only explorer is steered and paid by novelty")
    ap.add_argument("--novelty", action="store_true", help="count global novelty and log discoveries (runs/novelty.json, runs/discoveries.jsonl)")
    ap.add_argument("--novelty-path", default="runs/novelty.json", help="shared novelty table loaded at start")
    ap.add_argument("--novelty-delta", default="", help="where this run writes its novelty delta (default <run dir>/novelty_delta.json)")
    legs_attach.add_args(ap)
    ap.add_argument("--cell-dump", default=None, help="harvest cells into this Go-Explore archive dir (slice 3); off = byte-identical run")
    a = ap.parse_args(argv)
    drill_plan = legs_attach.plan(a.drill_leg, a.drill_grind, a.drill_steps, a.leg_states_dir, a.rom,
                                  a.state if a.state != "baselines/bedroom.state" else None, min_hp=a.drill_min_hp)
    if drill_plan:  # a drill starts from its saved entry state and runs its own step budget
        a.state, a.steps = str(drill_plan.state), drill_plan.steps + 2
    if a.seed is not None:
        random.seed(a.seed)
    if a.headless:
        a.frames_per_step = 4  # the readiness check still paces presses; nobody is watching
    if a.starter == "random":
        a.starter = random.choice(["bulbasaur", "charmander", "squirtle"])
    explore_run = random.random() < a.explore_rate

    run_dir = Path(a.runs_dir) / f"explore-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"  # unique even for a swarm started in one second
    run_dir.mkdir(parents=True, exist_ok=True)
    buf = JsonlBuffer()  # one cadence (every 50 steps + close) for the run's per-step jsonl appends
    trans = buf.open(run_dir / "transitions.jsonl")
    (run_dir / "meta.json").write_text(json.dumps({"start": state_goal(Path(a.state).stem) if a.state else "baseline",
                                                    "stop_at_goal": a.stop_at_goal, "stop_at_map": a.stop_at_map, "tag": a.tag, "steps": a.steps, "explore_rate": a.explore_rate, "box_pace": a.box_pace, "starter": a.starter, "seed": a.seed,
                                                    "frame_share": a.frame_share, "train_level": a.train_level,
                                                    "window": not a.headless, "git_sha": _git_sha() or ""}))
    mem = MapMemory(Path(a.maps), record_paths=False)  # the demo's maps.json gains no 'paths' key
    emu = PyBoyEmulator(Path(a.rom), headless=True)
    emu.tick(60); emu.load_state(Path(a.state)); emu.tick(30)
    emu.tick(idle_frames(a.seed))  # --seed shifts the game's RNG (seed 0/None: unchanged)

    ring = None
    if a.headless:
        # no Tk root at all (a hidden mainloop still paid ~16% of the profile, and any window on
        # Robert's screen is a hard rule): the console Text becomes a tail ring + console.log file
        ring = LogRing(run_dir / "console.log")
        log = ring
        root = screen = con = vis = dlg = None
    else:
        import tkinter as tk
        from PIL import Image, ImageTk
        root = tk.Tk(); root.title("PokeAgent explorer demo - 1x  (t turbo, p pause, arrows/a/s/Enter/Shift steer)")
        root.configure(bg="#111")
        screen = tk.Label(root, bg="#111", bd=0); screen.grid(row=0, column=0, padx=8, pady=8)
        con = tk.Text(root, width=78, height=28, bg="#0b0b0b", fg="#d8d8d8", font=("Consolas", 10), bd=0, padx=10, pady=8, wrap="word")
        con.grid(row=0, column=1, padx=(0, 8), pady=8, sticky="ns")
        # third pane: what the agent SEES (tile map as text) and what it REMEMBERS (map memory around it)
        vis = tk.Label(root, bg="#0b0b0b", fg="#9fd8ff", font=("Consolas", 13), justify="left", anchor="nw",
                       padx=10, pady=8, width=22, height=27)
        vis.grid(row=0, column=2, padx=(0, 8), pady=8, sticky="ns")
        # fourth pane under the game: the current dialog / menu text, goals, and battle flag (not on the map)
        dlg = tk.Label(root, bg="#0b0b0b", fg="#ffd9a0", font=("Consolas", 11), justify="left", anchor="nw",
                       padx=10, pady=6, width=58, height=6)
        dlg.grid(row=1, column=0, padx=8, pady=(0, 8), sticky="ew")
        for tag, col in {"hdr": "#7fd1ff", "why": "#c9f29b", "btn": "#ffd166", "res": "#ff9f7f", "human": "#f78fff"}.items():
            con.tag_config(tag, foreground=col)
        def log(t, tag=None):
            con.insert("end", t + "\n", tag); con.see("end")

    decisions = DecisionLog(run_dir / "decisions.jsonl", fh=buf.open(run_dir / "decisions.jsonl"))
    ctx = ExplorerContext(
        emu=emu, mem=mem, log=log, run_dir=run_dir, trans=trans, explore_run=explore_run,
        opts=ExplorerOptions(starter=a.starter, state_stem=state_goal(Path(a.state).stem) if a.state else "", state_path=a.state or "", steps=a.steps,
                             stop_at_goal=a.stop_at_goal, stop_at_map=a.stop_at_map, headless=a.headless, box_pace=a.box_pace,
                             frames_per_step=a.frames_per_step, train_level=a.train_level, maps_path=a.maps,
                             adaptive_pace=a.adaptive_pace, fast_text=a.fast_text,
                             bandit=a.bandit, bandit_path=a.bandit_path, bandit_delta=a.bandit_delta, par_follow=a.par_follow,
                             role=a.role, novelty=a.novelty, novelty_path=a.novelty_path, novelty_delta=a.novelty_delta))
    ctx.jsonl_buf = buf  # the shared cadence: per-step jsonl appends flush every 50 steps and on exit
    legs_attach.attach(ctx, drill_plan, a.save_leg_states, a.leg_states_dir, a.state, drills_log=a.drills_log, grind_log=a.grind_drills_log, goto=a.drill_goto)
    if a.bandit:
        from pokeagent.bandit.driver import attach
        attach(ctx, a.bandit_path, a.bandit_delta or None, a.seed)
    if a.novelty:
        from pokeagent.novelty.tracker import attach as attach_novelty
        attach_novelty(ctx)
    from pokeagent.explorer.anomalies import AnomalyMonitor
    from pokeagent.atlas.rom_maps import valid_map_ids
    ctx.anomalies = AnomalyMonitor.for_ctx(ctx, valid_map_ids(a.rom))
    a.ram_diff and start_ram_diff(ctx, emu, run_dir, a.state, a.rom)  # fail-soft: runs unrecorded on any error
    from pokeagent.atlas.ladders import rom_ladders
    ctx.ladders = rom_ladders(a.rom)
    from pokeagent.atlas.walkgrid import rom_cave_planner
    ctx.cave_plan = rom_cave_planner(a.rom)
    from pokeagent.explorer.world import SHIP_MAPS
    ctx.ship_plan = rom_cave_planner(a.rom, maps=SHIP_MAPS)
    from pokeagent.atlas.collision import rom_walkable_ids
    mem.rom_walkable = rom_walkable_ids(a.rom)
    from pokeagent.atlas.collision import rom_tile_pairs
    mem.rom_pairs = rom_tile_pairs(a.rom)
    presser = Presser(ctx)
    engine = Engine(ctx, presser, decision_log=decisions)
    if a.cell_dump:
        from pokeagent.goexplore.cell_dump import attach; attach(ctx, engine, a.cell_dump)
    frame_pub = None
    if a.frame_share:
        try:
            from pokeagent.telemetry import FramePublisher
            frame_pub = FramePublisher(a.control_port, emu)
            log(f"[frame slot: {frame_pub.name}]", "res")
        except Exception as e:
            log(f"[frame share unavailable: {e}]", "res")

    agent_view = None
    try:  # viewer agent: snapshot+commands on pokeagent.control_server, frames via --frame-share/telemetry
        from pokeagent.adapters.explorer_snapshot import ExplorerAgentView
        agent_view = ExplorerAgentView(ctx, emu, mem, engine, presser, agent_id=f"explore-{os.getpid()}",
                                       frame_slot=frame_pub.name if frame_pub else "")
        agent_view.serve(port=0)
        atexit.register(agent_view.close)
        log(f"[viewer agent registered: {agent_view.agent_id}]", "res")
    except Exception as e:
        log(f"[viewer agent unavailable: {e!r}]", "res")
    atexit.register(buf.close)  # a crash or Ctrl-C still drains the run's buffered .jsonl tail (close is idempotent)
    pos = ctx.pos

    def close_logs() -> None:
        ctx.bandit is not None and ctx.bandit.save()
        buf.close()  # drains every buffered jsonl (transitions, decisions, progress, loops) before they close
        trans.close(); decisions.close()
        ring is not None and ring.close()

    def on_key(ev):
        if ev.keysym == "p":
            ctx.paused = not ctx.paused; log(f"[agent {'paused' if ctx.paused else 'resumed'}]", "res"); return
        if ev.keysym == "t":  # turbo: 1x -> 2x -> 4x -> 8x -> 1x (frameskip in the window; headless is always unthrottled)
            ctx.speed = {1: 2, 2: 4, 4: 8}.get(ctx.speed, 1)
            root.title(f"PokeAgent explorer demo - {ctx.speed}x  (t turbo, p pause, arrows/a/s/Enter/Shift steer)")
            log(f"[turbo {ctx.speed}x]", "res"); return
        name = KEYS.get(ev.keysym)
        if name:
            if agent_view is not None: agent_view.hold.touch()  # tk steering holds the agent like viewer steering
            presser.press(name, "human", f"you pressed {name}")

    # --- remote control (Claude via curl now, MCP later): handlers run on this thread between frames ---
    jobs: queue.Queue = queue.Queue()

    def call(fn):
        fut: Future = Future(); jobs.put((fn, fut)); return fut.result(timeout=30)

    ctl = ControlServer(call, port=a.control_port)

    @ctl.route("GET", "/status")
    def _status():
        m, x, y = pos()
        return {"step": ctx.step, "map": m, "x": x, "y": y, "facing": ctx.facing, "paused": ctx.paused,
                "in_battle": bool(ctx.in_battle), "goals": check_goals(emu, ctx), "goal_steps": ctx.goal_steps,
                "goto": ctx.goto, "party": emu.read(0xD163), "bag_items": emu.read(0xD31D), "hp": party_hp(emu),
                "box_open": box_open(emu.read_range(TILEMAP, TILEMAP_LEN)), "maps_known": sorted(mem.data["maps"])}

    @ctl.route("GET", "/goals")
    def _goals(): return {"goals": check_goals(emu, ctx), "first_reached_step": ctx.goal_steps}

    @ctl.route("GET", "/screen")
    def _screen(): return {"lines": frame_lines(emu.read_range(TILEMAP, TILEMAP_LEN))}

    @ctl.route("GET", "/screenshot.png")
    def _shot(): return png_bytes(emu.screenshot())

    @ctl.route("GET", "/map")
    def _map(id=None, **_):
        mid = str(id if id is not None else pos()[0]); return {"map": mid, **mem.data["maps"].get(mid, {})}

    @ctl.route("POST", "/press")
    def _press(button="A", **_):
        if button.upper() not in Button.__members__:
            raise ValueError(f"unknown button {button!r}; use {sorted(Button.__members__)}")
        presser.press(button.upper(), "claude", f"remote press {button.upper()}"); return _status()

    @ctl.route("POST", "/pause")
    def _pause(**_): ctx.paused = True; log("[agent paused by remote]", "res"); return {"paused": True}

    @ctl.route("POST", "/resume")
    def _resume(**_): ctx.paused = False; log("[agent resumed by remote]", "res"); return {"paused": False}

    @ctl.route("POST", "/goto")
    def _goto(map=None, x=None, y=None, **_):
        ctx.goto = [int(map if map is not None else pos()[0]), int(x), int(y)]
        log(f"[remote goto {ctx.goto}]", "res"); return {"goto": ctx.goto}

    @ctl.route("GET", "/vision")
    def _vision(**_):
        return {"rows": battle_view(emu, ctx.move_tag) if emu.read(0xD057) else ascii_vision(emu, mem, emu.read(0xD367))}

    @ctl.route("GET", "/peek")
    def _peek(addr="0xD35E", length="1", **_):
        a0, n = int(str(addr), 16) if str(addr).lower().startswith("0x") else int(addr), min(int(length), 512)
        data = emu.read_range(a0, n) if n > 1 else bytes([emu.read(a0)])
        return {"addr": f"0x{a0:04X}", "hex": data.hex(" "), "bytes": list(data)}

    @ctl.route("GET", "/sprites")
    def _sprites(**_):
        return {"player": [emu.read(0xD362), emu.read(0xD361)],
                "slots": [{"slot": i, "pic": emu.read(0xC100 + 16 * i), "c2x4": emu.read(0xC204 + 16 * i),
                           "c2x5": emu.read(0xC205 + 16 * i), "c1x4": emu.read(0xC104 + 16 * i), "c1x6": emu.read(0xC106 + 16 * i)}
                          for i in range(16) if emu.read(0xC100 + 16 * i)]}

    @ctl.route("POST", "/say")
    def _say(text="", **_): log(f"claude:   {text}", "human"); return {"ok": True}

    @ctl.route("POST", "/reload_edits")
    def _reload_edits(**_):
        n = mem.apply_edits()  # fold runs/memory_edits.jsonl into live memory (brain-tools surgery)
        log(f"[edit journal reloaded: {n} edit(s) applied]", "res")
        return {"edits": n}

    try:
        ctl.start()
    except OSError as e:  # port taken (another agent): run without the API rather than crash
        log(f"[control API unavailable: {e}]", "res")

    log("Explorer demo. Rule-based agent learning the map; your key presses are learned too. Click the window to steer.", "hdr")
    log(f"Remote control for Claude: http://127.0.0.1:{a.control_port}/status  (press, pause, resume, goto, say)\n", "hdr")
    log(f"map memory: {a.maps} ({len(mem.data['maps'])} maps known so far); starter: {a.starter}; "
        f"{'EXPLORATION run (trying to beat the record)' if explore_run else 'exploitation run (follows what works)'}\n", "res")

    def close_frame_shm() -> None:
        if frame_pub is not None:
            frame_pub.close()

    if a.headless:
        def _exit_headless() -> None:
            try:
                close_frame_shm(); shutdown(ctx); close_logs(); emu.close()
            except Exception:
                pass
            try:
                ctl.stop()
            except Exception:
                pass
        run_headless(ctx, engine, jobs=jobs, on_exit=_exit_headless, agent_view=agent_view,
                     frame_pub=frame_pub, frame_every=a.frame_every)
        return 0

    def frame():
        agent_view and agent_view.tick()  # viewer commands + cached snapshot, on this (emulator) thread
        while not jobs.empty():  # remote-control jobs run here, on the emulator's thread
            fn, fut = jobs.get()
            try:
                fut.set_result(fn())
            except Exception as e:
                fut.set_exception(e)
        if ctx.done:
            root.after(100, frame)  # only job draining after the run, so /status still answers; ONE reschedule
            return
        if ctx.speed > 1:
            emu.tick(ctx.speed - 1)  # turbo: frameskip - run extra frames unrendered, draw one
        img = emu.screenshot().resize((480, 432), Image.NEAREST)  # screenshot renders one frame
        ctx.photo = ImageTk.PhotoImage(img); screen.configure(image=ctx.photo)
        if frame_pub is not None:
            frame_pub.publish(advance=False)  # reuse the frame screenshot() just rendered
        ctx.frame += 1
        if ctx.frame % 15 == 0:
            try:
                m_, x_, y_ = pos(); npcs = npc_positions(emu)
                if emu.read(0xD057):
                    vis.configure(text="SEES (battle)\n" + "\n".join(battle_view(emu, ctx.move_tag)))
                else:
                    sees = ascii_vision(emu, mem, emu.read(0xD367)); rem = mem.render_memory(m_, x_, y_, npcs)
                    vis.configure(text="SEES (10x9 tiles)\n" + "\n".join(sees) + "\n" + sees.legend
                                  + f"\n\nREMEMBERS map 0x{m_:02X}\n" + "\n".join(rem) + "\n" + rem.legend)
                tm_d = emu.read_range(TILEMAP, TILEMAP_LEN)
                lines_d = frame_lines(tm_d) if box_open(tm_d) else []
                g = check_goals(emu, ctx)
                dlg.configure(text=("DIALOG: " + " | ".join(lines_d)[:150] if lines_d else "DIALOG: (none)")
                              + f"\nGOALS:  " + goals_brief(g)
                              + f"\nBATTLE: {'yes (0x%02X)' % emu.read(0xD057) if emu.read(0xD057) else 'no'}"
                              f"   party={emu.read(0xD163)} bag={emu.read(0xD31D)} money={read_state(emu).money}")
            except Exception as e:
                vis.configure(text=f"vision error: {e!r}")
        tm_f = emu.read_range(TILEMAP, TILEMAP_LEN)
        ctx.box_open_now = box_open(tm_f)
        h = hash(tm_f)  # screen tiles only; wandering NPCs must not count as a cutscene
        ctx.stable_frames = ctx.stable_frames + 1 if h == ctx.last_hash else 0
        ctx.last_hash = h
        try:
            pace = (a.frames_per_step if a.adaptive_pace else a.box_pace) if (a.box_pace and ctx.box_open_now) else a.frames_per_step
            if ctx.slow_until > ctx.step:
                pace = max(pace, 40)  # some tasks need a slower hand (Mom's heal, fades): per-task speed
            hold = agent_view.held() if agent_view is not None else False
            if not ctx.paused and not hold and ctx.frame % pace == 0:
                engine.step()  # human hold (viewer Steer) pauses agent decisions, not the game
        except Exception as e:  # never let one bad step freeze the window: log it and keep the loop alive
            log(f"[agent step error: {e!r}]", "res")
        finally:
            root.after(16, frame)

    root.bind("<Key>", on_key)
    root.after(300, frame)
    root.protocol("WM_DELETE_WINDOW", lambda: (shutdown(ctx), close_logs(), emu.close(), root.destroy()))
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
