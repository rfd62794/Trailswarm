"""The Mario Land viewer: replays the best run from the start of the game at normal speed, plus highlights.

Owns the only viewer card. Reads the best run the workers publish (mario_search.read_best) and the cartographer's
moments list; never searches itself.
"""
import collections
import io
import time
from pathlib import Path

from mario_search import DIR, MACROS, press_macro, read_best, read_json
from mario_value import best_order

LEVELS = [(w, l) for w in range(1, 5) for l in range(1, 4)]
AGENT = "mario-land"
CLIP_LEAD, CLIP_TAIL = 150, 90


class Display:
    def __init__(self, workers, rom_path):
        from pokeagent.emulator import PyBoyEmulator
        from pokeagent.snapshot import Thinking
        from pokeagent.telemetry import FramePublisher
        self.emu = PyBoyEmulator(Path(rom_path), headless=True)
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
        self.shown = set()
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
                                   f"progress {self.w.level_progress}, best value {(self.best or {}).get('value', 0)} | underneath: {live} workers, "
                                   f"{tries} attempts, {deaths} deaths"),
            frame_slot=self.pub.name, updated_at=time.time())

    def watch(self, n):
        for _ in range(n):
            self.py.tick(1, True)
            self.pub.publish(advance=False)

    def restart(self):
        self.boot.seek(0)
        self.py.load_state(self.boot)

    def play_highlight(self):
        """Fast-forward to the best moment not shown yet and play it at normal speed."""
        doc = read_json(DIR / "moments.json")
        fresh = [m for m in (doc or {}).get("moments", []) if m["key"] not in self.shown and m["kills"] > 0]
        if not fresh:
            return
        moment = fresh[0]
        self.shown.add(moment["key"])
        start, stop = moment["frame"] - CLIP_LEAD, moment["end_frame"] + CLIP_TAIL
        self.think.plan = f"highlight in {moment['area']}: {moment['why']}"
        self.think.result = moment["agent"]
        self.events.append((self.step, f"highlight in {moment['area']}: {moment['why']}"))
        self.restart()
        self.py.set_emulation_speed(0)
        frame = 0

        def tick(n):
            nonlocal frame
            for _ in range(n):
                if frame == start:
                    self.py.set_emulation_speed(1)
                if frame >= start:
                    self.watch(1)
                else:
                    self.py.tick(1, False)
                frame += 1

        for m in moment["seq"]:
            press_macro(self.py, m, tick)
            self.step += 1
            self.refresh()
            if frame > stop:
                break
        self.watch(45)

    def play_best(self):
        doc = read_best()
        if doc is None:
            self.think.plan = "waiting for the first result from underneath"
            self.py.set_emulation_speed(1)
            self.watch(30)
            self.refresh()
            return
        if self.best is None or best_order(doc) > best_order(self.best):
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
        self.play_highlight()
