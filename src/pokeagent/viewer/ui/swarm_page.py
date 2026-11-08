"""Swarm page: one row per agent/slot as a real top-level window (movable/resizable, persisted by init_file).

Same shape as the Stadium pane: a View-menu checkbox toggles it, the title-bar X hides it for the
run, a click on a row focuses that agent. Rows are pre-assembled dicts from ``viewer.swarm_rows``
(built on the poll thread); this module only owns Dear PyGui items.
"""
from __future__ import annotations

import dearpygui.dearpygui as dpg

from pokeagent.viewer.swarm_rows import ROW_KEYS
from pokeagent.viewer.ui import tags, theme
from pokeagent.viewer.ui_scale import px

PANE_W, PANE_H = 900, 320      # untuned first values: default page size in 1x px
COLUMNS = ("Agent", "State", "Segment", "Grade", "Next", "Steps/s", "RSS", "Health", "Last goal")


class SwarmPage:
    """The top-level ``SWARM_PAGE`` window: a table of swarm rows plus the count line."""

    def __init__(self, on_focus, on_close=None) -> None:
        self._on_focus = on_focus
        kw = {} if on_close is None else {"on_close": lambda *_a: on_close()}
        self.win = dpg.add_window(tag=tags.SWARM_PAGE, label="Swarm",
                                  width=px(PANE_W), height=px(PANE_H), show=False, **kw)
        with dpg.group(parent=self.win):
            self.title = dpg.add_text("Swarm")
            self.table = dpg.add_table(header_row=True, resizable=True, row_background=True,
                                       borders_innerH=True, borders_outerH=True)
        self._sig = None
        self.row_items: list = []      # the first cell of each row (a clickable selectable)

    def set_visible(self, on: bool) -> None:
        if dpg.does_item_exist(self.win):
            dpg.configure_item(self.win, show=bool(on))

    def update(self, rows: list[dict]) -> None:
        """Re-render rows from ``swarm_rows.build_rows`` output; a no-op when nothing changed."""
        dpg.set_value(self.title, f"Swarm - {len(rows)} agent{'s' if len(rows) != 1 else ''}")
        sig = tuple(tuple(str(r.get(k, "")) for k in ROW_KEYS) for r in rows)
        if sig == self._sig:
            return
        self._sig = sig
        dpg.delete_item(self.table, children_only=True)
        self.row_items = []
        for label in COLUMNS:
            dpg.add_table_column(parent=self.table, label=label)
        for r in rows:
            row = dpg.add_table_row(parent=self.table)
            aid = str(r.get("id", ""))
            self.row_items.append(dpg.add_selectable(
                label=aid, parent=row, span_columns=True,
                callback=lambda s, a, u, aid=aid: self._on_focus(aid)))
            cells = (r.get("state", ""), r.get("segment", ""), r.get("grade", ""), r.get("next", ""),
                     r.get("steps_s", ""), r.get("rss", ""), r.get("health", ""), r.get("goal", ""))
            for j, val in enumerate(cells):
                item = dpg.add_text(str(val), parent=row)
                if j == 6:  # the Health column carries the badge colour; its reason is the tooltip
                    t = theme.health_theme(str(val))
                    if t is not None:
                        dpg.bind_item_theme(item, t)
                    if r.get("reason"):
                        tip = dpg.add_tooltip(item)
                        dpg.add_text(str(r["reason"]), parent=tip, wrap=px(340))
