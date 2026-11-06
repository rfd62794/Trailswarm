"""Focus view: one enlarged card plus a 'back to all agents' button (always visible)."""
from __future__ import annotations

from typing import Callable

import dearpygui.dearpygui as dpg

from pokeagent.viewer.model import ViewerModel


class FocusView:
    def __init__(self, parent, model: ViewerModel, card_factory: Callable,
                 on_back: Callable[[], None], on_toggle: Callable[[str], None],
                 on_select: Callable[[str], None]) -> None:
        self.model, self._factory = model, card_factory
        self._on_back, self._on_toggle, self._on_select = on_back, on_toggle, on_select
        self.area = dpg.add_child_window(parent=parent, width=10, height=10, border=False,
                                         no_scrollbar=True, tag="focus_area")
        self.card = None
        self._aid: str | None = None
        self._sig: tuple | None = None
        self._back_btn = None

    def area_size(self) -> tuple[int, int]:
        if dpg.does_item_exist(self.area):
            w, h = dpg.get_item_rect_size(self.area)
            return int(w), int(h)
        return 10, 10

    def sync(self, agent_id: str | None) -> None:
        """Show ``agent_id`` big; ``None`` clears. Rebuilds only when id or size bucket changes."""
        if agent_id is None:
            if self.card is not None:
                self.card.delete()
                self.card = None
            self._aid, self._sig = None, None
            return
        w, h = self.area_size()
        sig = (agent_id, w // 24, h // 24)
        if sig == self._sig and self.card is not None:
            return
        self._sig = sig
        if self.card is not None:
            self.card.delete()
        self._aid = agent_id
        bar_h = 56  # back button + padding + the card's own item gaps
        if self._back_btn is not None and dpg.does_item_exist(self._back_btn):
            dpg.delete_item(self._back_btn)
        # button first (top of the area) so it can never be pushed out of view by the tall card
        self._back_btn = dpg.add_button(label="< All agents", parent=self.area,
                                        callback=lambda s, a, u: self._on_back(), width=110)
        cw, ch = max(120, w - 8), max(120, h - bar_h - 8)
        self.card = self._factory(self.area, agent_id, cw, ch,
                                  self._on_toggle, self._on_select, big=True)

    def update(self, hold_s_for) -> None:
        if self.card is None or self._aid is None:
            return
        snap = self.model.snapshot(self._aid)
        frame = self.model.frame(self._aid)
        self.card.update(snap, frame, self.model.staleness(self._aid), hold_s_for(self._aid))

    def delete(self) -> None:
        if self.card is not None:
            self.card.delete()
            self.card = None
        if self._back_btn is not None and dpg.does_item_exist(self._back_btn):
            dpg.delete_item(self._back_btn)
        if dpg.does_item_exist(self.area):
            dpg.delete_item(self.area)
