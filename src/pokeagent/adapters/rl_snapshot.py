"""RL trainer -> AgentSnapshot adapter: makes a tools/rl_train.py run visible to the viewer.

Same layer rule as explorer_snapshot: never imports viewer/. The trainer keeps its own status
file (``runs/rlstatus_<port>.json``); the adapter reads it for episode/win/epsilon fields and
asks the env for live screen state. ``brain_fn(obs)`` supplies the Thinking.brain line
(e.g. ``"OVERWORLD -> A(0.07)"``) - rl_train wires it to its Q table.
"""
from __future__ import annotations

import json
import time
from collections import deque
from pathlib import Path
from typing import Callable

from pokeagent import agent_registry
from pokeagent.control_server import ControlServer
from pokeagent.explorer.perceive import BATTLE_FLAG, battle_view
from pokeagent.ram import read_state
from pokeagent.snapshot import AgentSnapshot, DRIVERS, Event, Goal, Screen, Sees, Segment, Thinking

MAX_RECENT = 20


class RlAgentView:
    """Snapshot + minimal command surface for one RL training run.

    Mid-training presses would corrupt the episode, so press/steer/save/load raise (the
    control server turns that into a 500); pause/resume only flip an advisory flag shown in
    the snapshot - they do not stop the trainer."""

    def __init__(self, env, status_path: Path, *, agent_id: str, frame_slot: str = "",
                 root: Path = Path("."), segment: str = "", brain_fn: Callable | None = None) -> None:
        self.env, self.status_path = env, Path(status_path)
        self.agent_id, self.root, self.frame_slot = agent_id, Path(root), frame_slot
        self.segment_name, self._brain_fn = segment, brain_fn
        self._paused = False
        self.recent: deque[Event] = deque(maxlen=MAX_RECENT)
        self._ctl: ControlServer | None = None
        self._port = 0
        self._last_status: dict = {}

    # -- snapshot -----------------------------------------------------------------
    def _status(self) -> dict:
        try:
            data = json.loads(self.status_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._last_status = data
        except (OSError, ValueError):
            pass
        return self._last_status

    def _obs(self):
        try:
            return self.env._obs()  # noqa: SLF001 - same-repo trainer env; the obs IS the agent's vision
        except Exception:
            return None

    def _sees(self, obs) -> Sees:
        try:
            if self.env.emu.read(BATTLE_FLAG):
                return Sees(rows=list(battle_view(self.env.emu)), mode="battle")
        except Exception:
            pass
        if obs is None:
            return Sees(rows=["(no observation yet)"], mode="overworld")
        rows = [f"obs {list(obs)[:6]}", f"steps {getattr(self.env, 'steps', 0)}"]
        return Sees(rows=rows, mode="overworld")

    def _screen(self) -> Screen:
        try:
            rs = read_state(self.env.emu)
            return Screen(in_battle=bool(self.env.emu.read(BATTLE_FLAG)), party=int(self.env.emu.read(0xD163)),
                          money=rs.money)
        except Exception:
            return Screen()

    def snapshot(self) -> AgentSnapshot:
        st = self._status()
        obs = self._obs()
        episode = int(st.get("episode", 0))
        phase = str(st.get("phase", "TRAIN"))
        brain = ""
        if self._brain_fn is not None:
            try:
                brain = str(self._brain_fn(obs) or "")
            except Exception:
                brain = ""
        wins = int(st.get("wins", 0))
        eps = st.get("epsilon")
        last_act = self.recent[-1].text if self.recent else ""
        return AgentSnapshot(
            agent_id=self.agent_id, kind="rl",
            state="paused" if self._paused else "running",
            stop_reason="",
            step=int(getattr(self.env, "steps", 0)),
            segment=Segment(id=self.segment_name or "segment", name=self.segment_name or "segment",
                            steps=episode),
            goals=[Goal(id=self.segment_name or "segment", name=self.segment_name or "segment",
                        status="current", steps=episode)],
            thinking=Thinking(
                want=f"train {self.segment_name or '?'} ({phase.lower()})",
                plan=(f"eps {float(eps):.3f}" if isinstance(eps, (int, float)) else phase),
                blocker="", driver="rl", rule="", button=last_act, result="",
                brain=brain),
            drivers={d: (1 if d == "rl" else 0) for d in DRIVERS},
            drivers_available=["rl"],
            recent=[Event(step=episode, driver="rl", text=f"ep {episode} wins {wins}")] + list(self.recent),
            sees=self._sees(obs), screen=self._screen(), human_hold=False,
            frame_slot=self.frame_slot, updated_at=time.time())

    # -- commands -------------------------------------------------------------------
    def handlers(self) -> dict[str, Callable[..., dict]]:
        def deny(cmd: str):
            def _h(**_):
                raise ValueError(f"rl trainer: {cmd} is not supported mid-training")
            return _h

        return {
            "pause": lambda **_: setattr(self, "_paused", True) or {},
            "resume": lambda **_: setattr(self, "_paused", False) or {},
            "speed": lambda **_: {},
            "hold_release": lambda **_: {},
            "hand_to": lambda **_: {},
            "press": deny("press"),
            "steer": deny("steer"),
            "save_state": deny("save_state"),
            "load_state": deny("load_state"),
        }

    # -- serving ---------------------------------------------------------------------
    def serve(self, port: int = 0) -> int:
        self._ctl = ControlServer(self.snapshot, self.handlers(), port=port, token="")
        self._port = self._ctl.start()
        agent_registry.register(self.root, self.agent_id, "rl", self._port, self.frame_slot,
                                token=self._ctl.token)
        return self._port

    def close(self) -> None:
        if self._ctl is not None:
            self._ctl.stop()
            self._ctl = None
        agent_registry.unregister(self.root, self.agent_id)
