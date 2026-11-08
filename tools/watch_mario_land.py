"""Super Mario Land: players search headless underneath, and the viewer shows only the best run.

Run from the repo root:  uv run python tools/watch_mario_land.py [--workers 2] [--minutes 90]

Each worker is a headless emulator process. It keeps a save state per stretch reached, tries button patterns
from the furthest ones, and publishes its best input sequence to runs/mario-land/best.json. Workers adopt each
other's best. Any future model can join by writing the same file: an input sequence plus how far it got.

The display process owns the only viewer card. It replays the best sequence from the start of the game at normal
speed, then picks up whatever is best by then.
"""
import argparse
import collections
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

R, B, A, L = "right", "b", "a", "left"
MACROS = [("run", [R, B], 12), ("run far", [R, B], 24), ("short hop", [R, B, A], 10), ("jump", [R, B, A], 20),
          ("big jump", [R, B, A], 32), ("walk jump", [R, A], 20), ("jump up", [A], 24), ("back up", [L], 10),
          ("wait", [], 8), ("walk", [R], 8), ("walk through the exit", [R], 720)]
WAIT = len(MACROS) - 1
BUCKET = 24
PROBE = 100
LEVELS = [(w, l) for w in range(1, 5) for l in range(1, 4)]
AGENT = "mario-land"
DIR = Path("runs") / "mario-land"
BEST = DIR / "best.json"


def low_priority():
    if os.name == "nt":
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)


def rom():
    return glob.glob("roms/Super Mario Land*.gb")[0]


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


def as_key(doc):
    return ((doc["key"][0][0], doc["key"][0][1]), doc["key"][1])


def press_macro(py, macro, tick):
    _, buttons, frames = MACROS[macro]
    for b in buttons:
        py.button_press(b)
    tick(frames)
    for b in buttons:
        py.button_release(b)
    tick(1)


class Worker:
    def __init__(self, index):
        from pyboy import PyBoy
        self.index = index
        self.py = PyBoy(rom(), window="null")
        self.py.set_emulation_speed(0)
        self.w = self.py.game_wrapper
        self.w.start_game()
        self.rng = random.Random(index * 7919 + int(time.time()))
        self.tries = self.deaths = 0
        self.boot = self.save()
        self.cells = {self.key(): {"state": self.boot, "seq": [], "lives": self.w.lives_left}}

    def key(self):
        return (self.w.world, self.w.level_progress // BUCKET)

    def save(self):
        f = io.BytesIO()
        self.py.save_state(f)
        return f.getvalue()

    def load(self, blob):
        self.py.load_state(io.BytesIO(blob))

    def tick(self, n):
        self.py.tick(n, False)

    def publish(self, key):
        doc = read_json(BEST)
        if doc is None or key > as_key(doc):
            write_json(BEST, {"key": [list(key[0]), key[1]], "seq": self.cells[key]["seq"], "worker": self.index,
                              "lives": self.cells[key]["lives"], "at": time.time()})

    def adopt(self):
        doc = read_json(BEST)
        if doc is None or as_key(doc) <= max(self.cells):
            return
        self.load(self.boot)
        for m in doc["seq"]:
            press_macro(self.py, m, self.tick)
        k = self.key()
        if k > max(self.cells):
            self.cells[k] = {"state": self.save(), "seq": list(doc["seq"]), "lives": self.w.lives_left}

    def attempt(self):
        order = sorted(self.cells, reverse=True)
        pick = order[min(int(self.rng.expovariate(0.35)), len(order) - 1)]
        cell = self.cells[pick]
        self.load(cell["state"])
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
                return
            k = self.key()
            if k > pick and k not in self.cells:
                blob = self.save()
                self.tick(PROBE)
                alive = self.w.lives_left >= cell["lives"]
                self.load(blob)
                if alive:
                    self.cells[k] = {"state": blob, "seq": list(seq), "lives": self.w.lives_left}
                    if k == max(self.cells):
                        self.publish(k)


def worker_main(index, end):
    low_priority()
    w = Worker(index)
    stat = DIR / f"worker-{index}.json"
    last = 0
    while time.time() < end:
        w.attempt()
        if time.time() - last > 3:
            last = time.time()
            w.adopt()
            write_json(stat, {"tries": w.tries, "deaths": w.deaths, "kept": len(w.cells), "at": last})


class Display:
    def __init__(self, workers):
        from pokeagent.emulator import PyBoyEmulator
        from pokeagent.snapshot import Thinking
        from pokeagent.telemetry import FramePublisher
        self.emu = PyBoyEmulator(Path(rom()), headless=True)
        self.py = self.emu._pyboy
        self.w = self.py.game_wrapper
        self.w.game_area_mapping(self.w.mapping_minimal, 0)
        self.w.start_game()
        self.boot = io.BytesIO()
        self.py.save_state(self.boot)
        self.pub = FramePublisher(AGENT, self.emu)
        self.workers = workers
        self.step = 0
        self.best = None
        self.events = collections.deque(maxlen=20)
        self.think = Thinking(driver="explorer", want="show the best run found so far")
        self.snap = None
        self.next_stats = 0
        self.totals = (0, 0, 0)
        self.refresh()

    def stats(self):
        if time.time() >= self.next_stats:
            self.next_stats = time.time() + 2
            docs = [read_json(DIR / f"worker-{i}.json") or {} for i in range(self.workers)]
            self.totals = (sum(d.get("tries", 0) for d in docs), sum(d.get("deaths", 0) for d in docs),
                           sum(1 for d in docs if time.time() - d.get("at", 0) < 15))
        return self.totals

    def refresh(self):
        from pokeagent.snapshot import AgentSnapshot, Event, Goal, Screen, Sees, Segment
        world = self.w.world
        rows = ["".join(" M*#E"[int(v)] for v in row) for row in self.w.game_area()]
        top = tuple(self.best["key"][0]) if self.best else (1, 1)
        goals = [Goal(id=f"{a}-{b}", name=f"World {a}-{b}",
                      status="done" if (a, b) < top else "current" if (a, b) == top else "ahead") for a, b in LEVELS]
        tries, deaths, live = self.stats()
        self.snap = AgentSnapshot(
            agent_id=AGENT, kind="explorer", step=self.step, thinking=self.think,
            segment=Segment(id=f"{world[0]}-{world[1]}", name=f"Super Mario Land {world[0]}-{world[1]}", steps=self.step),
            goals=goals, drivers={"explorer": tries, "rl": 0, "human": 0, "claude": 0}, drivers_available=["explorer"],
            recent=[e if isinstance(e, Event) else Event(step=e[0], driver="explorer", text=e[1]) for e in self.events],
            sees=Sees(rows=rows, mode="overworld"),
            screen=Screen(box_text=f"best run playing: lives {self.w.lives_left}, score {self.w.score}, "
                                   f"progress {self.w.level_progress} | underneath: {live} workers, "
                                   f"{tries} attempts, {deaths} deaths"),
            frame_slot=self.pub.name, updated_at=time.time())

    def watch(self, n):
        for _ in range(n):
            self.py.tick(1, True)
            self.pub.publish(advance=False)

    def restart(self):
        self.boot.seek(0)
        self.py.load_state(self.boot)

    def play_best(self):
        doc = read_json(BEST)
        if doc is None:
            self.think.plan = "waiting for the first result from underneath"
            self.py.set_emulation_speed(1)
            self.watch(30)
            self.refresh()
            return
        if self.best is None or as_key(doc) > as_key(self.best):
            self.events.append((self.step, f"new best from worker {doc.get('worker')}: world "
                                           f"{doc['key'][0][0]}-{doc['key'][0][1]}, stretch {doc['key'][1]}"))
        self.best = doc
        self.think.plan = f"replaying the best run, {len(doc['seq'])} moves"
        self.restart()
        self.py.set_emulation_speed(1)
        for m in doc["seq"]:
            press_macro(self.py, m, self.watch)
            self.think.rule, self.think.button = MACROS[m][0], "+".join(MACROS[m][1]) or "none"
            self.step += 1
            self.refresh()
        self.events.append((self.step, f"replay ended at {self.w.world[0]}-{self.w.world[1]}, progress {self.w.level_progress}"))
        self.watch(120)
        self.refresh()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--minutes", type=float, default=90)
    a = ap.parse_args()
    low_priority()
    DIR.mkdir(parents=True, exist_ok=True)
    BEST.unlink(missing_ok=True)
    end = time.time() + a.minutes * 60
    procs = [mp.Process(target=worker_main, args=(i, end), daemon=True) for i in range(a.workers)]
    for p in procs:
        p.start()
    from pokeagent import agent_registry
    from pokeagent.control_server import ControlServer
    d = Display(a.workers)
    ctl = ControlServer(lambda: d.snap, {})
    port = ctl.start()
    root = Path(".")
    agent_registry.register(root, AGENT, "explorer", port, d.pub.name, token=ctl.token)
    print(f"registered {AGENT} on port {port}, slot {d.pub.name}, pid {os.getpid()}", flush=True)
    try:
        while time.time() < end:
            d.play_best()
    finally:
        agent_registry.unregister(root, AGENT)
        ctl.stop()
        d.pub.close()
        d.emu.close()
        for p in procs:
            p.terminate()


if __name__ == "__main__":
    sys.exit(main())
