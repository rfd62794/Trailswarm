"""ViewerWindow host API for the control bar and keys: transport, scope, targets, spawn/stop, key presses.

A mixin (one job: turn UI actions into commands for the target agents) split from ``window.py`` to
keep both under the module size cap. Expects the host to provide ``model``, ``sources``, ``focus``,
``selected``, ``scope``, ``supervisor``, ``_spawn``, ``_outbox``, ``_throttle``, ``_gate``, ``_speed``,
``_paused`` and ``leave_focus``/``_send_one``/``_target_ids``/``_pid_for``.
"""
from __future__ import annotations

from pokeagent.viewer import steering, commands


class CommandHostMixin:
    # -- host API for control_bar / keys ----------------------------------------
    def set_scope(self, scope: str) -> None:
        self.scope = scope

    def selected_id(self) -> str | None:
        return self.selected

    def speed(self) -> int:
        return self._speed

    def paused(self) -> bool:
        return self._paused

    def cycle_speed(self) -> None:
        self._speed = commands.next_speed(self._speed)
        self.send_to_targets("speed", n=self._speed)

    def toggle_pause(self) -> None:
        self._paused = not self._paused
        self.send_to_targets("pause" if self._paused else "resume")

    def steering(self) -> bool:
        """Read-only: keyboard steering is on exactly while an agent is focused."""
        return self.focus.focused is not None

    def target_snaps(self):
        return [s for aid in self._target_ids() if (s := self.model.snapshot(aid)) is not None]

    def hand_to(self, driver: str) -> None:
        self.send_to_targets("hand_to", driver=driver)

    def save_state(self, name: str) -> None:
        self.send_to_targets("save_state", name=name or "slot")

    def load_state(self, name: str) -> None:
        self.send_to_targets("load_state", name=name or "slot")

    def at_agent_cap(self) -> bool:
        """Cached (refreshed off the UI thread every 2 s): True when spawning is disabled."""
        self._spawn.refresh()
        return self._spawn.capped

    @property
    def spawn_msg(self) -> str:
        return self._spawn.message

    def spawn_agent(self, kind: str, args: str) -> None:
        self._spawn.spawn(kind, args)

    def stop_targets(self) -> None:
        if self.supervisor is not None:
            for aid in self._target_ids():
                pid = self._pid_for(aid)
                if pid is not None:
                    self.supervisor.stop(pid)

    def send_to_targets(self, cmd: str, **args) -> None:
        for aid in self._target_ids():
            src = self.sources.get(aid)
            if src is not None:
                self._outbox.put((src, cmd, args))

    def key_button(self, key_name: str) -> None:
        """Game key: reaches only the focused agent (never in grid view), <=1 press / 120 ms / key."""
        hit = steering.press_target(key_name, self.focus.focused, self._throttle)
        if hit is not None:
            self._send_one(hit[0], "press", button=hit[1], source="human")

    def hotkey(self, name: str) -> None:
        """P / T: transport hotkeys, focus view only, one toggle per physical press."""
        if self.focus.focused is not None and self._gate.allow(name):
            self.toggle_pause() if name == "pause" else self.cycle_speed()

    def escape(self) -> None:
        self.leave_focus()
