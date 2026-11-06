"""MacroController: drives one macro a tick at a time from the agent's frame loop.

``tick()`` (emulator thread, once per frame, after the bridge pump) advances the running macro by ONE step, so frames keep
publishing, Tk keeps pumping and the snapshot keeps refreshing while it works. ``command()`` is the HTTP-thread side: it
starts the macro on the emulator thread and waits for its result up to ``wait_s``; past that it answers "pending" (a 504) and
the macro keeps running, visible as ``macro_status`` in the snapshot extra and stoppable with ``macro_cancel``.
A macro that Claude started without a lease takes an automatic one and releases it when the macro ends.
"""
from __future__ import annotations

from pokeagent.intervene.macro_core import MacroRun
from pokeagent.intervene.macros import make_run
from pokeagent.intervene.rig import EmuRig
from pokeagent.snapshot import Event

AUTO_LEASE_S = 65   # a little longer than the macro deadline
WAIT_S = 70.0


class MacroController:
    def __init__(self, view, rig_factory=None) -> None:
        self.view = view
        self.rig_factory = rig_factory or (lambda name: EmuRig(view.ctx, view.driver, name))
        self.run: MacroRun | None = None
        self.last: dict | None = None
        self._auto = False

    # -- emulator thread --------------------------------------------------------------
    def start(self, name: str, args: dict | None) -> MacroRun:
        if self.run is not None:
            return MacroRun.failed(name, "macro_busy")
        hold = self.view.claude_hold
        self._auto = not hold.active()
        if self._auto:
            hold.grant(AUTO_LEASE_S)  # the agent must not decide between a macro's steps
        run = make_run(self.rig_factory(name), name, args)
        self.run = run
        if run.done:
            self._end(run)
        return run

    def tick(self) -> None:
        run = self.run
        if run is None:
            return
        try:
            run.advance()
        except Exception as exc:  # a macro bug must not take the agent's loop down
            run.result = {"ok": False, "result": f"error: {exc!r}", "presses": run.presses}
            run.finished.set()
        if run.done:
            self._end(run)
        elif self.view.claude_hold.active():
            self.view.claude_hold.touch()

    def _end(self, run: MacroRun) -> None:
        self.last = run.status()
        self.run = None
        if self._auto:
            self.view.claude_hold.release()  # our own lease goes with the macro; an explicit hold stays
        self.view.recent.append(Event(step=self.view.ctx.step, driver="claude", text=f"macro {run.name}: {run.result['result']}"))

    def cancel(self) -> dict:
        if self.run is None:
            return {"ok": False, "result": "no_macro_running"}
        self.run.cancel()
        return {"cancelling": self.run.name}

    def status(self) -> dict | None:
        return self.run.status() if self.run is not None else self.last

    # -- HTTP thread ---------------------------------------------------------------------
    def command(self, name: str, args: dict | None = None, wait_s: float = WAIT_S, **_) -> dict:
        bridge = self.view.bridge
        if not bridge.marshal:  # tests: no emulator loop, so drive it inline
            run = self.start(name, args)
            while self.run is not None:
                self.tick()
            return run.result
        try:
            run = bridge.call(lambda: self.start(name, args))
        except TimeoutError as exc:
            return {"error": str(exc)}
        if run.finished.wait(wait_s):
            return run.result
        return {"ok": False, "result": "pending", "error": "macro still running: see macro_status, stop it with macro_cancel",
                "macro_status": self.status()}
