"""Control bar: target scope, pause/resume, speed, steer, hand-off, save/load, spawn, stop.

Widgets report intent to ``host`` (the viewer window); the bar never touches sources itself.
Three horizontal-group rows; ``BAR_TAG`` marks the first item so card areas can be re-inserted
before the bar on resize.
"""
from __future__ import annotations

import dearpygui.dearpygui as dpg

from pokeagent.viewer.ui.keys import handler

SPEED_LABELS = {1: "1x", 2: "2x", 4: "4x", 8: "8x"}
BAR_TAG = "bar_first"


class ControlBar:
    def __init__(self, parent, host) -> None:
        self.host = host
        self.speed_btn = None
        self.pause_btn = None
        self.steer_box = None
        self.hand_btns: dict[str, str | int] = {}
        self._build(parent)

    def _build(self, parent) -> None:
        # row 1: scope + transport
        with dpg.group(horizontal=True, parent=parent):
            dpg.add_combo(["All agents", "Selected"], default_value="All agents", width=100, tag=BAR_TAG,
                          callback=lambda s, a, u: self.host.set_scope("all" if a == "All agents" else "selected"))
            self.pause_btn = dpg.add_button(label="Pause", width=64,
                                            callback=lambda s, a, u: self.host.toggle_pause())
            self.speed_btn = dpg.add_button(label="1x", width=44,
                                            callback=lambda s, a, u: self.host.cycle_speed())
            self.steer_box = dpg.add_checkbox(label="Steering (focus view)", default_value=False, enabled=False)
        # row 2: hand-off + state slots
        with dpg.group(horizontal=True, parent=parent):
            for drv in ("rl", "explorer"):
                self.hand_btns[drv] = dpg.add_button(label=f"Hand to {drv.title()}", width=96,
                                                     callback=handler(self.host.hand_to, drv))
            dpg.add_input_text(tag="state_name", width=110, hint="state name")
            dpg.add_button(label="Save", width=52,
                           callback=lambda s, a, u: self.host.save_state(dpg.get_value("state_name")))
            dpg.add_button(label="Load", width=52,
                           callback=lambda s, a, u: self.host.load_state(dpg.get_value("state_name")))
        # row 3: spawn + lifecycle
        with dpg.group(horizontal=True, parent=parent):
            dpg.add_combo(["explorer", "rl"], default_value="explorer", tag="spawn_kind", width=90)
            dpg.add_input_text(tag="spawn_args", width=170, hint="args (space separated)")
            dpg.add_button(label="Spawn", width=56, tag="spawn_btn",
                           callback=lambda s, a, u: self.host.spawn_agent(
                               dpg.get_value("spawn_kind"), dpg.get_value("spawn_args")))
            dpg.add_text("", tag="spawn_status")
            dpg.add_button(label="Stop", width=48, callback=lambda s, a, u: self.host.stop_targets())
            dpg.add_button(label="Release", width=64,
                           callback=lambda s, a, u: self.host.send_to_targets("hold_release"))

    def refresh(self) -> None:
        """Per-frame cheap updates: speed label, pause label, hand-off availability."""
        if self.speed_btn is not None and dpg.does_item_exist(self.speed_btn):
            dpg.set_item_label(self.speed_btn, SPEED_LABELS.get(self.host.speed(), "1x"))
        if self.pause_btn is not None and dpg.does_item_exist(self.pause_btn):
            dpg.set_item_label(self.pause_btn, "Resume" if self.host.paused() else "Pause")
        if self.steer_box is not None and dpg.does_item_exist(self.steer_box):
            dpg.set_value(self.steer_box, self.host.steering())
        if dpg.does_item_exist("spawn_btn"):
            capped = self.host.at_agent_cap()
            dpg.configure_item("spawn_btn", enabled=not capped)
            dpg.set_value("spawn_status", self.host.spawn_msg or ("agent limit reached" if capped else ""))
        snaps = self.host.target_snaps()
        for drv, tag in self.hand_btns.items():
            if dpg.does_item_exist(tag):
                dpg.configure_item(tag, enabled=any(drv in (s.drivers_available or []) for s in snaps))
