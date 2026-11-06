"""Multi-view: the card grid inside the grid area, rebuilt only on agent-set or size change."""
from __future__ import annotations

import time
from typing import Callable

import dearpygui.dearpygui as dpg

from pokeagent.viewer.layout import grid
from pokeagent.viewer.model import ViewerModel
from pokeagent.viewer.view_cap import page_ids, view_max


UPDATE_BUDGET_S = 0.022  # per UI tick; the rest of the cards are refreshed on the following ticks


class GridView:
    def __init__(self, parent, model: ViewerModel, card_factory: Callable,
                 on_focus: Callable[[str], None], on_select: Callable[[str], None]) -> None:
        self.model, self._factory = model, card_factory
        self._on_focus, self._on_select = on_focus, on_select
        self.area = dpg.add_child_window(parent=parent, width=10, height=10, border=False,
                                         no_scrollbar=True, tag="grid_area")
        self.cards: dict[str, object] = {}
        self._sig: tuple | None = None
        self._rr = 0
        self.view_max, self.page = view_max(), 0

    def _ranked(self) -> list[str]:
        """Live agents first, then stale, then lost; stable by id so the grid does not reshuffle."""
        order = {"live": 0, "stale": 1, "lost": 2}
        return sorted(self.model.ids(), key=lambda a: (order.get(self.model.staleness(a), 3), a))

    def next_page(self, *_a) -> None:
        self.page += 1

    def area_size(self) -> tuple[int, int]:
        if dpg.does_item_exist(self.area):
            w, h = dpg.get_item_rect_size(self.area)
            return int(w), int(h)
        return 10, 10

    def sync(self) -> None:
        """Create/resync cards for the current agent set and area size (cheap no-op otherwise)."""
        all_ids = self._ranked()
        ids, more, self.page = page_ids(all_ids, self.view_max, self.page)
        w, h = self.area_size()
        sig = (tuple(ids), more, w // 20, h // 20)
        if sig == self._sig:
            return
        self._sig = sig
        for card in self.cards.values():
            card.delete()
        self.cards.clear()
        if dpg.does_item_exist("grid_more"):
            dpg.delete_item("grid_more")
        if not ids:
            return
        cols, rows, cw, ch = grid(len(ids), w - 8, h - 8)
        if dpg.does_item_exist("grid_table"):  # a rebuild (agent set / resize) must drop the old table first
            dpg.delete_item("grid_table")
        table = dpg.add_table(parent=self.area, header_row=False, tag="grid_table",
                              resizable=False, reorderable=False, sortable=False,
                              hideable=False, scrollX=False, scrollY=False)
        for _ in range(cols):
            dpg.add_table_column(parent=table, width_fixed=True, init_width_or_weight=float(cw))
        for r in range(rows):
            row = dpg.add_table_row(parent=table, height=ch)
            for c in range(cols):
                aid = ids[r * cols + c] if r * cols + c < len(ids) else None
                if aid is None:
                    dpg.add_table_cell(parent=row)
                    continue
                cell = dpg.add_table_cell(parent=row)
                self.cards[aid] = self._factory(cell, aid, cw, ch,
                                                 self._on_focus, self._on_select)
        if more:  # agents beyond the card limit: a button that cycles through them
            dpg.add_button(parent=self.area, tag="grid_more", callback=self.next_page,
                           label=f"+{more} more (page {self.page + 1}/{-(-len(all_ids) // self.view_max)})")

    def update(self, hold_s_for) -> None:
        """Refresh cards round-robin within a time budget so many agents keep the UI frame rate up;
        a card skipped this tick is first in line next tick (cards only redraw changed content)."""
        ids = list(self.cards)
        if not ids:
            return
        start, t0 = self._rr % len(ids), time.monotonic()
        for k in range(len(ids)):
            aid = ids[(start + k) % len(ids)]
            self.cards[aid].update(self.model.snapshot(aid), self.model.frame(aid),
                                   self.model.staleness(aid), hold_s_for(aid))
            if time.monotonic() - t0 > UPDATE_BUDGET_S:
                self._rr = start + k + 1
                return
        self._rr = start + 1

    def delete(self) -> None:
        for card in self.cards.values():
            card.delete()
        self.cards.clear()
        if dpg.does_item_exist(self.area):
            dpg.delete_item(self.area)
