"""The Dear PyGui window: one canvas of every area, all ghosts replayed over it via one texture.

Reused by import, unchanged, from ``pokeagent.world``: ``Viewport``, ``Pyramid``/``to_gpu``,
``Follow``. Every ghost head, trail, death mark, avatar and the live agent is one RGBA array
from ``overlay.render`` uploaded as ONE raw texture per frame, so display cost stays flat as
ghosts grow. The control row, agent pane, input wiring and texture helpers are in controls.py.
"""
from __future__ import annotations

import time

import dearpygui.dearpygui as dpg
import numpy as np

from pokeagent.mapview import controls, overlay, playback
from pokeagent.mapview.best import best_index
from pokeagent.mapview.compose import agent_rows, compose_base  # noqa: F401  (re-exported)
from pokeagent.mapview.layout import LABEL_H, Layout, locate
from pokeagent.mapview.presets import resolve
from pokeagent.mapview.texcache import TexCache
from pokeagent.mapview.smooth import Smoother
from pokeagent.mapview.walk import LiveTracker
from pokeagent.world.follow import Follow
from pokeagent.world.pyramid import Pyramid
from pokeagent.world.view import Viewport

ROOT, TEX, CANVAS = controls.ROOT, controls.TEX, controls.CANVAS
MAX_TEX = 40                            # chunk cache size


class MapWindow:
    """Window state plus one frame of work. ``headless`` skips input, textures and draw writes."""

    def __init__(self, snapshot, headless: bool = False, fps: int = playback.FPS,
                 avatars=None) -> None:
        self.headless, self._avatars = headless, avatars
        self.clock, self.vp, self.follow = playback.Clock(), Viewport(1, 1), Follow()
        self.trails, self.marks, self.follow_best = True, True, False
        self.follow_live = self._follow_touched = False
        self.preset, self.preset_note = resolve(), ""
        self._live_pts, self._track, self._smooth = {}, None, Smoother()
        self.status, self.uploads, self.base_builds = "", 0, 0   # uploads/builds are test-visible
        self.base = self.pyr = self._snap = self._built_key = self._pending_tables = self._built_imgs = None
        self.tables = playback.tables((), (), fps)
        self.frame = playback.positions(self.tables, 0.0)
        self.layout, self.agent_rows, self.best = Layout({}, 0, 0), [], None
        self.overlay_img = np.zeros((1, 1, 4), np.uint8)
        self._tex = TexCache(lambda tag: dpg.delete_item(tag) if dpg.does_item_exist(tag) else None, MAX_TEX)
        self._overlay_key, self._overlay_tag, self._tex_uploads, self._fitted = None, None, 0, False
        self._used_stale, self._best_run = False, None
        self._down_at = self._last_mouse = self._follow_t = None
        self.adopt(snapshot)

    def adopt(self, snap) -> None:
        """Swap in the newest snapshot; recompose only on area/layout change; ghosts join at loop start."""
        if snap is self._snap:
            return
        self._snap = snap
        self.status = "" if snap.found else f"waiting for {snap.source}"
        self.preset = getattr(snap, "preset", None) or resolve()
        self.follow_live = self.preset.follow_default == "live"
        self.preset_note = "unknown preset" if self.preset.name.endswith("?") else ""
        if self._track is None or self._track.walk_frames != self.preset.walk_frames:
            self._track = LiveTracker(self.preset.walk_frames, hold=8)
        if self.follow_live and snap.live and not self.follow.active and not self._follow_touched:
            self._set_follow_best(True)                     # follow live is the preset default
        # Pixels and layout only: a ``seen``-only change redraws the label, not the base.
        key = (snap.layout, tuple((a.name, a.width, a.height, id(snap.images.get(a.name))) for a in snap.areas))
        imgs = tuple(snap.images.get(a.name) for a in snap.areas)   # held so the ids stay unique
        if key != self._built_key:
            self._built_key, self._built_imgs, self.layout = key, imgs, snap.layout
            self.base, self.base_builds = compose_base(snap), self.base_builds + 1
            self.pyr = Pyramid(self.base) if self.base is not None else None
            self._tex.retire()
            self.vp.world_w, self.vp.world_h = max(1, snap.layout.space_w), max(1, snap.layout.space_h)
            self.vp.cx = min(max(self.vp.cx, 0.0), float(self.vp.world_w))
            self.vp.cy = min(max(self.vp.cy, 0.0), float(self.vp.world_h))
            if not self._fitted and self.base is not None:
                self._fitted = True
                self.vp.fit()
        self._pending_tables = snap.tables
        if not self.tables.ghosts:
            self._use_pending()

    def _use_pending(self) -> None:
        if self._pending_tables is None: return
        self.tables, self._pending_tables = self._pending_tables, None
        self.clock.duration = float(self.tables.durations.max()) if len(self.tables.durations) else 0.0
        self.agent_rows = agent_rows(self.tables)
        if not self.headless:
            controls.fill_agent_table(self)

    def build(self, parent=None) -> None:
        if not dpg.does_item_exist(TEX): dpg.add_texture_registry(tag=TEX, show=False)
        controls.build_body(self, parent)
        if self.headless: return
        controls.wire_input(self)
        controls.fill_agent_table(self)

    def _toggle_pause(self) -> None: self.clock.paused = not self.clock.paused

    def _set_follow_best(self, on: bool) -> None:
        self.follow_best, self._best_run, self._follow_touched = on, None, True
        if not on: self.follow.stop()
        if not self.headless and dpg.does_item_exist(controls.FOLLOW_CB):
            dpg.set_value(controls.FOLLOW_CB, on)

    def _user_panned(self) -> None:
        """A manual pan wins: follow goes off (and the checkbox with it), the camera stays put."""
        self.follow.stop()
        if self.follow_best:
            self._set_follow_best(False)

    def _follow_agent(self, agent: str) -> None:
        gs = [g for g in self.tables.ghosts if g.agent == agent]
        if (b := best_index(gs, self.tables.area_names)) is not None:
            self._set_follow_best(False)
            self.follow.start(gs[b].run, time.monotonic())
            if (p := self._points().get(gs[b].run)) is not None:
                self.vp.center_on(*p)

    def resize(self, w: int, h: int) -> None:
        if not dpg.does_item_exist(CANVAS): return
        dpg.configure_item(CANVAS, width=max(100, w - 250), height=max(100, h - 60))
        self.vp.resize(max(100, w - 250), max(100, h - 60))

    def _mouse(self):
        if not dpg.does_item_exist(CANVAS) or not dpg.is_item_hovered(CANVAS):
            return None
        mx, my = dpg.get_mouse_pos(local=False)
        ox, oy = dpg.get_item_rect_min(CANVAS)
        return mx - ox, my - oy

    def _wheel(self, delta) -> None:
        if (m := self._mouse()) is not None:
            self.vp.step_zoom_at(m[0], m[1], 1 if float(delta) > 0 else -1)

    def _press(self) -> None: self._down_at = self._mouse()

    def _release(self) -> None: self._down_at = self._last_mouse = None

    def _drag(self) -> None:
        m = self._mouse()
        down = m is not None and self._down_at is not None and dpg.is_mouse_button_down(dpg.mvMouseButton_Left)
        if down and self._last_mouse is not None:
            d = (m[0] - self._last_mouse[0], m[1] - self._last_mouse[1])
            if d[0] or d[1]:
                self.vp.pan(*d)
                self._user_panned()
        self._last_mouse = m if down else None

    def tick(self, dt: float, now: float | None = None) -> playback.Frame:
        """One frame of replay: advance the shared clock, follow, rasterise the one overlay."""
        now = time.monotonic() if now is None else now
        if self.clock.advance(dt) or not self.tables.ghosts:
            self._use_pending()
        self.frame = playback.positions(self.tables, self.clock.t)
        self.best = best_index(self.tables.ghosts, self.tables.area_names)
        self._live_pts = self._smooth.step(self._live_points(), dt)
        self._follow_tick(now, dt)
        self.overlay_img = overlay.render(self.frame, self.tables, self.layout, self.vp.visible(),
                                          self.vp.zoom, trails=self.trails,
                                          show_marks=self.marks, best=self.best,
                                          avatars=self._avatars, live=self._live_draw(),
                                          avatar_size=self.preset.avatar_size,
                                          walk_frames=self.preset.walk_frames)
        self.uploads += 1
        if not self.headless:
            self._upload_overlay()
            self._draw()
        return self.frame

    def _points(self) -> dict[str, tuple[float, float]]:
        pts = {}
        for k, g in enumerate(self.tables.ghosts):
            a = int(self.frame.area[k])
            if 0 <= a < len(self.tables.area_names):
                off = self.layout.offsets.get(self.tables.area_names[a])
                if off is not None:
                    pts[g.run] = (off[0] + float(self.frame.xs[k]), off[1] + float(self.frame.ys[k]))
        return pts

    def _live_points(self) -> dict[str, tuple[float, float]]:
        """Space positions of the live agents via the layout (unknown areas are skipped)."""
        snap = self._snap
        out = {}
        if snap is not None:
            for agent, pos in snap.live.items():
                if (p := locate(self.layout, pos.area, pos.x, pos.y)) is not None:
                    out[agent] = p
        return out

    def _live_draw(self) -> list:
        """(agent, x, y, facing, phase) per live agent, tracked across reads by the tracker."""
        out = []
        for agent, p in self._live_pts.items():
            pos = self._snap.live[agent]
            f, ph = self._track.update(agent, pos.area, pos.x, pos.y)
            out.append((agent, p[0], p[1], f, ph))
        return out

    def _follow_tick(self, now: float, dt: float) -> None:
        if self.follow_best:
            if self.follow_live and self._live_pts:
                agent = min(self._live_pts)
                if self.follow.agent_id != agent:
                    self.follow.start(agent, now)
            elif self.best is not None:
                run = self.tables.runs[self.best]
                if run != self._best_run:             # re-target only when the best run changes
                    self._best_run = run
                    self.follow.start(run, now)
        target = self.follow.target({**self._points(), **self._live_pts}, now)
        if target is not None:
            self.follow.step(self.vp, target, 0.0 if self._follow_t is None else now - self._follow_t)
        self._follow_t = now

    def _status_line(self) -> str:
        """preset.status_fields read off the host-supplied snapshot, else nothing."""
        obj = getattr(self._snap, "agent_status", None)
        parts = []
        if obj is not None:
            for name in self.preset.status_fields:
                v = obj
                for bit in name.split("."):
                    v = getattr(v, bit, None)
                    if v is None:
                        break
                if v is not None and v != "":
                    parts.append(str(getattr(v, "name", v)))
        return "  ".join(parts)

    def _upload_overlay(self) -> None:
        h, w = self.overlay_img.shape[:2]
        if self._overlay_key != (w, h):
            if self._overlay_tag is not None:
                dpg.delete_item(self._overlay_tag)
            self._overlay_key = (w, h)
            # A new id per size: Dear PyGui keeps a deleted item's alias, so reusing a string tag raises.
            self._overlay_tag = dpg.add_raw_texture(w, h, np.zeros(w * h * 4, np.float32),
                                                    format=dpg.mvFormat_Float_rgba, parent=TEX)
        dpg.set_value(self._overlay_tag, self.overlay_img.astype(np.float32).ravel() / 255.0)

    def _draw(self) -> None:
        if not dpg.does_item_exist(CANVAS): return
        self._drag()
        dpg.delete_item(CANVAS, children_only=True)
        if self.pyr is None:
            dpg.draw_text((20, 20), self.status or "no areas yet", size=18, parent=CANVAS)
            self._tex.sweep()
            return
        vp, self._tex_uploads, self._used_stale = self.vp, 0, False
        f, chunks = self.pyr.plan(vp.zoom, vp.visible(), MAX_TEX - 10)
        for cx, cy in chunks:
            if (tex := controls.chunk_tex(self, f, cx, cy)) is not None:
                x0, y0, x1, y1 = self.pyr.chunk_rect(f, cx, cy)
                dpg.draw_image(tex, vp.to_screen(x0, y0), vp.to_screen(x1, y1), parent=CANVAS)
            else:
                controls.draw_coarser(self, f, cx, cy)
        dpg.draw_image(self._overlay_tag, (0, 0), self.overlay_img.shape[:2][::-1], parent=CANVAS)
        seen = {a.name: a.seen for a in self._snap.areas}
        for name, (ax, ay) in self.layout.offsets.items():
            dpg.draw_text(vp.to_screen(ax, ay - LABEL_H + 2), f"{name} {seen.get(name, 0.0):.0%}",
                          size=14, parent=CANVAS)
        y = 8
        if self.preset_note:
            dpg.draw_text((12, y), self.preset_note, size=14, parent=CANVAS)
            y += 14
        if s := self._status_line():
            dpg.draw_text((12, y), s, size=14, parent=CANVAS)
            y += 14
        if self.follow.active:
            dpg.draw_text((12, y), f"following {self.follow.agent_id}", size=14, parent=CANVAS)
        if not self._used_stale:
            self._tex.sweep()        # nothing drawn this frame references the old textures
