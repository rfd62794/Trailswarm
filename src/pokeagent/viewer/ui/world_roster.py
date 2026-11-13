"""World side panel roster: one row per agent - colour swatch, name, goal/stage, the fighter's HP bar and level, idle seconds."""
from __future__ import annotations

import time

import dearpygui.dearpygui as dpg

from pokeagent.viewer.health import OK
from pokeagent.viewer.roster import fmt_idle
from pokeagent.viewer.theme_colours import state_rgb, text_rgba
from pokeagent.viewer.ui import theme
from pokeagent.viewer.ui_scale import px

REFRESH_S = 0.5


class Roster:
    def __init__(self, parent, view) -> None:
        self.view = view
        self.box = dpg.add_child_window(parent=parent, height=px(110), border=False)
        self._sig: tuple = ()
        self._at = 0.0

    def update(self, wrap: int) -> None:
        now = time.monotonic()
        if now - self._at < REFRESH_S:
            return
        self._at = now
        rows = self.view.roster_rows()
        sig = (tuple((r.agent_id, r.stage, r.hp, r.max_hp, r.level, int(r.idle_s), r.state) for r in rows), self.view.selected_id, theme.mode())
        if sig == self._sig:
            return
        self._sig = sig
        dpg.delete_item(self.box, children_only=True)
        if not rows:
            dpg.add_text("no agents yet", parent=self.box)
        mode = theme.mode()
        for r in rows:
            with dpg.group(horizontal=True, parent=self.box):
                dpg.add_color_button((*r.colour, 255), width=px(14), height=px(14), no_alpha=True, no_tooltip=True)
                dpg.add_text(r.name + (" <" if r.agent_id == self.view.selected_id else ""), color=state_rgb(r.state, r.state == OK, mode))
                dpg.add_text(r.stage or "-", color=text_rgba(mode, "dim"))
            with dpg.group(horizontal=True, parent=self.box, indent=px(20)):
                if r.max_hp:
                    dpg.add_progress_bar(default_value=r.hp_frac, width=px(90), height=px(10), overlay=f"{r.hp}/{r.max_hp}")
                    dpg.add_text(f"L{r.level}")
                dpg.add_text(f"idle {fmt_idle(r.idle_s)}", color=text_rgba(mode, "dim"))
