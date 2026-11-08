"""procedure_runner: precondition gating, bounded steps, abort-to-exploration, cap, and pause-on-heal."""
from __future__ import annotations

from pokeagent.explorer.procedures.state import of
from pokeagent.emulator import FakeEmulator
from pokeagent.explorer.context import ExplorerContext, ExplorerOptions
from pokeagent.explorer.memory import MapMemory
from pokeagent.explorer.behaviours.procedure_runner import HEAL_PAUSE_MAX, RUNNER_STEP_CAP, ProcedureRunner
from pokeagent.procedures import schema, store
from pokeagent.procedures.after_victory_rules import VictoryDecision

MAP, PX, PY = 0xD35E, 0xD362, 0xD361
NEVER = {"all": [{"map": 0x99}]}  # an effect that cannot hold in these fixtures: the step stays pending


def make_ctx(tmp_path, memory=None, **fields) -> ExplorerContext:
    run_dir = tmp_path / "runs" / "explore-1"
    run_dir.mkdir(parents=True, exist_ok=True)
    emu = FakeEmulator({MAP: 0x28, PX: 5, PY: 6, **(memory or {})})
    ctx = ExplorerContext(emu=emu, mem=MapMemory(tmp_path / "maps.json"), opts=ExplorerOptions(),
                          run_dir=run_dir, stable_frames=10, **fields)
    ctx.refresh()
    return ctx


def _proc(goal="potion", steps=None, **kw) -> schema.Procedure:
    return schema.Procedure(goal=goal, steps=steps or [], **kw)


def _buttons_step(pred=None, buttons=("UP",), effect=None):
    return schema.Step("s1", {"kind": "buttons", "buttons": list(buttons)},
                       pred or {"all": [{"map": 0x28}]}, effect or NEVER)


def _save(ctx, proc):
    return store.save(proc, ctx.run_dir.parent / "procedures")


def test_precondition_gates_the_runner(tmp_path):
    ctx = make_ctx(tmp_path)
    r = ProcedureRunner()
    _save(ctx, _proc(steps=[_buttons_step({"all": [{"map": 99}]}, effect=NEVER)]))
    assert not r.applies(ctx)  # the first step's precondition does not hold NOW
    _save(ctx, _proc(steps=[_buttons_step()]))
    r2 = ProcedureRunner()  # a fresh runner: the first cached the gated file for RELOAD_EVERY steps
    assert r2.applies(ctx)
    d = r2.step(ctx)
    assert d is not None and d.button == "UP"


def test_a_goto_step_walks_and_completes_the_procedure(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.mem.data["maps"]["40"] = {"visited": {"5,6": 1, "5,5": 1, "5,4": 1}, "blocked": [], "warps": {}}
    step = schema.Step("s1", {"kind": "goto", "map": 0x28, "x": 5, "y": 4},
                       {"all": [{"map": 0x28}]}, {"all": [{"at": [0x28, 5, 4]}]})
    _save(ctx, _proc(steps=[step]))
    r = ProcedureRunner()
    assert r.applies(ctx)
    d = r.step(ctx)
    assert d is not None and d.button == "UP"
    ctx.emu.set(PY, 4)
    ctx.refresh()
    r.step(ctx)  # the effect is met: the attempt is graded and saved
    assert of(ctx)["run"] is None
    saved = store.load("potion", ctx.run_dir.parent / "procedures")
    assert (saved.attempts, saved.successes) == (1, 1)


def test_a_step_failing_its_bounds_aborts_to_exploration(tmp_path):
    ctx = make_ctx(tmp_path)
    step = schema.Step("s1", {"kind": "buttons", "buttons": ["UP"]}, {"all": [{"map": 0x28}]},
                       NEVER, max_presses=0)
    _save(ctx, _proc(steps=[step]))
    r = ProcedureRunner()
    assert r.applies(ctx)
    assert r.step(ctx) is None and of(ctx)["run"] is None  # over budget: failed, state cleared
    saved = store.load("potion", ctx.run_dir.parent / "procedures")
    assert saved.attempts == 1 and saved.fail_streak == 1 and saved.steps[0].fail == 1


def test_a_downgraded_step_and_a_disabled_procedure_are_skipped(tmp_path):
    ctx = make_ctx(tmp_path)
    down = schema.Step("s1", {"kind": "buttons", "buttons": ["UP"]}, {"all": [{"map": 0x28}]},
                       NEVER, fail=2, ok=0)
    _save(ctx, _proc(steps=[down]))
    assert not ProcedureRunner().applies(ctx)  # downgraded: the runner returns control to exploration
    _save(ctx, _proc(steps=[_buttons_step()], disabled=True))
    assert not ProcedureRunner().applies(ctx)


def test_the_run_cap_stops_the_runner(tmp_path):
    ctx = make_ctx(tmp_path)
    of(ctx)["steps"] = RUNNER_STEP_CAP
    _save(ctx, _proc(steps=[_buttons_step()]))
    assert not ProcedureRunner().applies(ctx)


def test_a_heal_walk_pauses_the_pending_step_until_it_ends(tmp_path):
    from pokeagent.explorer import heal_walk
    from pokeagent.explorer.status_care import of as care_of
    ctx = make_ctx(tmp_path)
    _save(ctx, _proc(steps=[_buttons_step()]))
    r = ProcedureRunner()
    assert r.applies(ctx)
    of(ctx)["victory"] = VictoryDecision("heal", "", None, 0.4, 0.2, 2, "heal")
    assert r.applies(ctx)                       # a decision alone does not pause: the walk does
    assert heal_walk.start(ctx, "after_victory")
    assert not r.applies(ctx)                   # paused while the request lives
    assert r.step(ctx) is None
    care_of(ctx).pop("walk")                    # the walk ended (healed or abandoned)
    assert r.applies(ctx) and r.step(ctx).button == "UP"


def test_a_push_decision_resumes_immediately(tmp_path):
    ctx = make_ctx(tmp_path)
    _save(ctx, _proc(steps=[_buttons_step()]))
    r = ProcedureRunner()
    assert r.applies(ctx)
    of(ctx)["victory"] = VictoryDecision("push", "", 0.5, 0.9, 0.9, 2, "push")
    assert r.applies(ctx) and r.step(ctx).button == "UP"


def test_the_segment_goal_just_entered_keeps_its_procedure_live(tmp_path):
    # "potion" met (seeded) -> next unmet "left_house"? No: map 0x28 already marks left_house met, so the
    # previous ladder goal here is "left_house" only when potion is also met... potion is seeded -> unmet is
    # first_pokemon -> prev is left_house: its procedure resumes inside its own maps.
    ctx = make_ctx(tmp_path, initial_goals={"potion"})
    _save(ctx, _proc(goal="left_house", steps=[_buttons_step()]))
    r = ProcedureRunner()
    assert r.applies(ctx)
    assert of(ctx)["run"]["goal"] == "left_house"
