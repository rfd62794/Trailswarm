"""One agent card: header + Render | Sees textures over Thinking/Progress text textures.

Every pixel the card shows comes from viewer.panels (pure functions); this module only owns
Dear PyGui items and texture bookkeeping. ``big=True`` lays the same card out for focus view.
"""
from __future__ import annotations

import hashlib
import time
from typing import Callable

import numpy as np

import dearpygui.dearpygui as dpg

from pokeagent.snapshot import AgentSnapshot
from pokeagent.viewer.health import OK
from pokeagent.viewer.panels import BG, DIM, PANE, TEXT, driver_color, plain, span
from pokeagent.viewer.panels import render as pres
from pokeagent.viewer.panels import registry
from pokeagent.viewer.panels.noframe import hint_texture
from pokeagent.viewer.panels.textimg import SEES_GRID, lines_texture
from pokeagent.viewer.ui import tags, theme

_PAD = 5
_HEADER_H = 15
_FOLLOW_H = 22  # the per-card Follow button strip (tiles only)
_FRAME_MIN_S = 1 / 20  # a card re-uploads a changed frame at most 20 times a second


class _Tex:
    """A named raw texture: created lazily, updated only when its pixels change."""

    def __init__(self, width: int, height: int) -> None:
        self.w, self.h = width, height
        self.tag: str | int | None = None
        self._key: tuple | None = None

    def _ensure(self, data: list[float], w: int, h: int) -> str | int:
        if self.tag is None or self.w != w or self.h != h:
            if self.tag is not None:
                dpg.delete_item(self.tag)
            self.tag = dpg.add_raw_texture(w, h, data, parent=tags.VIEWER_TEX)
            self.w, self.h, self._key = w, h, None
        return self.tag

    def set(self, data: list[float], w: int, h: int, key: tuple) -> str | int:
        """Upload ``data`` when ``key`` (content+size signature) differs from the last upload."""
        tag = self._ensure(data, w, h)
        if self._key != key:
            dpg.set_value(tag, data)
            self._key = key
        return tag

    def delete(self) -> None:
        if self.tag is not None:
            dpg.delete_item(self.tag)
            self.tag = None


def _frame_tex(rgb: bytes, w: int, h: int, pw: int, ph: int, dim: bool) -> tuple[list[float], int, int, tuple]:
    px = pres.frame_rgba(rgb, w, h, pw, ph)
    if dim:  # lost/stopped: darken the last frame instead of dropping it
        px = px * np.float32(0.4)
    key = (w, h, dim, hashlib.blake2b(rgb, digest_size=8).digest())
    return px, pw, ph, key


def _text_tex(lines, pw: int, ph: int, grid=None) -> tuple[list[float], int, int, tuple]:
    data, tw, th = lines_texture(lines, pw, ph, grid=grid)
    key = (tw, th, hashlib.md5(repr(lines).encode()).digest()[:8])
    return data, tw, th, key


def _hex_rgba(color: str) -> list[float]:
    c = color.lstrip("#")
    return [int(c[i:i + 2], 16) / 255.0 for i in (0, 2, 4)] + [1.0]


def _hstack(left: np.ndarray | None, lw: int, lh: int,
            right: np.ndarray, rw: int, rh: int, gap: int,
            fill: list[float]) -> tuple[np.ndarray, int, int]:
    """Render | Sees side by side in one texture (DPG groups cannot nest in cells)."""
    w, h = lw + gap + rw, lh
    out = np.empty((h, w, 4), dtype=np.float32)
    out[:] = np.asarray(fill, dtype=np.float32)
    if left is not None:
        out[:, :lw] = left.reshape(h, lw, 4)
    out[:, lw + gap:] = right.reshape(rh, rw, 4)
    return out.reshape(-1), w, h


class CardView:
    """Textures + item tags for one card. ``update`` is called every UI frame; it only
    re-uploads pixels when the snapshot/frame content actually changed."""

    def __init__(self, parent, agent_id: str, card_w: int, card_h: int, on_focus: Callable[[str], None],
                 on_select: Callable[[str], None], big: bool = False,
                 on_follow: Callable[[str], None] | None = None,
                 health_for: Callable[[str], object] | None = None) -> None:
        self.agent_id = agent_id
        self._on_follow = on_follow
        self.big = big
        self._on_focus, self._on_select = on_focus, on_select
        self._health_for = health_for  # aid -> Health | None (HealthStore lookups; no I/O)
        self._health_state = OK
        self._tip_text = None
        self.card_w, self.card_h = card_w, card_h
        self._sizes: dict[str, tuple[int, int]] = {}
        self._tex: dict[str, _Tex] = {}
        self._img: dict[str, str | int] = {}
        self._parent = parent  # items are leaves: no container can nest inside cells/child_windows
        self._last_click = 0.0
        self._sel: bool | None = None
        self._sees_cache: tuple = (None, None)
        self._top_at = 0.0
        self._memo: dict = {}  # panel -> input signature of what its texture shows now
        self._build()

    def _clicked(self) -> None:
        """Click = select; two clicks <0.4 s apart = focus (DPG item double-click handlers are flaky)."""
        now = time.monotonic()
        if now - self._last_click < 0.4:
            self._last_click = 0.0
            self._on_focus(self.agent_id)
        else:
            self._last_click = now
            self._on_select(self.agent_id)

    def set_selected(self, on: bool) -> None:
        """Highlight (full brightness + bright tint on the header) vs the dimmed rest of the grid."""
        if getattr(self, "_sel", None) == on:
            return
        self._sel = on
        tag = self._img.get("top")
        if tag is not None and dpg.does_item_exist(tag):
            dpg.configure_item(tag, tint_color=(255, 255, 255, 255) if on else (170, 170, 170, 255))
        self._apply_header_tint()

    def set_health(self, state: str, reason: str = "") -> None:
        """Health-state header tint + one-line reason tooltip; re-themes only when the value changes."""
        key = (state, reason)
        if self._memo.get("health") == key:
            return
        self._memo["health"] = key
        self._health_state = state
        self._apply_header_tint()
        if self._tip_text is not None and dpg.does_item_exist(self._tip_text):
            dpg.set_value(self._tip_text, reason)

    def _apply_header_tint(self) -> None:
        """The header image's tint: the health colour wins when not ok, else the selection tint."""
        tag = self._img.get("header")
        if tag is None or not dpg.does_item_exist(tag):
            return
        state = getattr(self, "_health_state", OK)
        if state != OK and state in theme.HEADER_COLOUR:
            tint = theme.HEADER_COLOUR[state]
        else:
            tint = (120, 220, 255, 255) if self._sel else theme.HEADER_COLOUR[OK]
        dpg.configure_item(tag, tint_color=tint)

    # -- layout -----------------------------------------------------------------
    def _geom(self) -> dict[str, tuple[int, int]]:
        "-> panel name -> (w, h) in display px."""
        w, h = self.card_w, self.card_h
        iw = w - 2 * _PAD
        pw = (iw - _PAD) // 2 if not self.big else iw * 2 // 5
        # two 10:9 frames wide -> frame height follows panel width
        fh = int(pw * 9 / 10)
        avail = h - 2 * _PAD - _HEADER_H - (_FOLLOW_H if self._on_follow else 0)
        top = min(fh, max(24, int(avail * 0.62)))
        text = max(16, avail - top - _PAD)
        g = {
            "header": (iw, _HEADER_H),
            "top": (iw, top),  # render | sees composited into one texture
            "thinking": (iw, int(text * 0.55)),
            "progress": (iw, text - int(text * 0.55) - 2),
        }
        self._split = (pw, iw - pw - _PAD)  # (render_w, sees_w) inside "top"
        if self.big:
            g["focus"] = (iw, max(30, h - _HEADER_H - top - int(text * 0.55) - text - 6 * _PAD))
        return g

    def _panel_lines(self, name: str, snap: AgentSnapshot | None, hold_s: float | None) -> list:
        if snap is None:
            return [plain("(waiting for snapshot)", DIM)]
        if name == "header":
            return self._header(snap)
        if name == "thinking":
            return registry.lines_for(name, snap, hold_s=hold_s)
        return registry.lines_for(name, snap)

    def _header(self, snap: AgentSnapshot) -> list:
        head = f"{snap.agent_id} · {snap.kind or '?'}"
        seg = f" · {snap.segment.id} {snap.segment.name}".rstrip() if snap.segment.id else ""
        st = f" · step {snap.step}"
        line = [span(head, driver_color(snap.thinking.driver or snap.kind)), span(seg + st, DIM)]
        if snap.state != "running":
            line.append(span(f"  [{snap.state}{': ' + snap.stop_reason if snap.stop_reason else ''}]", DIM))
        return [line]

    # -- build ------------------------------------------------------------------
    def _build(self) -> None:
        g = self._geom()
        self._sizes = dict(g)
        p = self._parent
        self._img["header"] = self._place("header", g["header"])
        tip = dpg.add_tooltip(self._img["header"])   # shows the health reason, set only on state change
        self._tip_text = dpg.add_text("", parent=tip, wrap=400)
        self._img["top"] = self._place("top", g["top"])
        self._img["thinking"] = self._place("thinking", g["thinking"])
        self._img["progress"] = self._place("progress", g["progress"])
        if self.big:
            self._img["focus"] = self._place("focus", g["focus"])
        if self._on_follow is not None:
            self._img["follow"] = dpg.add_button(label="Follow", parent=self._parent, width=60, height=_FOLLOW_H - 4,
                                                 callback=lambda s, a, u: self._on_follow(self.agent_id))

    def _place(self, name: str, size: tuple[int, int]):
        tex = self._tex.setdefault(name, _Tex(*size))
        if tex.tag is None:  # 1x1 placeholder until the first update uploads real pixels
            tex.tag = dpg.add_raw_texture(1, 1, [0.0] * 4, parent=tags.VIEWER_TEX)
        img = dpg.add_image_button(tex.tag, parent=self._parent, width=size[0], height=size[1],
                                   background_color=(0, 0, 0, 0),
                                   callback=lambda s, a, u: self._clicked())
        return img

    # -- update -----------------------------------------------------------------
    def update(self, snap: AgentSnapshot | None, frame, staleness: str, hold_s: float | None = None) -> None:
        health_for = getattr(self, "_health_for", None)  # absent on test stubs made with __new__
        if health_for is not None:           # dict lookups only; the store is fed off the render thread
            h = health_for(self.agent_id)
            if h is not None:
                self.set_health(h.state, h.reason)
        g = self._sizes
        dim = staleness != "live" or (snap is not None and snap.state in ("stopped", "done"))
        # top strip: render frame (left) | sees text (right) in one texture, at 2x
        rw_, sw_ = self._split
        _, th_ = g["top"]
        if min(rw_, sw_, th_) < 4:  # window not sized yet / degenerate card: nothing to draw
            return
        ss = 2  # textimg supersample; frame is rasterized to match
        sees_lines = registry.lines_for("sees", snap) if snap is not None else [plain("(waiting for snapshot)", DIM)]
        fkey = (frame[1], frame[2], hashlib.blake2b(frame[0], digest_size=8).digest()) if frame is not None else None
        top_key = ("top", fkey, dim, (rw_, sw_, th_), hashlib.md5(repr(sees_lines).encode()).digest()[:8])
        now = time.monotonic()
        prev = self._memo.get("top")
        if prev != top_key and not (prev is not None and prev[2:] == top_key[2:] and now - self._top_at < _FRAME_MIN_S):
            # rasterize only when frame/text/size changed; frame-only changes are capped at ~20 Hz
            self._memo["top"] = top_key
            self._top_at = now
            left = lkey = None
            if frame is not None:
                rgb, w, h = frame
                px, pw_, ph_, lkey = _frame_tex(rgb, w, h, rw_ * ss, th_ * ss, dim)
                if (pw_, ph_) == (rw_ * ss, th_ * ss):
                    left = px
                else:  # unexpected raster size: skip rather than misalign
                    lkey = None
            elif snap is not None:  # a snapshot but no frame: say why instead of a blank
                hpx, hw, hh = hint_texture(rw_, th_)
                if (hw, hh) == (rw_ * ss, th_ * ss):
                    left, lkey = hpx, ("no-frame", rw_, th_)
            skey = (sw_, th_, top_key[4])
            if self._sees_cache[0] != skey:  # the Sees text changes far less often than the frame
                self._sees_cache = (skey, _text_tex(sees_lines, sw_, th_, SEES_GRID))
            rpx, rtw, rth, rkey = self._sees_cache[1]
            data, tw2, th2 = _hstack(left, rw_ * ss, rth, rpx, rtw, rth, _PAD * ss, _hex_rgba(PANE))
            tag = self._tex["top"].set(data, tw2, th2, ("top", lkey, rkey))
            dpg.configure_item(self._img["top"], texture_tag=tag)
        # text panels
        for name in ("header", "thinking", "progress", "focus"):
            if name not in self._img:
                continue
            lines = self._panel_lines(name, snap, hold_s)
            pw, ph = g[name]
            mkey = (name, pw, ph, hashlib.md5(repr(lines).encode()).digest()[:8])
            if self._memo.get(name) == mkey:
                continue
            self._memo[name] = mkey
            data, tw, th, key = _text_tex(lines, pw, ph)
            tag = self._tex[name].set(data, tw, th, key)
            dpg.configure_item(self._img[name], texture_tag=tag)

    def delete(self) -> None:
        for tag in self._img.values():
            if dpg.does_item_exist(tag):
                dpg.delete_item(tag)
        self._img.clear()
        for tex in self._tex.values():
            tex.delete()
        self._tex.clear()

    def resize(self, card_w: int, card_h: int) -> None:
        if (card_w, card_h) != (self.card_w, self.card_h):
            self.card_w, self.card_h = card_w, card_h
            self.delete()
            self._memo.clear()
            self._sees_cache = (None, None)
            self._sel = None
            self._build()
