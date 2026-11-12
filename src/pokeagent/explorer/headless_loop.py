"""The headless run loop: everything the demo's Tk ``frame()`` did, minus Tk.

``tools/explore_demo.py --headless`` (the swarm learners) must never import or create Tk - a window
that appears on Robert's screen is a hard-rule violation, and a hidden ``root.mainloop()`` still
spent 16% of the profile pumping Tk callbacks. A plain ``while`` drives one emulator tick per
iteration, the control API's job queue drains between ticks, and ``os._exit(0)`` on ``ctx.done``
keeps the swarm-parent contract (a swarm round waits on the process).

``LogRing`` is what the console ``Text`` widget was: a bounded tail in memory plus an append to
``<run dir>/console.log`` that drains on the run's 50-step cadence and on ``close`` - not per line.
"""
from __future__ import annotations

import os
from collections import deque
from pathlib import Path

from pokeagent.explorer.jsonl_buf import FLUSH_EVERY
from pokeagent.explorer.perceive import TILEMAP, TILEMAP_LEN, box_open
from pokeagent.fsutil import where

TAIL = 400  # log lines kept in memory as the run's console tail


class LogRing:
    """``log(text, tag)`` with the Text-writer's signature: a bounded tail plus a buffered
    console.log append. Lines are held until the ``every``-step cadence (``tick``) or ``close`` -
    the same bound JsonlBuffer accepts - so the hot path stops paying a write+flush per line."""

    def __init__(self, path: Path | str, tail: int = TAIL, every: int = FLUSH_EVERY) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.tail: deque = deque(maxlen=tail)
        self.every = every
        self._fh = path.open("a", encoding="utf-8")
        self._lines: list[str] = []

    def __call__(self, text, tag=None) -> None:
        line = str(text)
        self.tail.append(line)
        self._lines.append(line + "\n")

    def tick(self, step: int) -> None:
        """The shared drain cadence: ``run`` ticks it once per iteration, it drains every ``every`` steps."""
        if self._fh is not None and self.every and step % self.every == 0:
            self._drain(self._fh)

    def _drain(self, fh) -> None:
        if self._lines:
            fh.write("".join(self._lines))
            self._lines.clear()
            fh.flush()

    def close(self) -> None:
        fh, self._fh = self._fh, None
        if fh is not None:
            try:
                self._drain(fh)
            finally:
                fh.close()


def run(ctx, engine, *, jobs, on_exit=None, agent_view=None, frame_pub=None, frame_every: int = 2,
        exit_fn=None) -> None:
    """Drive the agent until ``ctx.done``: one tick per iteration, control jobs drained between
    ticks, ``on_exit()`` cleanup then ``exit_fn(0)`` exactly like the old Tk loop's headless branch.
    ``exit_fn`` is injectable so tests and the perf probe can outlive the run; ``None`` resolves
    ``os._exit`` at call time, so a trap installed after this module was imported still works.
    ``on_exit`` runs exactly once on every exit path: the ``finally`` keeps a crash or Ctrl-C in
    the loop from skipping the buffered-log drain (``exit_fn`` itself stays clean-path only)."""
    o, emu = ctx.opts, ctx.emu
    log_tick = getattr(ctx.log, "tick", None)  # a LogRing shares the run's 50-step drain cadence
    try:
        while True:
            agent_view and agent_view.tick()  # viewer commands + cached snapshot, on this (emulator) thread
            while not jobs.empty():  # remote-control jobs run here, on the emulator's thread
                fn, fut = jobs.get()
                try:
                    fut.set_result(fn())
                except Exception as e:
                    fut.set_exception(e)
            if ctx.done:  # a finished headless agent must EXIT (swarm rounds wait on it)
                break
            if frame_pub is not None and ctx.frame % max(1, frame_every) == 0:
                try:
                    frame_pub.publish()  # render this tick anyway and publish it (no extra game frame)
                except Exception:
                    emu.tick(1)
            else:
                emu.tick(1)  # no rendering at all
            ctx.frame += 1
            tm = emu.read_range(TILEMAP, TILEMAP_LEN)
            ctx.box_open_now = box_open(tm)
            h = hash(tm)  # screen tiles only; wandering NPCs must not count as a cutscene
            ctx.stable_frames = ctx.stable_frames + 1 if h == ctx.last_hash else 0
            ctx.last_hash = h
            try:
                pace = (o.frames_per_step if o.adaptive_pace else o.box_pace) \
                    if (o.box_pace and ctx.box_open_now) else o.frames_per_step
                if ctx.slow_until > ctx.step:
                    pace = max(pace, 40)  # some tasks need a slower hand (Mom's heal, fades): per-task speed
                hold = agent_view.held() if agent_view is not None else False
                if not ctx.paused and not hold and ctx.frame % pace == 0:
                    engine.step()  # human hold (viewer Steer) pauses agent decisions, not the game
            except Exception as e:  # never let one bad step kill the loop: log it and keep going
                ctx.log(f"[agent step error: {e!r}{where(e)}]", "res")
            log_tick and log_tick(ctx.step)
    finally:
        try:
            on_exit and on_exit()
        except Exception:
            pass
    (exit_fn or os._exit)(0)
