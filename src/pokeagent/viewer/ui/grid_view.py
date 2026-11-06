"""Multi-view: the card grid inside the grid area, rebuilt only on agent-set or size change."""
from __future__ import annotations

from typing import Callable

import dearpygui.dearpygui as dpg

from pokeagent.viewer.layout import grid
from pokeagent.viewer.model import ViewerModel


class GridView:
    def __init__(self, parent, model: ViewerModel, card_factory: Callable,
                 on_focus: Callable[[str], None], on_select: Callable[[str], None]) -> None:
        self.model, self._factory = model, card_factory
        self._on_focus, self._on_select = on_focus, on_select
        self.area = dpg.add_child_window(parent=parent, width=10, height=10, border=False,
                                         no_scrollbar=True, tag="grid_area")
        self.cards: dict[str, object] = {}
        self._sig: tuple | None = None

    def area_size(self) -> tuple[int, int]:
        if dpg.does_item_exist(self.area):
            w, h = dpg.get_item_rect_size(self.area)
            return int(w), int(h)
        return 10, 10

    def sync(self) -> None:
        """Create/resync cards for the current agent set and area size (cheap no-op otherwise)."""
        ids = self.model.ids()
        w, h = self.area_size()
        sig = (tuple(ids), w // 20, h // 20)
        if sig == self._sig:
            return
        self._sig = sig
        for card in self.cards.values():
            card.delete()
        self.cards.clear()
        if not ids:
            return
        cols, rows, cw, ch = grid(len(ids), w - 8, h - 8)
        table = dpg.add_table(parent=self.area, header_row=False, tag="grid_table",
                              resizable=False, reorderable=False, sortable=False,
                              hideable=False, scrollX=False, scrollY=False,
                              no_host_extendX=True, no_host_extendY=True)
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

    def update(self, hold_s_for) -> None:
        for aid, card in self.cards.items():
            snap = self.model.snapshot(aid)
            frame = self.model.frame(aid)
            card.update(snap, frame, self.model.staleness(aid), hold_s_for(aid))

    def delete(self) -> None:
        for card in self.cards.values():
            card.delete()
        self.cards.clear()
        if dpg.does_item_exist(self.area):
            dpg.delete_item(self.area)
