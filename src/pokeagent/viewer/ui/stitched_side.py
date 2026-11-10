"""Stitched World mode's right column: the focus panel on top, the agent list below.

The focus panel shows the selected gameplay agent's current frame (``card.py``'s frame helper,
aspect-kept, integer upscale when it fits), the status line, the ``gameplay_agent`` notice and
the preset's ``status_fields``. The list has one row per live registry agent, then one per
ghost-only name ("recorded"); a click selects, "Auto" returns to featured. Rows rebuild only
when the set changes, not per frame.
"""
from __future__ import annotations

import hashlib

import dearpygui.dearpygui as dpg

from pokeagent.mapview import compose, overlay
from pokeagent.viewer import modes
from pokeagent.viewer import selection as selmod
from pokeagent.viewer import ui_scale
from pokeagent.viewer.model import CARD_FRAME_HZ
from pokeagent.viewer.panels.noframe import hint_texture
from pokeagent.viewer.ui import tags
from pokeagent.viewer.ui.card import _Tex, _frame_tex

WANT_TTL_S = 1.0            # frame demand re-declared every tick; dies a second after hiding
FRAME_ASPECT = 0.9          # the gameplay frame box is a little shorter than wide (10:9 frames)


class StitchedSide:
    def __init__(self, host, parent) -> None:
        self.host = host                       # StitchedHost: .sel .view .stitched .win
        self.width = ui_scale.px(280)
        if not dpg.does_item_exist(tags.VIEWER_TEX):
            dpg.add_texture_registry(tag=tags.VIEWER_TEX, show=False)
        self._tex = _Tex(1, 1)
        self._rows_sig = None
        with dpg.group(parent=parent):
            self._img = dpg.add_image(self._tex.set([0.0] * 4, 1, 1, ("blank",)))
            self.notice = dpg.add_text("", wrap=self.width)
            self.status = dpg.add_text("", wrap=self.width)
            self.fields = dpg.add_text("", wrap=self.width)
            dpg.add_separator()
            with dpg.group(horizontal=True):
                dpg.add_button(label="Auto", callback=lambda *_: self.host.auto())
                dpg.add_text("agents", color=(140, 140, 140))
            self.list = dpg.add_child_window(height=-1, border=True)

    def fit(self, w: int, h: int) -> None:
        self.width = w
        for t in (self.notice, self.status, self.fields):
            dpg.configure_item(t, wrap=w - ui_scale.px(12))

    # -- per tick ------------------------------------------------------------------
    def update(self) -> None:
        host, model = self.host, self.host.win.model
        snap = host.view._snap if host.view is not None else host.stitched.snapshot()
        ids = model.ids()
        feat = selmod.featured(snap.live, ids)
        agent, notice = selmod.gameplay_agent(host.sel, ids, feat)
        if agent is not None:                  # the gameplay panel's agent keeps its frames coming
            model.want_frames({agent: CARD_FRAME_HZ}, WANT_TTL_S)
        self._frame(agent)
        dpg.set_value(self.status, modes.status_text("world", len(ids), host.sel.agent, host.following()))
        dpg.set_value(self.notice, notice)
        dpg.set_value(self.fields, self._fields(agent))
        self._list(snap, ids, model)

    def _frame(self, agent: str | None) -> None:
        bw = max(16, self.width - ui_scale.px(16))
        bh = max(16, int(bw * FRAME_ASPECT))
        frame = self.host.win.model.frame(agent) if agent else None
        if frame is None:
            px, tw, th = hint_texture(bw, bh)
            key = ("hint", tw, th)
            data = list(px)
        else:
            rgb, w, h = frame
            tw, th = self._box(w, h, bw, bh)
            data, tw, th, key = _frame_tex(rgb, w, h, tw, th, dim=False)
        tag = self._tex.set(list(data), tw, th, ("frame", key))
        dpg.configure_item(self._img, texture_tag=tag, width=tw, height=th)

    @staticmethod
    def _box(w: int, h: int, bw: int, bh: int) -> tuple[int, int]:
        """Aspect-kept fit inside the panel box; integer upscale when the frame is smaller."""
        k = min(bw // w, bh // h)
        if k >= 1:
            return w * k, h * k
        s = min(bw / w, bh / h)
        return max(1, int(w * s)), max(1, int(h * s))

    def _fields(self, agent: str | None) -> str:
        """The preset's status_fields read off that agent's viewer snapshot (like _status_line)."""
        s = self.host.win.model.snapshot(agent) if agent else None
        if s is None:
            return ""
        parts = []
        for name in self.host.stitched.preset.status_fields:
            v = s
            for bit in name.split("."):
                v = getattr(v, bit, None)
                if v is None:
                    break
            if v is not None and v != "":
                parts.append(str(getattr(v, "name", v)))
        return "  ".join(parts)

    # -- the agent list ---------------------------------------------------------------
    def _list(self, snap, ids, model) -> None:
        rows = [(a, overlay.color_index(a, len(overlay.PALETTE)), self._state(model, a), "")
                for a in ids]
        rows += [(a, c, f"x{n}  {far}", "recorded")
                 for a, c, n, far in compose.agent_rows(snap.tables) if a not in ids]
        sig = (tuple(rows), self.host.sel.agent)
        if sig == self._rows_sig:
            return
        self._rows_sig = sig
        dpg.delete_item(self.list, children_only=True)
        for i, (agent, cidx, detail, tag) in enumerate(rows):
            kind = "live" if i < len(ids) else "ghost"
            with dpg.group(horizontal=True, parent=self.list):
                sw = dpg.add_drawlist(width=12, height=12)
                dpg.draw_rectangle((0, 0), (12, 12), parent=sw,
                                   fill=(*[int(v) for v in overlay.PALETTE[cidx]], 255))
                label = f"{agent}  {detail}".rstrip() + (f"  [{tag}]" if tag else "")
                dpg.add_selectable(label=label, default_value=agent == self.host.sel.agent,
                                   callback=lambda _s, _a, _u, a=agent, k=kind: self.host.pick(a, k))

    @staticmethod
    def _state(model, agent: str) -> str:
        s = model.snapshot(agent)
        return s.state if s is not None else model.staleness(agent)
