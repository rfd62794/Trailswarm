"""Keyboard mapping -> viewer commands. Keys reach an agent only in focus view (steering is automatic there).

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


def handler(fn, *args):
    """A DPG callback taking exactly (sender, app_data, user_data). DPG passes None for any extra
    parameter, so a default-arg lambda (``lambda s, a, u, n=name: ...``) silently loses ``n``."""
    def callback(sender=None, app_data=None, user_data=None):
        fn(*args)
    return callback


def install(host) -> None:
    """Register key handlers on ``host`` (the viewer window) inside a handler registry."""

    def typing() -> bool:
        return any(dpg.is_item_active(t) for t in _TEXT_ITEMS if dpg.does_item_exist(t))

    def button(key_name: str):
        if not typing():
            host.key_button(key_name)

    def hotkey(name: str):
        if not typing():
            host.hotkey(name)

    with dpg.handler_registry(show=True, tag="viewer_keys"):
        for name, dpg_key in _DPG_KEYS.items():
            dpg.add_key_press_handler(dpg_key, callback=handler(button, name))
        dpg.add_key_press_handler(dpg.mvKey_Escape, callback=handler(host.escape))
        dpg.add_key_press_handler(dpg.mvKey_P, callback=handler(hotkey, "pause"))
        dpg.add_key_press_handler(dpg.mvKey_T, callback=handler(hotkey, "speed"))
