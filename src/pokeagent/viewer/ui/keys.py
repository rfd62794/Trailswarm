"""Keyboard mapping -> viewer commands. Keys reach an agent only while Steer is on.

DPG has no global key callback, so each mapped key gets a press handler; unmapped keys are
ignored. Text-entry widgets (state name, spawn args) suppress game keys while focused.
"""
from __future__ import annotations

import dearpygui.dearpygui as dpg

from pokeagent.viewer.commands import KEYMAP

_DPG_KEYS = {
    "Up": dpg.mvKey_Up, "Down": dpg.mvKey_Down, "Left": dpg.mvKey_Left, "Right": dpg.mvKey_Right,
    "a": dpg.mvKey_A, "s": dpg.mvKey_S, "Return": dpg.mvKey_Return,
    "Shift_L": dpg.mvKey_LShift, "Shift_R": dpg.mvKey_RShift,
}
_TEXT_ITEMS = ("state_name", "spawn_args")


def install(host) -> None:
    """Register key handlers on ``host`` (the viewer window) inside a handler registry."""

    def button(key_name: str):
        if any(dpg.is_item_active(t) for t in _TEXT_ITEMS if dpg.does_item_exist(t)):
            return
        host.key_button(key_name)

    with dpg.handler_registry(show=True, tag="viewer_keys"):
        for name, dpg_key in _DPG_KEYS.items():
            dpg.add_key_press_handler(dpg_key, callback=lambda s, a, u, n=name: button(n))
        dpg.add_key_press_handler(dpg.mvKey_Escape, callback=lambda s, a, u: host.escape())
        dpg.add_key_press_handler(dpg.mvKey_P, callback=lambda s, a, u: host.toggle_pause())
        dpg.add_key_press_handler(dpg.mvKey_T, callback=lambda s, a, u: host.cycle_speed())
