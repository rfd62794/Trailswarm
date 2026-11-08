"""Super Mario Land search: input macros, the headless Worker, and the JSON files workers share.

Each worker keeps one cell per (world, progress bucket) with its own save state, input sequence, lives and style
value. Distance decides what is best; value (mario_value) replaces a cell's run only within the same cell.
Every worker writes its own runs/mario-land/best-<n>.json, so there is no read-compare-write race; readers take
the max with read_best().
"""
import ctypes
import glob
import io
import json
import multiprocessing as mp
import os
import random
import sys
import time
from pathlib import Path

from mario_moments import classify
from mario_value import add_event, best_order, carried_fails, should_replace

R, B, A, L = "right", "b", "a", "left"
MACROS = [("run", [R, B], 12), ("run far", [R, B], 24), ("short hop", [R, B, A], 10), ("jump", [R, B, A], 20),
          ("big jump", [R, B, A], 32), ("walk jump", [R, A], 20), ("jump up", [A], 24), ("back up", [L], 10),
          ("wait", [], 8), ("walk", [R], 8), ("walk through the exit", [R], 720)]
WAIT = len(MACROS) - 1
BUCKET = 24
PROBE = 240
RETIRE_AFTER = 40            # consecutive deaths from one save point before it stops being tried
OFF_SCREEN_Y = 165           # Mario sprite y once he has fallen below the screen
DEATH_SAMPLE = 15
TIMER_REFRESH = 4            # frames between timer baseline refreshes; a stale baseline would make every kill a bonus
DIR = Path("runs") / "mario-land"
INBOX = DIR / "inbox"
BEST_GLOB = "best-*.json"


def low_priority():
    if os.name == "nt":
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)


def parent_gone():
    """True in a child process once the process that started it has died (a hard kill runs no cleanup)."""
    parent = mp.parent_process()
    return parent is not None and not parent.is_alive()


def find_rom():
    """The ROM path, or exit with a clear message. Checked once in main() before anything is spawned."""
    found = glob.glob("roms/Super Mario Land*.gb")
    if not found:
        sys.exit("No Super Mario Land ROM found: put it in roms/ (matching 'Super Mario Land*.gb'). "
                 "ROMs are never committed.")
    return found[0]


def write_json(path, doc):
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(doc), encoding="utf-8")
    for _ in range(40):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.05)
    tmp.unlink(missing_ok=True)


def read_json(path):
    for _ in range(5):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            time.sleep(0.05)
    return None


def read_best():
    """The best document across all workers' files: furthest first, then highest value."""
    docs = [d for d in (read_json(p) for p in DIR.glob(BEST_GLOB)) if d]
    return max(docs, key=best_order, default=None)


def clear_best():
    for p in DIR.glob(BEST_GLOB):
        p.unlink(missing_ok=True)
    (DIR / "best.json").unlink(missing_ok=True)


def press_macro(py, macro, tick):
    _, buttons, frames = MACROS[macro]
    for b in buttons:
        py.button_press(b)
    tick(frames)
    for b in buttons:
        py.button_release(b)
    tick(1)


class Worker:
    def __init__(self, index, rom_path):
        from pyboy import PyBoy
        self.index = index
        self.py = PyBoy(rom_path, window="null")
        self.py.set_emulation_speed(0)
        self.w = self.py.game_wrapper
        self.w.game_area_mapping(self.w.mapping_minimal, 0)
        self.w.start_game()
        self.rng = random.Random(index * 7919 + int(time.time()))
        self.tries = self.deaths = self.replaced = 0
        self.sent = 0
        self.last_sent = 0
        self.boot = self.save()
        self.start_meter(0)
        self.cells = {self.key(): {"state": self.boot, "seq": [], "lives": self.w.lives_left, "value": 0,
                                  "progress": self.w.level_progress}}
        self.best = (max(self.cells), 0)

    def key(self):
        return (self.w.world, self.w.level_progress // BUCKET)

    def save(self):
        f = io.BytesIO()
        self.py.save_state(f)
        return f.getvalue()

    def load(self, blob, value=0):
        self.py.load_state(io.BytesIO(blob))
        self.start_meter(value)

    def start_meter(self, value):
        self.value = value
        self.score, self.coins, self.timer = self.w.score, self.w.coins, self.w.time_left
        self.frame = 0

    def tick(self, n):
        """Advance n frames, adding style value. Only the score is read each frame; coins and the timer are read
        when the score rose (and the timer baseline every TIMER_REFRESH frames), the grid only on a rise."""
        for _ in range(n):
            self.py.tick(1, False)
            self.frame += 1
            score = self.w.score
            if score != self.score:
                gained, coins, timer = score - self.score, self.w.coins, self.w.time_left
                if gained > 0:
                    kind = classify(gained, coins > self.coins, timer < self.timer, self.w.game_area())
                    self.value = add_event(self.value, kind, gained)
                self.score, self.coins, self.timer = score, coins, timer
            elif self.frame % TIMER_REFRESH == 0:
                self.coins, self.timer = self.w.coins, self.w.time_left

    def send(self, seq, outcome):
        """Hand an attempt to the cartographer, at most one every two seconds."""
        now = time.time()
        if now - self.last_sent < 2:
            return
        self.last_sent = now
        self.sent += 1
        write_json(INBOX / f"{self.index}-{self.sent}.json",
                   {"seq": seq, "outcome": outcome, "worker": self.index, "at": now})

    def retired(self, key):
        return self.cells[key].get("fails", 0) >= RETIRE_AFTER

    def survives(self, lives, new_level):
        """Reaching a new level is always kept: standing idle at its start would let the first enemy reject it."""
        if new_level:
            return True
        self.py.tick(PROBE, False)
        return self.w.lives_left >= lives and self.py.memory[0xC201] < OFF_SCREEN_Y

    def publish(self, key):
        cell = self.cells[key]
        doc = {"key": [list(key[0]), key[1]], "seq": cell["seq"], "worker": self.index, "lives": cell["lives"],
               "value": cell["value"], "at": time.time()}
        if best_order(doc) > self.best:
            self.best = best_order(doc)
            write_json(DIR / f"best-{self.index}.json", doc)

    def adopt(self):
        doc = read_best()
        if doc is None or best_order(doc) <= self.best:
            return
        self.load(self.boot)
        for m in doc["seq"]:
            press_macro(self.py, m, self.tick)
        k, lives, progress = self.key(), self.w.lives_left, self.w.level_progress
        old = self.cells.get(k)
        if old is None or should_replace(old["value"], old["lives"], self.value, lives, old["progress"], progress):
            fails = carried_fails(old.get("fails", 0), old["progress"], progress) if old else 0
            self.cells[k] = {"state": self.save(), "seq": list(doc["seq"]), "lives": lives, "value": self.value,
                             "progress": progress, "fails": fails}
        self.best = max(self.best, best_order(doc))

    def attempt(self):
        ranked = sorted(self.cells, reverse=True)
        order = [k for k in ranked if not self.retired(k)] or ranked
        pick = order[min(int(self.rng.expovariate(0.35)), len(order) - 1)]
        cell = self.cells[pick]
        self.load(cell["state"], cell["value"])
        seq = list(cell["seq"])
        count = self.rng.randint(1, 6)
        for i in range(count):
            m = self.rng.randrange(WAIT)
            if pick == order[0] and i == count - 1 and self.rng.random() < 0.25:
                m = WAIT
            press_macro(self.py, m, self.tick)
            seq.append(m)
            self.tries += 1
            if self.w.lives_left < cell["lives"] or self.w.game_over():
                self.deaths += 1
                cell["fails"] = cell.get("fails", 0) + 1
                if self.deaths % DEATH_SAMPLE == 0:
                    self.send(seq, "death")
                return
            self.consider(pick, cell, seq)

    def consider(self, pick, cell, seq):
        """Keep the current position as a new cell, or as a better run of an existing one."""
        k = self.key()
        old = self.cells.get(k)
        fresh = k > pick and (old is None or self.retired(k))
        progress = self.w.level_progress
        better = old is not None and should_replace(old["value"], old["lives"], self.value, self.w.lives_left,
                                                    old["progress"], progress)
        if not (fresh or better):
            return
        blob, value = self.save(), self.value
        need = cell["lives"] if fresh else old["lives"]
        alive = self.survives(need, fresh and k[0] != pick[0])
        self.load(blob, value)
        if not alive:
            return
        fails = 0 if fresh else carried_fails(old.get("fails", 0), old["progress"], progress)
        self.cells[k] = {"state": blob, "seq": list(seq), "lives": self.w.lives_left, "value": value,
                         "progress": progress, "fails": fails}
        if fresh:
            cell["fails"] = 0
        else:
            self.replaced += 1
        if k == max(self.cells):
            self.publish(k)
            self.send(seq, "best")


def worker_main(index, end, rom_path):
    low_priority()
    w = Worker(index, rom_path)
    stat = DIR / f"worker-{index}.json"
    last = 0
    while time.time() < end and not parent_gone():
        w.attempt()
        if time.time() - last > 3:
            last = time.time()
            w.adopt()
            write_json(stat, {"tries": w.tries, "deaths": w.deaths, "kept": len(w.cells),
                              "replaced": w.replaced, "at": last})
