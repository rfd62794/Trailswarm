"""The window's stitched-World wiring (kept out of window.py), mirroring WorldHost.

Owns the MapWindow embedded in World mode, the right-hand side column, and the ONE Selection
that drives the map camera, the gameplay panel and the agent list. The area shows only while
``focus.view == "world"`` and the launch's renderer is "stitched".
"""
from __future__ import annotations

import time

import dearpygui.dearpygui as dpg

from pokeagent.mapview.view import MapWindow
from pokeagent.viewer import selection as selmod
from pokeagent.viewer import ui_scale
from pokeagent.viewer.ui.stitched_side import StitchedSide

AREA_TAG = "stitched_area"
SIDE_FRAC, SIDE_MIN = 0.28, 280          # right column: ~28% of the window, at least 280 px


class StitchedHost:
    def __init__(self, win, stitched) -> None:
        self.win, self.stitched = win, stitched     # stitched: a StitchedSource
        self.sel = selmod.Selection()
        self.view: MapWindow | None = None
        self.side: StitchedSide | None = None
        self.area = self._left = self._right = None
        self.pending_follow: str | None = None
        self._last = time.monotonic()

    # -- the one selection -------------------------------------------------------
    def pick(self, agent: str, kind: str) -> None:
        """Map click or list row: a user selection (re-enables Follow selected)."""
        self.sel.select(agent, kind)
        self.win.selected = agent
        if self.view is not None:
            self.view._set_follow_best(True)
        self._push()

    def auto(self) -> None:
        """The "Auto" button: back to the featured live agent for camera AND gameplay panel."""
        self.sel.auto()
        if self.view is not None:
            self.sel.update(self.view._snap.live, self.win.model.ids())
            self.view._set_follow_best(True)
        self.win.selected = self.sel.agent
        self._push()

    def follow(self, agent_id: str) -> None:
        """WorldHost parity: a card Follow or mode-switch. Only a different agent becomes a
        user pick; re-entering World with the auto selection keeps it auto."""
        if agent_id is not None and agent_id != self.sel.agent:
            self.pick(agent_id, "live")
        elif self.view is not None:
            self.view._set_follow_best(True)

    def following(self) -> str | None:
        return self.sel.agent if (self.view is not None and self.view.follow_best) else None

    def _push(self) -> None:
        if self.view is not None:
            self.view.set_selected(self.sel.agent, "live" if self.sel.is_live else "ghost")

    # -- build / fit / tick --------------------------------------------------------
    def build(self, headless: bool = False) -> None:
        self.area = dpg.add_child_window(parent=self.win._win, width=10, height=10, border=False,
                                         no_scrollbar=True, tag=AREA_TAG, show=False)
        with dpg.group(horizontal=True, parent=self.area):
            self._left = dpg.add_group()
            self._right = dpg.add_child_window(width=10, border=False)
        self.view = MapWindow(self.stitched.snapshot(), headless=headless,
                              avatars=self.stitched.avatars, on_pick=self.pick)
        self.view.build(parent=self._left)
        self.side = StitchedSide(self, parent=self._right)

    def fit(self, vw: int, avail: int) -> None:
        if self.area is None:
            return
        side = max(ui_scale.px(SIDE_MIN), int(vw * SIDE_FRAC))
        dpg.configure_item(self.area, width=vw - 8, height=avail)
        dpg.configure_item(self._right, width=side, height=avail - 8)
        self.view.resize(vw - side - 32, avail - 8)
        self.side.fit(side, avail)

    def tick(self) -> None:
        if self.view is None:
            return
        showing = self.win.focus.view == "world"
        dpg.configure_item(self.area, show=showing)
        if not showing:
            return
        now = time.monotonic()
        dt, self._last = now - self._last, now
        self.view.adopt(self.stitched.snapshot())
        self.sel.update(self.view._snap.live, self.win.model.ids())
        self.win.selected = self.sel.agent
        self._push()
        self.view.tick(dt, now)
        self.side.update()
