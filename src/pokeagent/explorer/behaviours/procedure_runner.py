"""procedure_runner: walk a loaded, enabled goal procedure one press per call - bounded, graded, never trusted.

Registered between the planner and exploration (after PlanGoal/LearnerHunt/TeamHunt, before Frontier). It runs
while the NEXT UNMET goal (or the segment goal just entered, inside its own maps) owns a procedure file; every
step is bounded by presses and frames, a downgraded step is skipped, a failing step hands control back to
exploration, and an after_victory heal/potion decision pauses a pending step until healed (or HEAL_PAUSE_MAX).
"""
from __future__ import annotations

from pokeagent.explorer.behaviours.base import BehaviourBase, Decision, no_press
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.procedures.state import of
from pokeagent.explorer.world import DIRS, WorldGraph
from pokeagent.goals import GOALS, party_full
from pokeagent.procedures import predicates, store

RELOAD_EVERY = 200      # steps a cached procedure file is kept before re-reading (untuned first value)
PRE_LOST_STEPS = 5      # consecutive calls a step's precondition may be false before the step fails (untuned)
RUNNER_STEP_CAP = 4000  # presses spent inside procedures per run; then the runner stops for the run (untuned)
HEAL_PAUSE_MAX = 600    # steps an after_victory heal/potion decision pauses a pending step (untuned)


class ProcedureRunner(BehaviourBase):
    name = "procedure_runner"

    def __init__(self) -> None:
        self._cache: dict = {}  # goal -> (loaded_at_step, Procedure | None)

    # --- start condition ---------------------------------------------------------------------------------
    def applies(self, ctx: ExplorerContext) -> bool:
        if ctx.view.battling or ctx.in_battle or ctx.view.box or ctx.proc is not None or ctx.goto:
            return False
        if of(ctx)["steps"] >= RUNNER_STEP_CAP:
            return False
        if of(ctx)["run"] is not None:
            return not self._paused(ctx)
        return self._acquire(ctx) is not None

    def _root(self, ctx):
        return ctx.run_dir.parent / "procedures"

    def _load(self, ctx, goal):
        hit = self._cache.get(goal)
        if hit and ctx.step - hit[0] < RELOAD_EVERY:
            return hit[1]
        proc = store.load(goal, self._root(ctx))
        self._cache[goal] = (ctx.step, proc)
        return proc

    def _acquire(self, ctx):
        st = predicates.read_state(ctx)
        goals = ctx.goals()
        i = next((i for i, g in enumerate(GOALS) if not goals.get(g)), len(GOALS))
        cands = ([GOALS[i]] if i < len(GOALS) else []) + ([GOALS[i - 1]] if i > 0 else [])
        for j, goal in enumerate(cands):  # the next unmet goal first, then the segment just entered
            proc = self._load(ctx, goal)
            if proc is None or proc.disabled:
                continue
            step = store.next_step(proc, st)
            if step is None or not predicates.check(step.pre, st):
                continue
            if j == 1 and st["map"] not in predicates.proc_maps(proc):
                continue  # the just-met goal's procedure resumes only inside its own maps
            of(ctx)["run"] = {"proc": proc, "goal": goal, "i": proc.steps.index(step),
                                 "presses": 0, "frames": 0, "pre_lost": 0, "wins0": ctx.battles_won,
                                 "p0": of(ctx)["steps"], "f0": ctx.frame, "pause_at": None, "queue": None}
            ctx.log(f"[procedure {goal}: start ({len(proc.steps)} steps, {proc.source})]", "res")
            return proc
        return None

    def _paused(self, ctx) -> bool:
        """An after_victory heal/potion pauses the pending step until the party is healed or HEAL_PAUSE_MAX
        passes; a push resumes; continue does nothing special."""
        run = of(ctx)["run"]
        av = of(ctx)["victory"]
        action = getattr(av, "action", None)
        if action in ("heal", "potion") and run.get("av_done") is not av:
            if run["pause_at"] is None:
                run["pause_at"] = ctx.step
            if party_full(ctx.emu) or ctx.step - run["pause_at"] >= HEAL_PAUSE_MAX:
                run["pause_at"] = None
                run["av_done"] = av  # this decision is spent: a new one pauses again
                return False
            return True
        run["pause_at"] = None
        return False

    # --- one press per call ------------------------------------------------------------------------------
    def step(self, ctx: ExplorerContext) -> Decision | None:
        run = of(ctx)["run"]
        if run is None or self._paused(ctx):
            return None
        proc, st = run["proc"], predicates.read_state(ctx)
        while run["i"] < len(proc.steps):  # advance past done / downgraded steps
            s = proc.steps[run["i"]]
            if self._done(s, run, ctx, st):
                if store.downgraded(s):
                    store.grade(proc, s.id, True)  # achieved outside the runner: resets the downgrade
                run["i"] += 1
                run.update(presses=0, frames=0, pre_lost=0, queue=None, wins0=ctx.battles_won)
                continue
            if store.downgraded(s):
                ctx.log(f"[procedure {run['goal']}: step {s.id} downgraded - exploring]", "res")
                run["i"] += 1
                continue
            break
        if run["i"] >= len(proc.steps):
            presses, frames = of(ctx)["steps"] - run["p0"], ctx.frame - run["f0"]
            store.grade(proc, None, True, presses, frames)
            store.save(proc, self._root(ctx))
            ctx.log(f"[procedure {run['goal']}: done in {presses} presses / {frames} frames]", "res")
            of(ctx)["run"] = None
            return no_press("procedure_done")
        step = proc.steps[run["i"]]
        run["frames"] += ctx.opts.frames_per_step
        if st["map"] not in predicates.proc_maps(proc):
            return self._fail(ctx, run, step, "left the procedure's maps")
        if not predicates.check(step.pre, st, ctx.log):
            run["pre_lost"] += 1
            if run["pre_lost"] >= PRE_LOST_STEPS:
                return self._fail(ctx, run, step, "precondition lost")
            return None  # a step whose precondition is false is not failed: other behaviours run
        run["pre_lost"] = 0
        if run["presses"] >= step.max_presses or run["frames"] >= step.max_frames:
            return self._fail(ctx, run, step, f"over budget ({run['presses']} presses / {run['frames']} frames)")
        dec = self._act(ctx, run, step, st)
        if dec is not None and dec.button:
            run["presses"] += 1
            of(ctx)["steps"] += 1
        return dec

    @staticmethod
    def _done(step, run, ctx, st) -> bool:
        if predicates.check(step.effect, st):
            return True
        a = step.action or {}  # a fight_trainer step also finishes when a trainer win is recorded under it
        return a.get("name") == "fight_trainer" and ctx.battles_won > run["wins0"]

    def _fail(self, ctx, run, step, why):
        proc = run["proc"]
        store.grade(proc, step.id, False)
        store.grade(proc, None, False)
        store.save(proc, self._root(ctx))
        ctx.log(f"[procedure {run['goal']}: step {step.id} failed ({why}) - exploring]", "res")
        of(ctx)["run"] = None
        return None

    def _act(self, ctx, run, step, st) -> Decision | None:
        a = step.action or {}
        kind = a.get("kind")
        if kind == "buttons":
            if run["queue"] is None:
                run["queue"] = list(a.get("buttons") or [])
            if not run["queue"]:
                return self._fail(ctx, run, step, "script spent")
            return Decision(run["queue"].pop(0), "proc_buttons", f"procedure {run['goal']} {step.id}: scripted press")
        if kind == "goto":
            return self._goto(ctx, run, step, a.get("map"), a.get("x"), a.get("y"), st)
        if kind == "interact":
            pos = (st["map"], st["x"], st["y"])
            if pos != (a.get("map"), a.get("x"), a.get("y")):
                return self._goto(ctx, run, step, a.get("map"), a.get("x"), a.get("y"), st)
            if a.get("face") and ctx.facing != a["face"]:
                return Decision(a["face"], "proc_face", f"procedure {run['goal']} {step.id}: facing {a['face']}")
            return Decision("A", "proc_interact", f"procedure {run['goal']} {step.id}: press A")
        if kind == "behaviour":
            if a.get("name") not in ("fight_trainer", "talk", "heal_here"):
                return self._fail(ctx, run, step, f"unknown behaviour {a.get('name')}")
            return self._npc(ctx, run, step, a.get("at"), st)
        return self._fail(ctx, run, step, f"unknown action kind {kind}")

    def _goto(self, ctx, run, step, m, ax, ay, st) -> Decision | None:
        pos = (st["map"], st["x"], st["y"])
        goal = (lambda n: n[0] == m) if ax is None or ay is None else (lambda n: n == (m, ax, ay))
        if goal(pos):
            return None  # arrived (a null tile is satisfied by the map): the effect completes the step
        g = WorldGraph(ctx.mem.data["maps"])
        g.blocked_now = frozenset(ctx.mem.temp_blocked)
        p = g.path(pos, goal)
        if p:
            return Decision(p[0], "proc_goto", f"procedure {run['goal']} {step.id}: goto ({m},{ax},{ay})")
        return None  # no learned route: other behaviours run; the frame budget still bounds the step

    def _npc(self, ctx, run, step, at, st) -> Decision | None:
        if not isinstance(at, (list, tuple)) or len(at) < 3:
            return None  # no target tile (a fight may still finish the step via wins0)
        m, ax, ay = int(at[0]), int(at[1]), int(at[2])
        pos = (st["map"], st["x"], st["y"])
        if pos[0] == m:
            dx, dy = ax - pos[1], ay - pos[2]
            if abs(dx) + abs(dy) == 1:
                face = next(b for b, (ddx, ddy) in DIRS.items() if (ddx, ddy) == (dx, dy))
                if ctx.facing != face:
                    return Decision(face, "proc_face", f"procedure {run['goal']} {step.id}: facing {face}")
                return Decision("A", "proc_talk", f"procedure {run['goal']} {step.id}: talking to the trainer")
            goal = lambda n: n[0] == m and abs(n[1] - ax) + abs(n[2] - ay) == 1
        else:
            goal = lambda n: n[0] == m
        g = WorldGraph(ctx.mem.data["maps"])
        g.blocked_now = frozenset(ctx.mem.temp_blocked)
        p = g.path(pos, goal)
        if p:
            return Decision(p[0], "proc_walk", f"procedure {run['goal']} {step.id}: walking to ({ax},{ay})")
        return None
