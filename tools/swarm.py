"""Swarm learning: run N headless explorers in parallel, each from the shared memory, then merge what they learned.

    uv run python tools/swarm.py --agents 4 --steps 400          # ~N x faster learning than one watched run
    uv run python tools/swarm.py --merge-only                     # just fold runs/swarm/agent*.json into runs/maps.json
    uv run python tools/swarm.py --continuous --agents 4 [--duration 6] [--stop-now]   # self-refilling; see swarm_continuous.py

Each agent gets its own copy of runs/maps.json, a different seed and starter, a different control port
(8800+i) and its own transitions file (runs/explore-<ts>/, as always). When all finish, merge_memory folds
every agent's memory back into runs/maps.json: visit counts add, walls/warps/interactions/tile types union,
demonstrations union (with their grades), so the next watched run starts from everything the swarm found.
"""
from __future__ import annotations

import argparse
import atexit
import contextlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORT_BASE = int(os.environ.get("POKEAGENT_SWARM_PORT_BASE", 8800))  # scratch swarms use a high base
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pokeagent import resources  # noqa: E402
from pokeagent.legs import drill_fold, schedule as legs_schedule  # noqa: E402
from pokeagent.agent_registry import list_agents  # noqa: E402
from swarm_proc import TreeProc  # noqa: E402
import swarm_handoff  # noqa: E402
from swarm_watch import ProgressWatch, record_stall  # noqa: E402
from swarm_merge import merge_memory, merge_file_into  # noqa: E402,F401


def plan_agents(root: Path, want: int, **limits) -> tuple[int, str]:
    """Clip ``want`` to what the machine can run beside the agents already live; returns (n, why)."""
    resources.measure_agent_rss(root)
    return resources.room_for(want, root, **limits)


def segment_args(goal: str | None) -> list[str]:
    """--state/--stop-at-goal for re-running one segment, or [] when its start checkpoint does not exist yet."""
    from pokeagent.goals import GOALS
    if not goal or goal not in GOALS:
        return []
    i = GOALS.index(goal)
    start = ROOT / "runs" / "checkpoints" / f"{GOALS[i - 1]}.state" if i > 0 else ROOT / "baselines" / "bedroom.state"
    return ["--state", str(start), "--stop-at-goal", goal] if start.exists() else []


def job_args(job: dict) -> list[str]:
    """A curriculum job: start checkpoint, stop condition and the tag that links the run back to its job."""
    return ["--state", job["start"], *job["stop"], "--tag", job["tag"]]


def clamp_drills(f: float) -> float:
    """--drills is a share of refills: [0, 0.5], so segment runs always keep at least half."""
    return min(0.5, max(0.0, float(f)))


def drill_args(drill: dict) -> list[str]:
    """A leg drill (legs.schedule.pick): re-run one leg from its saved entry state."""
    return ["--drill-leg", drill["leg"], "--state", drill["state"]]


def weakest_segment(n: int) -> str | None:
    """The n-th refill takes the next-weakest goal (consistency < 70%); None when everything is consistent."""
    try:
        import overnight
        from pokeagent.campaign import selectable
        cons = {g: c for g, c in overnight.consistency().items() if c is not None and c < 0.7 and selectable(g)}  # no Surf goals for agents without Surf
    except Exception:
        return None
    weak = sorted(cons, key=cons.get)[:3]
    return weak[n % len(weak)] if weak else None


class Launcher:
    """Starts one headless explore_demo per config; picks a control port nobody (registry or this swarm) uses."""

    def __init__(self, share_frames: bool, roles_mode: bool = False, ram_diff_slots: int = 0, port_base: int | None = None,
                 bandit_slots: int = 0, par_from: int | None = None, novelty: bool = False, save_leg_states: bool = False):
        self.save_leg_states = save_leg_states  # --save-leg-states: every agent saves a state on each calm map entry (runs/legs/states)
        self.share_frames, self.roles_mode, self.handles = share_frames, roles_mode, []
        self.novelty = novelty  # --novelty: every slot counts global novelty and logs discoveries; only explorer-role slots are paid
        self.par_from = par_from  # slots >= par_from run --par-follow (the top slots, so a bandit A/B on the bottom slots stays separate)
        self.bandit_slots = bandit_slots  # slots 0..N-1 run the behaviour bandit; the rest are the control group
        self.ram_diff_slots = ram_diff_slots  # slots 0..N-1 record event RAM diffs (tools/ram_discover.py); default none
        self.port_base = PORT_BASE if port_base is None else port_base

    def _bandit_args(self, cfg: dict) -> list[str]:
        if cfg["slot"] >= self.bandit_slots:
            return []
        from pokeagent.bandit.store import delta_path_for
        return ["--bandit", "--bandit-delta", str(delta_path_for(cfg["own"]))]

    def _novelty_args(self, cfg: dict) -> list[str]:
        if not self.novelty:
            return []
        from pokeagent.novelty.store import delta_path_for
        return ["--novelty", "--role", cfg["role"], "--novelty-delta", str(delta_path_for(cfg["own"]))]

    def _par_args(self, cfg: dict) -> list[str]:
        return ["--par-follow"] if self.par_from is not None and cfg["slot"] >= self.par_from else []

    def _port(self) -> int:
        used = {e.get("port") for e in list_agents(ROOT)} | {h.port for h in self.handles if h.poll() is None}
        return next(p for p in range(self.port_base, self.port_base + 100) if p not in used)

    def __call__(self, cfg: dict):
        role_args = ["--explore-rate", str(cfg["explore_rate"]) if "explore_rate" in cfg
                     else "0.5" if cfg["role"] == "explorer" else "0.0"]
        job, drill = cfg.get("job"), cfg.get("drill")
        if cfg["role"] in ("trainer", "explorer") and self.roles_mode and not job and not drill:
            ck = ROOT / "runs" / "checkpoints"
            start = next((p for p in (ck / "team_best.state", ck / "to_route1.state") if p.exists()), None)
            if start:
                role_args = ["--state", str(start), "--explore-rate", "0.0" if cfg["role"] == "trainer" else "0.3"]
        port = self._port()
        cmd = [sys.executable, str(ROOT / "tools" / "explore_demo.py"), "--headless", "--steps", str(cfg["steps"]),
               "--maps", str(cfg["own"]), "--seed", str(cfg["seed"]), "--starter", cfg["starter"], "--control-port", str(port),
               "--box-pace", str(cfg["box_pace"])] + (["--frame-share"] if self.share_frames else [])               + (["--ram-diff"] if cfg["slot"] < self.ram_diff_slots else []) + self._bandit_args(cfg) + self._par_args(cfg) + self._novelty_args(cfg) + role_args + (drill_args(drill) if drill else job_args(job) if job else segment_args(cfg["segment"])) + (["--save-leg-states"] if self.save_leg_states else [])
        log = (ROOT / "runs" / "swarm" / f"agent{cfg['slot']}.log").open("a")
        h = TreeProc(cmd, port, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        self.handles = [x for x in self.handles if x.poll() is None] + [h]
        return h


def make_watch(cfg: dict):
    return ProgressWatch(ROOT, cfg["seed"], trainer=cfg["role"] == "trainer", since_wall=cfg.get("started_wall"))


def touch_lock() -> None:
    with contextlib.suppress(OSError):
        os.utime(ROOT / "runs" / "spawn.lock")


def par_from(a, n: int) -> int | None:
    """First slot index that runs --par-follow (--continuous only): the top --par-share of the n slots, the rest are controls."""
    return n - round(n * a.par_share) if a.par_follow else None


def bandit_slots(a, n: int) -> int:
    """How many of the n slots run the behaviour bandit (--continuous only): --bandit-share of them, the rest are controls."""
    return round(n * a.bandit_share) if a.bandit else 0


def run_continuous(a) -> int:
    import swarm_continuous as sc
    stack = contextlib.ExitStack(); atexit.register(stack.close)
    adopted = None
    if resources.lock_held(ROOT):  # a live supervisor: ask it to hand its agents over (rolling upgrade, no drain)
        print("a supervisor holds runs/spawn.lock: asking it to hand over its agents (30 s)...")
        adopted = swarm_handoff.request_handoff(ROOT)
        if adopted is None:
            print("not starting: no handoff (no answer in 30 s, or another upgrade is in flight); no double supervision")
            return 1
    try:
        if adopted is not None:  # the old supervisor already pointed the lock at us; we supervise its agents regardless
            swarm_handoff.acquire_after_handoff(stack, ROOT, [x["pid"] for x in adopted.get("agents", [])], print)
        else:
            stack.enter_context(resources.spawn_lock(ROOT, wait_s=30))
    except resources.LockBusy as e:
        print(f"not starting: {e}"); return 1
    if adopted is not None:
        n = a.agents or len(adopted.get("agents", [])) or 4  # requested count; else keep what was running
    else:
        n, why = plan_agents(ROOT, max(1, a.agents or 4))
        print(why)
        if n == 0:
            print("no room for more agents; not starting a swarm"); return 0
    shared = ROOT / a.maps
    roles = ["trainer", "explorer"] if a.roles else None
    segment = weakest_segment if a.segment == "auto" else (lambda _n: a.segment) if a.segment else None
    sup: list = []
    plan = None
    if a.plan == "curriculum":
        from seg_sched import Curriculum
        try:
            plan = Curriculum(ROOT, suite=a.suite)
        except ValueError as e:
            print(f"not starting: {e}")
            return 2

    def limit() -> int:  # machine cap minus agents we did not start (a viewer-spawned one counts against us)
        live = resources.live_agent_count(ROOT)
        pending = max(0, sup[0].running() - live)  # started but not registered yet: still count against the cap
        room, _mx, _live = resources.headroom(ROOT, extra_live=pending)
        return sup[0].running() + room

    sup.append(sc.Supervisor(ROOT, shared, n, Launcher(a.share_frames, a.roles, a.ram_diff_slots, a.port_base, bandit_slots(a, n), par_from(a, n), a.novelty, a.save_leg_states), merge_file_into, limit, steps=a.steps,
                             starter=a.starter, roles=roles, segment=segment, stop_now=a.stop_now,
                             deadline=time.monotonic() + a.duration * 3600 if a.duration else None,
                             firsts=lambda: sc.goal_firsts(ROOT), heartbeat=touch_lock, watch=make_watch, on_stall=record_stall,
                             segment_ok=lambda g: bool(segment_args(g)), plan=plan,
                             drills=clamp_drills(a.drills), drill_pick=lambda k: legs_schedule.pick(ROOT, k), on_drill=lambda _d: drill_fold.fold_file(ROOT / "runs" / "legs.json", ROOT / "runs" / "legs" / "drills.jsonl")))
    if adopted is not None:
        sup[0].adopt(adopted)
        swarm_handoff.adopt_path(ROOT / "runs" / "swarm", os.getpid()).unlink(missing_ok=True)
    print(f"continuous swarm: {n} slots, {a.steps} steps each; stop with Ctrl+C or create runs/swarm.stop")
    sup[0].run()
    stack.close()  # release runs/spawn.lock now (also when we handed our own agents on to a newer supervisor)
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agents", type=int, default=None, help="slot count (default 4; with --upgrade, the adopted agent count)")
    ap.add_argument("--steps", type=int, default=400)
    ap.add_argument("--merge-only", action="store_true")
    ap.add_argument("--bandit", action="store_true", help="--continuous: run the behaviour bandit in a share of the slots (the rest are controls)")
    ap.add_argument("--par-follow", action="store_true", help="--continuous: walk purposeful trips along the ROM par path in a share of the slots (the rest are controls)")
    ap.add_argument("--par-share", type=float, default=0.5, help="share of slots that run with --par-follow (default 0.5; the top slots)")
    ap.add_argument("--novelty", action="store_true", help="--continuous: count global novelty (runs/novelty.json) and log discoveries; only explorer-role slots are steered and paid")
    ap.add_argument("--bandit-share", type=float, default=0.5, help="share of slots that run with --bandit (default 0.5)")
    ap.add_argument("--maps", default="runs/maps.json")
    ap.add_argument("--port-base", type=int, default=PORT_BASE,
                    help="--continuous: first control port to try (100 ports); default POKEAGENT_SWARM_PORT_BASE or 8800")
    ap.add_argument("--plan", choices=["curriculum"], default=None,
                    help="--continuous: curriculum = pick each slot's segment by need (tools/segments.py shows the table)")
    ap.add_argument("--suite", default=None, metavar="NAME",
                    help="--plan curriculum: restrict segment jobs to this suite (runs/segment_sets.json)")
    ap.add_argument("--segment", default=None,
                    help="re-run ONE segment: agents start from runs/checkpoints/<previous goal>.state and stop at this goal")
    ap.add_argument("--drills", type=float, default=0.0, metavar="F",
                    help="--continuous: this fraction of refills drill the worst leg (runs/legs.json waste ranking, legs with a saved entry state) instead of a segment; 0 = off")
    ap.add_argument("--save-leg-states", action="store_true", help="--continuous: agents save a state on each calm map entry (runs/legs/states) for the drills")
    ap.add_argument("--roles", action="store_true",
                    help="specialised agents: half train from team_best.state (level up on Route 1), half explore from it (map expansion)")
    ap.add_argument("--starter", choices=["bulbasaur", "charmander", "squirtle"], default=None,
                    help="fix the starter for every agent (default: rotate bulbasaur/charmander/squirtle)")
    ap.add_argument("--share-frames", action="store_true", default=True, dest="share_frames",
                    help="agents publish rendered frames to shared memory for the viewer / tools/watch.py (renders every "
                         "Nth tick). ON by default; this flag is accepted for old command lines")
    ap.add_argument("--no-share-frames", action="store_false", dest="share_frames",
                    help="turn frame sharing off (the viewer Tiles then show no game picture)")
    ap.add_argument("--ram-diff-slots", type=int, default=0, metavar="N",
                    help="the first N agent slots record event RAM diffs for tools/ram_discover.py (default 0 = off)")
    ap.add_argument("--continuous", action="store_true",
                    help="keep --agents running: merge each agent's memory as it exits, then start a replacement")
    ap.add_argument("--upgrade", "--adopt", action="store_true", dest="upgrade",
                    help="--continuous: take over a running supervisor's agents (no drain); also happens automatically "
                         "when a live supervisor holds the lock. --agents changes the slot count gradually")
    ap.add_argument("--duration", type=float, default=None, help="--continuous: stop refilling after this many hours")
    ap.add_argument("--stop-now", action="store_true", help="--continuous: on stop, kill running agents instead of letting them finish")
    return ap


def main() -> int:
    a = build_parser().parse_args()
    from pokeagent.goals import GOALS
    seg_args: list[str] = []
    if a.merge_only and resources.lock_held(ROOT):
        print("a swarm is running (runs/spawn.lock); not merging its in-progress agent files"); return 1
    if a.continuous:
        return run_continuous(a)
    if a.segment:
        if a.segment not in GOALS:
            print(f"unknown segment {a.segment!r}"); return 1
        i = GOALS.index(a.segment)
        start = ROOT / "runs" / "checkpoints" / f"{GOALS[i - 1]}.state" if i > 0 else ROOT / "baselines" / "bedroom.state"
        if not start.exists():
            print(f"no checkpoint for the segment start: {start} (reach the previous goal in a run first)"); return 1
        seg_args = ["--state", str(start), "--stop-at-goal", a.segment]
        print(f"segment {a.segment}: starting every agent from {start.name}")
    shared = ROOT / a.maps
    swarm_dir = ROOT / "runs" / "swarm"; swarm_dir.mkdir(parents=True, exist_ok=True)

    if not a.merge_only:
        from pokeagent.explorer.edits import JOURNAL_NAME
        journal = ROOT / "runs" / JOURNAL_NAME
        stack = contextlib.ExitStack(); atexit.register(stack.close)
        try:  # one swarm at a time: two racing swarms would both read "room for N" and overshoot the cap
            stack.enter_context(resources.spawn_lock(ROOT, wait_s=30))
        except resources.LockBusy as e:
            print(f"not starting: {e}"); return 1
        n, why = plan_agents(ROOT, a.agents or 4)
        print(why)
        if n == 0:
            print("no room for more agents; not starting a swarm"); return 0
        used = {e.get("port") for e in list_agents(ROOT)}
        ports = [p for p in range(8800, 8900) if p not in used][:n]  # never reuse a live agent's control port
        procs = []
        for i in range(n):
            own = swarm_dir / f"agent{i}.json"
            if shared.exists():
                shutil.copy(shared, own)
            if journal.exists():  # agents fold the same surgery into their own copies on load
                shutil.copy(journal, own.parent / JOURNAL_NAME)
            starter = a.starter or ["bulbasaur", "charmander", "squirtle"][i % 3]
            role_args: list[str] = []
            role = ""
            if a.roles:
                team = ROOT / "runs" / "checkpoints" / "team_best.state"
                start = team if team.exists() else ROOT / "runs" / "checkpoints" / "to_route1.state"
                if start.exists():
                    role = "trainer" if i % 2 == 0 else "explorer"
                    role_args = ["--state", str(start), "--explore-rate", "0.0" if role == "trainer" else "0.3"]
            cmd = [sys.executable, str(ROOT / "tools" / "explore_demo.py"), "--headless", "--steps", str(a.steps),
                   "--maps", str(own), "--seed", str(1000 + i), "--starter", starter, "--control-port", str(ports[i]),
                   "--box-pace", str([8, 16, 30][i % 3])] + (["--frame-share"] if a.share_frames else []) \
                   + (["--ram-diff"] if i < a.ram_diff_slots else []) + (role_args or ["--explore-rate", "0.5" if i % 2 else "0.0"]) + seg_args
            if role:
                print(f"agent {i}: role {role}, starting from {Path(role_args[1]).name}")
            log = (swarm_dir / f"agent{i}.log").open("w")
            procs.append((i, subprocess.Popen(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)))
            print(f"agent {i}: starter {starter}, {'explorer' if i % 2 else 'exploiter'}, port {ports[i]}")
        t0 = time.time()
        deadline = t0 + max(240, a.steps * 1.2)  # ONE wall-clock budget for the whole round
        try:
            for i, p in procs:
                try:
                    rc = p.wait(timeout=max(1, deadline - time.time()))
                except subprocess.TimeoutExpired:
                    p.kill(); rc = "killed (timeout)"
                print(f"agent {i} finished rc={rc} after {time.time() - t0:.0f}s")
        finally:  # Ctrl+C or any error: never leave agents running (they hold ports 8800+i)
            for i, p in procs:
                if p.poll() is None:
                    p.kill()

    merged = 0
    dst = json.loads(shared.read_text()) if shared.exists() else {"maps": {}}
    for own in sorted([*swarm_dir.glob("agent*.json"), *(swarm_dir / "unmerged").glob("agent*.json")]):
        try:
            dst = merge_file_into(shared, own); merged += 1
            own.unlink()  # merged; a stale file must not be merged again by a later --merge-only
        except Exception as e:
            print(f"skip {own.name} (kept): {e!r}")
    print(f"merged {merged} agent memories into {shared}: maps={len(dst['maps'])}, "
          f"tiles={sum(len(m['visited']) for m in dst['maps'].values())}, "
          f"interactions={sum(len(m.get('interactions', {})) for m in dst['maps'].values())}, "
          f"demos={sum(len(m.get('demos', [])) for m in dst['maps'].values())}")
    ms = ROOT / "runs" / "milestones.json"
    if ms.exists():
        try:
            hist = json.loads(ms.read_text())
            print("goal firsts (best step so far):", {g: min(e["step"] for e in v) for g, v in hist.items()})
        except json.JSONDecodeError as e:
            print(f"milestones.json unreadable: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
