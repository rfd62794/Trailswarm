"""Explorer -> AgentSnapshot adapter: makes an ExplorerContext/Engine demo visible to the viewer.

Layer rule: this module (and every adapters/ module) NEVER imports viewer/ - it only produces
``pokeagent.snapshot.AgentSnapshot`` and serves ``pokeagent.control_server`` commands. The demo
keeps its own --control-port HTTP API untouched; this adapter adds the viewer-facing one.
"""
from __future__ import annotations

import logging
import os
import time
from collections import deque
from pathlib import Path
from typing import Callable

from pokeagent import agent_registry
from pokeagent.adapters.bridge import EmuBridge
from pokeagent.adapters.event_feed import EventFeed
from pokeagent.adapters.party_panel import party_rows
from pokeagent.control_server import ControlServer
from pokeagent.explorer import perceive
from pokeagent.goals import SIDE_GOALS
from pokeagent.explorer.perceive import BATTLE_FLAG, TILEMAP, TILEMAP_LEN, box_open, frame_lines
from pokeagent.human_hold import HumanHold
from pokeagent.intervene import extra as intervene_extra
from pokeagent.intervene.handlers import intervene_handlers
from pokeagent.intervene.lease import LEASE_FILE, ClaudeHold
from pokeagent.intervene.rig import ClaudeDriver
from pokeagent.intervene.runner import MacroController
from pokeagent.ram import read_state
from pokeagent.snapshot import AgentSnapshot, DRIVERS, Event, Goal, Screen, Sees, Segment, Thinking

MAX_RECENT = 20
_STATE_DIRS = (Path("runs") / "states", Path("baselines"), Path("."))


def _ret(value=None) -> dict:
    return {}


class ExplorerAgentView:
    """Snapshot + command surface for one explorer demo. ``press`` with source "human" (or any
    viewer Steer key) feeds ``HumanHold`` so the agent stops deciding while a human drives."""

    def __init__(self, ctx, emu, mem, engine, presser, *, agent_id: str = "explorer",
                 root: Path = Path("."), frame_slot: str = "", marshal: bool = True,
                 refresh_every: int = 6) -> None:
        self.ctx, self.emu, self.mem, self.engine, self.presser = ctx, emu, mem, engine, presser
        self.agent_id, self.root, self.frame_slot = agent_id, Path(root), frame_slot
        self.hold = HumanHold()
        run_dir = getattr(ctx, "run_dir", None)
        self.claude_hold = ClaudeHold(Path(run_dir) / LEASE_FILE if run_dir and Path(run_dir).is_dir() else None)
        self.tracker = intervene_extra.Tracker()
        if engine.decision_log is not None:
            engine.decision_log.listeners.append(self.tracker.add_decision)
        self.driver = ClaudeDriver(ctx, presser, engine.decision_log, self.claude_hold)
        self.macros = MacroController(self)
        self.feed = EventFeed()
        self.recent: deque[Event] = deque(maxlen=MAX_RECENT)
        self._presses: dict[str, int] = {}
        self._ctl: ControlServer | None = None
        self._port = 0
        # HTTP threads never touch the emulator: commands run in tick() on the emulator thread and
        # snapshot() returns a copy built there. marshal=False (tests) runs everything inline.
        self.bridge = EmuBridge(self._build, every=refresh_every, marshal=marshal)

    def held(self) -> bool:
        """Does anyone (a human steering, or Claude's lease) hold the agent? The decision loop skips its own step while True."""
        return self.hold.active() or self.claude_hold.active()

    def tick(self) -> None:
        """Call once per frame from the emulator's own loop."""
        self.bridge.tick()
        self.claude_hold.refresh()  # keep the watchdog's lease mirror fresh while held
        self.macros.tick()          # one macro step per frame: frames and snapshots keep flowing

    # -- snapshot -----------------------------------------------------------------
    def _last_decision(self):
        return getattr(self.engine, "last_decision", None)

    def _last_outcome(self) -> str:
        pending = getattr(self.engine, "_pending_outcomes", None) or []
        return str(pending[-1].get("outcome", "")) if pending else ""

    def _sees(self) -> Sees:
        try:
            if self.emu.read(BATTLE_FLAG) != 0 or self.ctx.view.battling:
                return Sees(rows=list(perceive.battle_view(self.emu)), mode="battle")
            vis = perceive.ascii_vision(self.emu, self.mem, self.emu.read(0xD367))
            rows = list(vis) + ([vis.legend] if getattr(vis, "legend", "") else [])  # Rendered is a list
            return Sees(rows=rows, mode="overworld")
        except Exception:
            logging.getLogger(__name__).warning("sees build failed", exc_info=True)
            return Sees()

    def _screen(self) -> Screen:
        try:
            tm = self.emu.read_range(TILEMAP, TILEMAP_LEN)
            lines = frame_lines(tm) if box_open(tm) else []
            rs = read_state(self.emu)
            return Screen(box_text=" | ".join(lines)[:200], in_battle=bool(self.emu.read(BATTLE_FLAG)),
                          party=party_rows(self.emu), money=rs.money, bag_summary="")
        except Exception:
            return Screen()

    def _extra(self) -> dict:
        try:
            out = intervene_extra.build(self.ctx, self.emu, self.tracker, self._screen().box_text)
            out["macro_status"] = self.macros.status()
            return out
        except Exception:
            logging.getLogger(__name__).warning("intervene extra failed", exc_info=True)
            return {}

    def snapshot(self) -> AgentSnapshot:
        return self.bridge.snapshot()

    def _build(self) -> AgentSnapshot:
        ctx = self.ctx
        done = bool(ctx.done)
        check = ctx.goals()
        current = next((k for k, v in check.items() if not v and k not in SIDE_GOALS), "")
        dec = self._last_decision()
        want = " ".join(str(ctx.goto)) if ctx.goto else (current or "explore")
        try:  # the event stream is derived here, on the emulator thread; it must never break the snapshot
            self.feed.observe(self.emu, ctx, self.mem, dec, self._last_outcome(), self.hold.active(), check)
        except Exception:
            logging.getLogger(__name__).warning("event feed failed", exc_info=True)
        return AgentSnapshot(
            agent_id=self.agent_id, kind="explorer",
            state="stopped" if done else "paused" if ctx.paused else "running",
            stop_reason=(ctx.opts.stop_at_goal or "done") if done else "",
            step=ctx.step,
            segment=Segment(id="run", name=current or ctx.opts.stop_at_goal or "explore",
                            steps=ctx.step),
            goals=[Goal(id=k, name=k, status="done" if v else ("current" if k == current else "ahead"))
                   for k, v in sorted(check.items())],
            thinking=Thinking(want=want, plan=(dec.why if dec else "") or (dec.behaviour if dec else ""),
                              blocker=str(ctx.last_fail) if ctx.last_fail else "",
                              driver="explorer", rule=(dec.rule if dec else ""),
                              button=(dec.button if dec else ""), result=self._last_outcome()),
            drivers={d: (self._presses.get(d, 0) if d in ("human", "claude") else 0) for d in DRIVERS},
            drivers_available=["explorer", "human"],
            recent=list(self.recent),
            sees=self._sees(), screen=self._screen(), human_hold=self.hold.active(),
            claude_hold_s=round(self.claude_hold.remaining(), 1), extra=self._extra(),
            frame_slot=self.frame_slot, updated_at=time.time())

    # -- commands -------------------------------------------------------------------
    def _state_path(self, name: str) -> Path:
        p = Path(name)
        if p.suffix == ".state" and p.exists():
            return p
        for d in _STATE_DIRS:
            cand = d / f"{name}.state"
            if cand.exists():
                return cand
        return Path("runs") / "states" / f"{name}.state"

    def handlers(self) -> dict[str, Callable[..., dict]]:
        ctx, presser, hold = self.ctx, self.presser, self.hold

        def press(button: str, source: str = "human", **_) -> dict:
            self._presses[source] = self._presses.get(source, 0) + 1
            if source == "human":
                hold.touch()
            if source == "claude":
                self.driver.press(button, f"remote press {button}")  # refreshes the lease, marks decisions.jsonl
            else:
                presser.press(button, source, f"viewer press {button}")
            self.recent.append(Event(step=ctx.step, driver=source, text=f"press {button}"))
            return {}

        def save_state(name: str, **_) -> dict:
            path = self._state_path(name)
            path.parent.mkdir(parents=True, exist_ok=True)
            self.emu.save_state(path)
            return {"path": str(path)}

        def load_state(name: str, **_) -> dict:
            self.emu.load_state(self._state_path(name))
            self.recent.append(Event(step=ctx.step, driver="human", text=f"load {name}"))
            return {}

        raw = {
            "pause": lambda **_: _ret(setattr(ctx, "paused", True)),
            "resume": lambda **_: _ret(setattr(ctx, "paused", False)),
            "speed": lambda n, **_: _ret(setattr(ctx, "speed", int(n))),
            "press": press,
            "steer": lambda on, **_: _ret(hold.touch() if on else None),
            "hand_to": lambda driver, **_: _ret(hold.touch() if driver == "human" else hold.release()),
            "save_state": save_state,
            "load_state": load_state,
        }
        extra = intervene_handlers(self)
        raw.update(extra)
        wrapped = {name: self.bridge.wrap(h) for name, h in raw.items()}
        wrapped["macro"] = self.macros.command  # starts on the emulator thread, then waits on the HTTP thread
        return wrapped

    # -- serving ---------------------------------------------------------------------
    def serve(self, port: int = 0, agent_id: str | None = None) -> int:
        """Start the viewer-facing control server + registry entry; returns the port."""
        self._ctl = ControlServer(self.snapshot, self.handlers(), port=port, token="",
                                 events_fn=self.feed.bus.payload)
        self._port = self._ctl.start()
        agent_registry.register(self.root, agent_id or self.agent_id, "explorer", self._port,
                                self.frame_slot, pid=os.getpid(), token=self._ctl.token)
        return self._port

    def close(self) -> None:
        if self._ctl is not None:
            self._ctl.stop()
            self._ctl = None
        agent_registry.unregister(self.root, self.agent_id)
