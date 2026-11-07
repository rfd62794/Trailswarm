"""The window's world-mode wiring (kept out of window.py): build, fit and per-frame tick of the world view."""
from __future__ import annotations

import dearpygui.dearpygui as dpg

from pokeagent.viewer.ui.world_side import WorldSide
from pokeagent.viewer.ui.world_view import WorldView
from pokeagent.world.export import load_for_view
from pokeagent.world.model import WorldModel


class WorldHost:
    def __init__(self, win, model: WorldModel | None = None) -> None:
        self.win, self.model = win, model or WorldModel()
        self.view: WorldView | None = None
        self.pending_follow: str | None = None   # a follow requested before the view was built

    def build(self) -> None:
        w = self.win
        self.view = WorldView(w._win, self.model, w.toggle_focus, w._on_select, load_for_view, WorldSide)
        self.view.side.bind(w.model, w.toggle_focus)
        if self.pending_follow is not None:
            self.follow(self.pending_follow)

    def follow(self, agent_id: str) -> None:
        if self.view is None:
            self.pending_follow = agent_id
        else:
            self.pending_follow = None
            self.view.follow_agent(agent_id)

    def fit(self, vw: int, avail: int) -> None:
        if self.view is not None:
            self.view.fit(vw, avail)

    def tick(self) -> None:
        if self.view is None:
            return
        showing = self.win.focus.view == "world"
        dpg.configure_item(self.view.area, show=showing)
        if showing:
            self.view.update()
