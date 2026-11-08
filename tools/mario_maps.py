"""Builds per-level maps and ghost tracks by replaying the input sequences workers drop in the inbox.

Output under runs/mario-land/:
    maps/level_<world>-<level>.png and maps/index.json   stitched levels and how much of each has been seen
    ghosts/<run>.json                                    one attempt as positions over time

The ghost format holds no game terms, so any game can write it:
    {"schema": 1, "game": ..., "run": ..., "agent": ..., "outcome": ..., "every": frames_per_point,
     "points": [[area, x, y], ...]}
"""
import glob
import json
import os
import time
from pathlib import Path

import numpy as np
from PIL import Image

from mario_moments import MomentBook, classify

DIR = Path("runs") / "mario-land"
INBOX = DIR / "inbox"
MAPS = DIR / "maps"
GHOSTS = DIR / "ghosts"
HUD = 16
SPRITE_Y = 16                # the game's sprite y is 16 pixels below the screen's top edge
HEIGHT = 144 - HUD
MAX_SAMPLES = 15
SETTLE_FRAMES = 60           # a new level reports stale progress briefly, so its first frames are ignored
SAMPLE_EVERY = 3
POINT_EVERY = 2
KEEP_GHOSTS = 60
BACKLOG = 20
SAVE_EVERY_S = 20
ADDR_MARIO_X, ADDR_MARIO_Y = 0xC202, 0xC201


def write_atomic(path, write):
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp{path.suffix}")
    write(tmp)
    for _ in range(40):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.05)
    tmp.unlink(missing_ok=True)


def area_name(world):
    return f"{world[0]}-{world[1]}"


def update_columns(columns, cam, frame):
    for sx in range(frame.shape[1]):
        samples = columns.setdefault(cam + sx, [])
        if len(samples) < MAX_SAMPLES:
            samples.append(frame[:, sx].copy())


def render_map(columns):
    width = max(columns) + 1
    img = np.full((HEIGHT, width), 255, np.uint8)
    for x, samples in columns.items():
        img[:, x] = np.median(np.stack(samples), axis=0).astype(np.uint8)
    return img, len(columns) / width


class Cartographer:
    def __init__(self, macros):
        from pyboy import PyBoy
        self.macros = macros
        self.py = PyBoy(glob.glob("roms/Super Mario Land*.gb")[0], window="null")
        self.py.set_emulation_speed(0)
        self.w = self.py.game_wrapper
        self.w.game_area_mapping(self.w.mapping_minimal, 0)
        self.w.start_game()
        self.boot = self.snapshot()
        self.book = MomentBook()
        self.levels = {}
        self.ghost_count = 0

    def snapshot(self):
        import io
        f = io.BytesIO()
        self.py.save_state(f)
        return f.getvalue()

    def replay(self, doc):
        import io
        self.py.load_state(io.BytesIO(self.boot))
        lives, world, settle, frame, points = self.w.lives_left, self.w.world, 0, 0, []
        score, coins, timer, move, events = self.w.score, self.w.coins, self.w.time_left, 0, []

        def tick(n):
            nonlocal world, settle, frame, score, coins, timer
            for _ in range(n):
                self.py.tick(1, frame % SAMPLE_EVERY == 0)
                frame += 1
                gained, coins_rose, timer_dropped = self.w.score - score, self.w.coins > coins, self.w.time_left < timer
                score, coins, timer = self.w.score, self.w.coins, self.w.time_left
                if gained > 0 and not settle:
                    kind = classify(gained, coins_rose, timer_dropped, self.w.game_area())
                    events.append({"frame": frame, "move": move, "area": area_name(world), "x": self.w.level_progress,
                                   "y": int(self.py.memory[ADDR_MARIO_Y]) - SPRITE_Y - HUD, "kind": kind, "points": gained})
                if self.w.world != world:
                    world, settle = self.w.world, SETTLE_FRAMES
                if settle:
                    settle -= 1
                    continue
                x, y = self.w.level_progress, int(self.py.memory[ADDR_MARIO_Y])
                if frame % POINT_EVERY == 0:
                    points.append([area_name(world), x, y - SPRITE_Y - HUD])
                cam = x - self.py.memory[ADDR_MARIO_X]
                if frame % SAMPLE_EVERY == 1 and cam >= 0:
                    a = np.asarray(self.py.screen.image.convert("L"))[HUD:]
                    update_columns(self.levels.setdefault(area_name(world), {}), cam, a)

        for move, m in enumerate(doc["seq"]):
            _, buttons, frames = self.macros[m]
            for b in buttons:
                self.py.button_press(b)
            tick(frames)
            for b in buttons:
                self.py.button_release(b)
            tick(1)
            if self.w.lives_left < lives:
                break
        self.book.add(events, doc)
        return points

    def write_ghost(self, doc, points):
        self.ghost_count += 1
        run = f"{int(doc['at'] * 1000)}-{doc['worker']}"
        ghost = {"schema": 1, "game": "mario-land", "run": run, "agent": f"worker-{doc['worker']}",
                 "outcome": doc["outcome"], "every": POINT_EVERY, "points": points}
        write_atomic(GHOSTS / f"{run}.json", lambda p: p.write_text(json.dumps(ghost), encoding="utf-8"))
        files = sorted(GHOSTS.glob("*.json"), key=lambda p: p.stat().st_mtime)
        for old in files[:-KEEP_GHOSTS]:
            old.unlink(missing_ok=True)

    def save_maps(self):
        index = {}
        for area, columns in self.levels.items():
            img, seen = render_map(columns)
            write_atomic(MAPS / f"level_{area}.png", lambda p: Image.fromarray(img).save(p, format="PNG"))
            index[area] = {"width": int(img.shape[1]), "height": HEIGHT, "seen": round(seen, 3),
                           "file": f"level_{area}.png"}
        write_atomic(MAPS / "index.json", lambda p: p.write_text(json.dumps({"schema": 1, "levels": index}), encoding="utf-8"))

    def save_moments(self):
        if self.book.dirty:
            self.book.dirty = False
            doc = {"schema": 1, "game": "mario-land", "moments": self.book.ranked()}
            write_atomic(DIR / "moments.json", lambda p: p.write_text(json.dumps(doc), encoding="utf-8"))

    def next_doc(self):
        files = sorted(INBOX.glob("*.json"), key=lambda p: p.stat().st_mtime)
        for old in files[:-BACKLOG]:
            old.unlink(missing_ok=True)
        files = files[-BACKLOG:]
        for path in reversed(files):
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            path.unlink(missing_ok=True)
            return doc
        return None


def cartographer_main(end, macros):
    from watch_mario_land import low_priority
    low_priority()
    for d in (INBOX, MAPS, GHOSTS):
        d.mkdir(parents=True, exist_ok=True)
    c = Cartographer(macros)
    last_save = 0
    while time.time() < end:
        doc = c.next_doc()
        if doc is None:
            time.sleep(0.25)
        else:
            c.write_ghost(doc, c.replay(doc))
            c.save_moments()
        if c.levels and time.time() - last_save > SAVE_EVERY_S:
            last_save = time.time()
            c.save_maps()
