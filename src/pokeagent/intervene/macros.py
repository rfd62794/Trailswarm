"""The macro registry plus the simple macros: wait, back_out, battle_run.

Every macro here and in macros_battle / macros_goto is built from its args by a ``build(args) -> (step_fn, cap)`` function;
``run_macro(rig, name, args)`` runs one and never raises (bad args come back as ``{"ok": False, "result": "bad_args: ..."}``).
"""
from __future__ import annotations

from pokeagent.explorer.behaviours.switch_out import run_press
from pokeagent.intervene.macro_core import MacroArgError, Step, press, run_steps
from pokeagent.intervene.screen import ScreenRead, main_menu

MAX_WAIT_FRAMES = 600
RUN_TRIES = 4


def build_wait(args: dict):
    frames = int(args.get("frames", 60))
    if not 1 <= frames <= MAX_WAIT_FRAMES:
        raise MacroArgError(f"frames must be 1..{MAX_WAIT_FRAMES}")

    def step(scr: ScreenRead, st: dict, rig) -> Step:
        if st.get("waited"):
            return Step(done="waited")
        st["waited"] = True
        return Step(wait=frames)
    return step, 1


def build_back_out(args: dict):
    """B until the bare overworld or the battle main menu. Stops when the screen stops changing."""
    def step(scr: ScreenRead, st: dict, rig) -> Step:
        if scr.in_battle and _main(scr):
            return Step(done="battle_menu")
        if not scr.in_battle and not scr.busy:
            return Step(done="overworld")
        sig = (tuple(scr.screen), scr.cur)
        st["same"] = st.get("same", 0) + 1 if sig == st.get("sig") else 0
        st["sig"] = sig
        if st["same"] >= 4:
            return Step(stop="screen_unchanged")  # B is not moving this screen: a person should look
        return press("B", "backing out")
    return step, 20


def _main(scr: ScreenRead) -> bool:
    return main_menu(scr.frames)


def build_battle_run(args: dict):
    """Walk the battle menu to RUN and confirm; clear the 'Got away safely!' text. A trainer battle stops, it cannot be fled."""
    def step(scr: ScreenRead, st: dict, rig) -> Step:
        text = scr.text.lower()
        if not scr.in_battle:
            if not st.get("ran"):
                return Step(stop="not_in_battle")
            return press("B", "clearing the escape text") if scr.busy else Step(done="escaped")
        if "no running" in text:
            return Step(stop="trainer_battle")
        if _main(scr):
            if st.get("tries", 0) >= RUN_TRIES:
                return Step(stop="run_failed")
            p = run_press(scr.frames)
            if p == "A":
                st["ran"], st["tries"] = True, st.get("tries", 0) + 1
            return press(p or "DOWN", "toward RUN")
        if scr.menu:
            return press("B", "leaving a submenu")  # move list, bag, party: not where RUN is
        if scr.box:
            return press("A", "advancing battle text")
        return Step(wait=10)
    return step, 40


def _registry() -> dict:
    from pokeagent.intervene.macros_battle import build_fight, build_switch, build_use_item
    from pokeagent.intervene.macros_goto import build_goto
    return {"back_out": build_back_out, "battle_run": build_battle_run, "battle_fight": build_fight,
            "use_item": build_use_item, "switch": build_switch, "goto": build_goto, "wait": build_wait}


def macro_names() -> list[str]:
    return sorted(_registry())


def run_macro(rig, name: str, args: dict | None = None) -> dict:
    build = _registry().get(name)
    if build is None:
        return {"ok": False, "result": f"unknown_macro: {name} (have {', '.join(macro_names())})", "presses": 0}
    try:
        step, cap = build(args or {})
    except (MacroArgError, ValueError, KeyError, TypeError) as exc:
        return {"ok": False, "result": f"bad_args: {exc}", "presses": 0}
    return run_steps(step, rig, name, cap)
