"""A game-agnostic gameplay view: one large game screen and one status line, for any registered agent.

Run from the repo root:  uv run python tools/watch_game.py [--agent ID] [--root .]

It knows only the viewer contract: the agent registry, frames with their own width and height, and the snapshot's
generic fields. Tab switches agent when more than one is running.
"""
import argparse
import sys
import threading
import time
from pathlib import Path

import dearpygui.dearpygui as dpg
import numpy as np

from pokeagent.agent_registry import list_agents
from pokeagent.viewer.sources import HttpShmSource

UPSCALE = 4
STATUS_H = 64
TEX = "gameplay_tex"
IMG = "gameplay_img"
LINE1 = "gameplay_line1"
LINE2 = "gameplay_line2"


def fit_size(view_w, view_h, w, h):
    """The largest size that fits the area and keeps the frame's aspect ratio."""
    scale = max(0.1, min(view_w / w, view_h / h))
    return int(w * scale), int(h * scale)


def status_lines(agent_id, snap):
    if snap is None:
        return f"{agent_id}: waiting for data", ""
    name = snap.segment.name or snap.segment.id or agent_id
    move = " | ".join(x for x in (snap.thinking.plan, snap.thinking.rule) if x)
    return name, " | ".join(x for x in (snap.screen.box_text, move) if x)


def to_texture(rgb, w, h):
    a = np.frombuffer(rgb, np.uint8).reshape(h, w, 3)
    a = a.repeat(UPSCALE, axis=0).repeat(UPSCALE, axis=1)
    out = np.ones((a.shape[0], a.shape[1], 4), np.float32)
    out[..., :3] = a / 255.0
    return out.ravel()


class Agents:
    """The registry, followed in the background so a slow agent never stalls the picture."""

    def __init__(self, root, wanted):
        self.root, self.wanted = Path(root), wanted
        self.sources = {}
        self.pids = {}
        self.snaps = {}
        self.index = 0
        self.lock = threading.Lock()
        threading.Thread(target=self.loop, daemon=True).start()

    def loop(self):
        while True:
            entries = [e for e in list_agents(self.root) if not self.wanted or str(e["id"]) == self.wanted]
            fresh = {}
            for e in entries:
                aid = str(e["id"])
                old = self.sources.get(aid)
                fresh[aid] = old if old is not None and self.pids.get(aid) == e.get("pid") else HttpShmSource(e)
                self.pids[aid] = e.get("pid")
            with self.lock:
                self.sources = fresh
            for aid, src in fresh.items():
                self.snaps[aid] = src.snapshot()
            time.sleep(0.5)

    def current(self):
        with self.lock:
            ids = sorted(self.sources)
            if not ids:
                return None, None, None
            aid = ids[self.index % len(ids)]
            return aid, self.sources[aid], self.snaps.get(aid)

    def next(self):
        self.index += 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", default="")
    ap.add_argument("--root", default=".")
    ap.add_argument("--shot", default="", help="write this window's own picture to a PNG after a few seconds, for checking")
    a = ap.parse_args()
    agents = Agents(a.root, a.agent)
    dpg.create_context()
    with dpg.handler_registry():
        dpg.add_key_press_handler(dpg.mvKey_Tab, callback=lambda: agents.next())
    registry = dpg.add_texture_registry()
    tex_size = None
    with dpg.window(tag="root", no_title_bar=True, no_move=True, no_resize=True, no_scrollbar=True):
        dpg.add_text("Waiting for an agent", tag=LINE1)
        dpg.add_text("", tag=LINE2)
    dpg.create_viewport(title="Gameplay", width=760, height=800)
    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.set_primary_window("root", True)
    start, shown, shot_done, last_log = time.time(), 0, False, 0
    while dpg.is_dearpygui_running():
        aid, src, snap = agents.current()
        fr = src.frame() if src is not None else None
        if aid is not None:
            one, two = status_lines(aid, snap)
            dpg.set_value(LINE1, one)
            dpg.set_value(LINE2, two)
        if fr is not None:
            rgb, w, h = fr
            if tex_size != (w, h):
                if dpg.does_item_exist(IMG):
                    dpg.delete_item(IMG)
                if dpg.does_item_exist(TEX):
                    dpg.delete_item(TEX)
                pixels = to_texture(rgb, w, h)
                dpg.add_raw_texture(w * UPSCALE, h * UPSCALE, pixels, format=dpg.mvFormat_Float_rgba, tag=TEX, parent=registry)
                dpg.add_image(TEX, tag=IMG, parent="root", before=LINE1)
                tex_size = (w, h)
            dpg.set_value(TEX, to_texture(rgb, w, h))
            vw, vh = fit_size(dpg.get_viewport_client_width() - 16, dpg.get_viewport_client_height() - STATUS_H, w, h)
            dpg.configure_item(IMG, width=vw, height=vh)
            shown += 1
        dpg.render_dearpygui_frame()
        if a.shot and not shot_done and time.time() - start > 6:
            dpg.output_frame_buffer(a.shot)
            shot_done = True
        if time.time() - last_log > 10:
            last_log = time.time()
            print(f"agent={aid} frames_shown={shown} size={tex_size}", flush=True)
    dpg.destroy_context()
    return 0


if __name__ == "__main__":
    sys.exit(main())
