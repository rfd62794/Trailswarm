"""Stadium pane: the battle strip as a real top-level window (movable/resizable, persisted by init_file).

Same ``Slot`` widgets the old side-panel strip used (live frame + battle card + HP bars), fed by
``WorldModel.stadium(now)``, at most ``stadium.MAX_CARDS``. Shown/hidden by the View menu checkbox;
click on a slot still focuses that agent.
"""
from __future__ import annotations

import time

import dearpygui.dearpygui as dpg

from pokeagent.viewer.panels.render import frame_rgba
from pokeagent.viewer.ui import tags
from pokeagent.viewer.ui_scale import px
from pokeagent.world import stadium

FW, FH = 120, 108              # live frame in a stadium panel (unchanged from the old strip)
FRAME_S = 0.1                  # a slot re-uploads its live frame at most this often
PANE_W, PANE_H = 560, 240      # untuned first values: default pane size in 1x px


class Slot:
    """One stadium panel: live frame (click = focus view) next to the battle card."""

    def __init__(self, parent, idx: int, on_focus) -> None:
        self.aid: str | None = None
        self._on_focus = on_focus
        self._last = 0.0
        self.tex = dpg.add_raw_texture(FW, FH, [0.0] * (FW * FH * 4), parent=tags.VIEWER_TEX)  # texture stays 1x; the button scales it
        self.group = dpg.add_group(horizontal=True, parent=parent, show=False)
        self.btn = dpg.add_image_button(self.tex, width=px(FW), height=px(FH), parent=self.group,
                                        callback=lambda s, a, u: self.click())
        with dpg.group(parent=self.group):
            self.title = dpg.add_text("")
            self.text = dpg.add_text("")
            self.you = dpg.add_progress_bar(width=px(200), overlay="you")
            self.foe = dpg.add_progress_bar(width=px(200), overlay="enemy")

    def click(self) -> None:
        if self.aid:
            self._on_focus(self.aid)

    def show(self, aid: str, card, frame, now: float) -> None:
        self.aid = aid
        dpg.show_item(self.group)
        rows = stadium.lines(card)
        dpg.set_value(self.title, f"{aid}")
        dpg.set_value(self.text, "\n".join(rows[0:1] + rows[2:]))
        dpg.set_value(self.you, stadium.hp_frac(card.hp, card.max_hp))
        dpg.set_value(self.foe, stadium.hp_frac(card.enemy_hp, card.enemy_max_hp))
        if frame is not None and now - self._last > FRAME_S:
            self._last = now
            dpg.set_value(self.tex, frame_rgba(frame[0], frame[1], frame[2], FW, FH))

    def hide(self) -> None:
        self.aid = None
        dpg.hide_item(self.group)


class StadiumPane:
    """The top-level ``STADIUM_PANE`` window: ``Slot`` widgets plus the overflow note."""

    def __init__(self, on_focus) -> None:
        self.win = dpg.add_window(tag=tags.STADIUM_PANE, label="Stadium",
                                  width=px(PANE_W), height=px(PANE_H), show=False)
        with dpg.group(parent=self.win):
            self.title = dpg.add_text("Stadium")
            self.slots_parent = dpg.add_group()
            self.more = dpg.add_text("", color=(255, 200, 80, 255))
        self.slots = [Slot(self.slots_parent, i, on_focus) for i in range(stadium.MAX_CARDS)]

    def set_visible(self, on: bool) -> None:
        if dpg.does_item_exist(self.win):
            dpg.configure_item(self.win, show=bool(on))

    def update(self, wm, model, now: float | None = None) -> None:
        """``wm`` is the WorldModel (battles), ``model`` the ViewerModel (live frames)."""
        now = time.monotonic() if now is None else now
        shown, overflow = stadium.strip(wm.stadium(now))
        dpg.set_value(self.title, f"Stadium - {len(shown) + overflow} in battle" if shown
                      else "Stadium - no battles")
        for i, slot in enumerate(self.slots):
            if i < len(shown):
                aid, card = shown[i]
                slot.show(aid, card, model.frame(aid), now)
            else:
                slot.hide()
        dpg.set_value(self.more, f"+{overflow} more battles not shown" if overflow else "")
