"""Learning explorer demo: one window (game left, console right), a rule-based agent that LEARNS the map.

    uv run python tools/explore_demo.py                  # from the repo root; needs baselines/bedroom.state
    uv run python tools/explore_demo.py --steps 400 --maps runs/maps.json

What it learns, and where it goes so the real framework can reuse it:
  runs/maps.json                 cumulative map memory (same schema Map_Memory_Directive adopts):
                                 per map id: visited tiles with counts, blocked (x,y,DIR), warps (x,y,DIR)->[map,x,y]
  runs/explore-<ts>/transitions.jsonl   one line per press: from, button, to, moved, textbox, source
Policy: if a text box is open (border tile 0x79 in the tile map) press A; otherwise pick the direction from the
current tile that is not known-blocked and leads to the least-visited tile. Human steering: click the window and
use arrows / a (A) / s (B) / Enter (START) / Shift (SELECT); p pauses the agent. Human presses are learned too.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import tkinter as tk
from pathlib import Path

from PIL import Image, ImageTk

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pokeagent.emulator import Button, PyBoyEmulator  # noqa: E402
from pokeagent.hexmap import diff as ram_diff  # noqa: E402  (framework module, landed in directive 4)
from pokeagent.names import load_registry  # noqa: E402
from pokeagent.ram import read_state  # noqa: E402
from pokeagent.screentext import CHARMAP  # noqa: E402  (verified charmap lives in the framework now)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from explore_plan import ControlServer, WorldGraph, plan_step, png_bytes  # noqa: E402

import queue  # noqa: E402
from concurrent.futures import Future  # noqa: E402

GOAL_MENU = {"potion": ["WITHDRAW ITEM", "POTION"]}  # menu options to take, in order, while a goal is unmet
# YES/NO boxes: the answer depends on the question that was on screen just before. First match wins; default YES.
YESNO_RULES = [("nickname", "NO"), (" name ", "NO"), ("toss", "NO"), ("deposit", "NO"), ("release", "NO"),
               ("give up", "NO"), (" run ", "NO"), ("", "YES")]  # spaced needles = whole words


STARTERS = ["BULBASAUR", "CHARMANDER", "SQUIRTLE"]


def yesno_answer(question: str, starter: str = "any") -> tuple[str, str]:
    q = " " + "".join(ch for ch in question.lower() if ch.isalnum() or ch == " ") + " "  # tolerant of ?,!,é and line breaks
    offered = next((s for s in STARTERS if s.lower() in q.replace(" ", "")), None)
    if offered and "want" in q and "nickname" not in q and "name" not in q.split():  # "So! You want CHARMANDER?"
        if starter == "any" or starter.upper() == offered:
            return "YES", f"starter offered: {offered} (wanted {starter})"
        return "NO", f"starter offered: {offered}, but we want {starter}"
    for needle, ans in YESNO_RULES:
        if needle in q:
            return ans, (f"'{needle}' in the question" if needle else "default for confirmations")
    return "YES", "default"


def goal_menu_choice(goals: dict, options: list[str]) -> str | None:
    for goal, wanted in GOAL_MENU.items():
        if not goals.get(goal):
            for w in wanted:
                # Containment, not prefix: an item list drawn over the PC menu reads "DE POTION", "TO CANCEL".
                hit = next((o for o in options if w in o and "CANCEL" not in o), None)
                if hit:
                    return hit
    return None

DIRS = {"UP": (0, -1), "DOWN": (0, 1), "LEFT": (-1, 0), "RIGHT": (1, 0)}
# Screen-tile offsets of the 2x2 map tile in front of the player (player sprite sits at rows 8-9, cols 8-9).
AHEAD = {"UP": [(6, 8), (6, 9), (7, 8), (7, 9)], "DOWN": [(10, 8), (10, 9), (11, 8), (11, 9)],
         "LEFT": [(8, 6), (8, 7), (9, 6), (9, 7)], "RIGHT": [(8, 10), (8, 11), (9, 10), (9, 11)]}
EFFECT_WINDOW = (0xD000, 0x900)  # bag, money, map, party, event flags: diffed around every interaction
REGISTRY = load_registry()


GOALS = ["potion", "left_house", "first_pokemon", "won_battle"]  # Robert's first optimisation targets (2026-11-02)


def check_goals(emu, st: dict) -> dict[str, bool]:
    """Milestones read straight from RAM (bag 0xD31D/E verified; party 0xD163 and battle 0xD057 unverified)."""
    bag_n = emu.read(0xD31D)
    bag = emu.read_range(0xD31E, 2 * bag_n) if 0 < bag_n < 21 else b""  # PyBoy rejects empty slices
    potion = any(bag[i] == 0x14 for i in range(0, len(bag), 2))
    m = emu.read(0xD35E)
    return {"potion": potion, "left_house": m not in (0x25, 0x26) or st.get("goal_left_house", False),
            "first_pokemon": emu.read(0xD163) > 0, "won_battle": st.get("battles_won", 0) > 0}


def ahead_tiles(tilemap: bytes, direction: str) -> list[int]:
    return [tilemap[r * 20 + c] for r, c in AHEAD[direction]]


def sprite_snapshot(emu) -> list[list[int]]:
    """[picture id, map y, map x] for NPC sprite slots 1-15 (wSpriteStateData, UNVERIFIED addresses)."""
    out = []
    for i in range(1, 16):
        pic = emu.read(0xC100 + 16 * i)
        if pic:
            out.append([pic, emu.read(0xC204 + 16 * i), emu.read(0xC205 + 16 * i)])
    return out


def npc_positions(emu) -> set:
    return {(emu.read(0xC205 + 16 * i) - 4, emu.read(0xC204 + 16 * i) - 4) for i in range(1, 16) if emu.read(0xC100 + 16 * i)}


def ascii_vision(emu, mem, tileset: int) -> list[str]:
    """Cheap vision: the visible 10x9 map tiles as one character each, from RAM, no image model.
    @ player, N an NPC (sprite table), # tile ids learned solid, . learned walkable, ? never tried,
    W a learned warp tile; an open text box replaces the bottom rows with its decoded text."""
    tm = emu.read_range(TILEMAP, TILEMAP_LEN)
    m, px, py = emu.read(0xD35E), emu.read(0xD362), emu.read(0xD361)
    d = mem.m(m)
    npcs = {(emu.read(0xC205 + 16 * i) - 4, emu.read(0xC204 + 16 * i) - 4) for i in range(1, 16) if emu.read(0xC100 + 16 * i)}
    warps = {tuple(map(int, k.split(",")[:2])) for k in d.get("warps", {})}
    rows = []
    for r in range(9):
        line = ""
        for c in range(10):
            mx, my = px + (c - 4), py + (r - 4)
            block = [tm[(2 * r) * 20 + 2 * c], tm[(2 * r) * 20 + 2 * c + 1], tm[(2 * r + 1) * 20 + 2 * c], tm[(2 * r + 1) * 20 + 2 * c + 1]]
            if (c, r) == (4, 4):
                ch = "@"
            elif (mx, my) in npcs:
                ch = "N"
            elif (mx, my) in warps:
                ch = "W"
            else:
                e = mem.data.get("tile_types", {}).get(str(tileset), {}).get(",".join(f"{b:02X}" for b in block))
                ch = "?" if not e else ("#" if e["solid"] > e["walkable"] else ".")
            line += ch
        rows.append(line)
    return rows  # text boxes are NOT part of the map: the dialog pane shows them


def battle_view(emu) -> list[str]:
    """What the agent 'sees' in a battle: not a map. HP/level from RAM (pret/pokered addresses, UNVERIFIED until
    we watch them move: wBattleMonHP 0xD015/16, wBattleMonMaxHP 0xD023/24, wBattleMonLevel 0xD022,
    wEnemyMonHP 0xCFE6/E7, wEnemyMonMaxHP 0xCFF4/F5, wEnemyMonLevel 0xCFF3) plus the on-screen text and menu."""
    def u16(a): return (emu.read(a) << 8) | emu.read(a + 1)
    tm = emu.read_range(TILEMAP, TILEMAP_LEN)
    lines = frame_lines(tm)
    rows = [f"BATTLE kind=0x{emu.read(0xD057):02X}",
            f"you   L{emu.read(0xD022):<3} HP {u16(0xD015):>3}/{u16(0xD023):<3}",
            f"enemy L{emu.read(0xCFF3):<3} HP {u16(0xCFE6):>3}/{u16(0xCFF4):<3}",
            "(hp addrs unverified)", ""]
    menu = [ln for ln in lines if ">" in ln or ln.isupper()]
    rows += ["MENU/TEXT:"] + [ln[:20] for ln in (menu or lines)[:6]]
    return rows


def effects(before: bytes, after: bytes) -> tuple[list[list[int]], str]:
    """RAM deltas around an interaction, capped, plus a one-line human summary using the registry's names."""
    changes = ram_diff(before, after, base=EFFECT_WINDOW[0])[:64]
    raw = [[c.addr, c.old, c.new] for c in changes]
    named = []
    for c in changes:
        e = REGISTRY.by_addr(c.addr)
        if e:
            named.append(f"{e.name} {c.old}->{c.new}")
    summary = ", ".join(named[:6]) if named else (f"{len(raw)} unnamed bytes changed" if raw else "no RAM change")
    return raw, summary


def box_open(tilemap: bytes) -> bool:
    """A frame is open when a top-left corner tile is immediately followed by a top-edge tile."""
    i = tilemap.find(bytes([BORDER_TL, 0x7A]))
    return i >= 0


def frame_lines(tilemap: bytes) -> list[str]:
    """Readable text lines anywhere on screen (dialog rows, menus, lists); '>' marks the menu cursor."""
    out = []
    for r in range(18):
        row = tilemap[r * 20:(r + 1) * 20]
        if row.count(0x7C) < 2:  # only rows inside a frame (left and right edge tiles present)
            continue
        inner = row[row.index(0x7C) + 1:len(row) - row[::-1].index(0x7C) - 1]
        line = "".join(ch if ch.isprintable() else " " for ch in (CHARMAP.get(b, " ") or " " for b in inner)).strip()
        if any(ch.isalnum() for ch in line):
            out.append(" ".join(line.split()))
    return out


def box_text(tilemap: bytes) -> str:
    return " | ".join(frame_lines(tilemap))


def is_menu(tilemap: bytes) -> bool:
    return 0xED in tilemap  # the ▶ cursor tile (verified)
KEYS = {"Up": "UP", "Down": "DOWN", "Left": "LEFT", "Right": "RIGHT", "a": "A", "s": "B",
        "Return": "START", "Shift_L": "SELECT", "Shift_R": "SELECT"}
TILEMAP, TILEMAP_LEN, BORDER_TL = 0xC3A0, 360, 0x79


class MapMemory:
    def __init__(self, path: Path):
        self.path = path
        self.data = json.loads(path.read_text()) if path.exists() else {"maps": {}}

    def m(self, map_id: int) -> dict:
        return self.data["maps"].setdefault(str(map_id), {"visited": {}, "blocked": [], "warps": {}, "last_seen": 0})

    def visit(self, map_id, x, y, step):
        d = self.m(map_id); d["visited"][f"{x},{y}"] = d["visited"].get(f"{x},{y}", 0) + 1; d["last_seen"] = step

    def learn(self, before, button, after, *, confirmed: bool) -> str:
        """Record what a press did. A move that fails is only 'blocked' once CONFIRMED (same press from
        the same tile failed twice in a row); a single failure can be a turn-in-place or a warp fade."""
        (m0, x0, y0), (m1, x1, y1) = before, after
        if button not in DIRS:
            return "pressed"
        key = f"{x0},{y0},{button}"
        blocked = self.m(m0)["blocked"]
        if m1 != m0:
            w = self.m(m0)["warps"]
            taken = self.m(m0).setdefault("warp_taken", {})
            taken[key] = taken.get(key, 0) + 1
            w[key] = [m1, x1, y1]  # exact [map, x, y] shape for the Map_Memory module; counts live beside it
            return f"WARP to map 0x{m1:02X} ({x1},{y1}) - taken {taken[key]}x"
        if (x1, y1) == (x0, y0):
            if not confirmed:
                return "no move (turned? fading?) - will retry once before calling it blocked"
            if key not in blocked:
                blocked.append(key)
            return "blocked (confirmed)"
        if key in blocked:
            blocked.remove(key)  # it was a false 'blocked' (learned during a fade); forget it
            return "moved - cleared a false wall"
        return "moved"

    # --- tile types: which 2x2 tile-id blocks are solid, learned per tileset, so a bookshelf is never bumped twice ---
    def learn_tiles(self, tileset: int, ahead: list[int], walkable: bool):
        t = self.data.setdefault("tile_types", {}).setdefault(str(tileset), {})
        key = ",".join(f"{b:02X}" for b in ahead)
        e = t.setdefault(key, {"solid": 0, "walkable": 0})
        e["walkable" if walkable else "solid"] += 1

    def known_solid(self, tileset: int, ahead: list[int]) -> bool:
        e = self.data.get("tile_types", {}).get(str(tileset), {}).get(",".join(f"{b:02X}" for b in ahead))
        return bool(e) and e["solid"] >= 3 and e["walkable"] == 0

    def render_memory(self, map_id: int, x: int, y: int, npcs: set, radius: int = 6) -> list[str]:
        """What the agent REMEMBERS around it: . visited, # a wall it confirmed, W warp, i interaction, N NPC, @ you."""
        d = self.m(map_id)
        visited = {tuple(map(int, k.split(","))) for k in d.get("visited", {})}
        warps = {tuple(map(int, k.split(",")[:2])) for k in d.get("warps", {})}
        inter = {tuple(map(int, k.split(",")[:2])) for k, e in d.get("interactions", {}).items() if e.get("text")}
        walls = set()
        for k in d.get("blocked", []):
            bx, by, bd = k.split(","); dx, dy = DIRS[bd]; walls.add((int(bx) + dx, int(by) + dy))
        rows = []
        for yy in range(y - radius, y + radius + 1):
            line = ""
            for xx in range(x - radius, x + radius + 1):
                p = (xx, yy)
                line += ("@" if p == (x, y) else "N" if p in npcs else "W" if p in warps else "i" if p in inter
                         else "#" if p in walls and p not in visited else "." if p in visited else " ")
            rows.append(line)
        return rows

    def interact(self, map_id, x, y, facing, text: str) -> dict:
        d = self.m(map_id).setdefault("interactions", {})
        e = d.setdefault(f"{x},{y},{facing}", {"count": 0, "text": "", "presses": [], "menus": [], "choices": []})
        e["count"] += 1
        if text and not e["text"]:
            e["text"] = text[:160]
        return e

    def finish_interaction(self, e: dict, presses: int, menus: list, choices: list):
        """Remember how many presses the whole interaction took and what menus/choices appeared."""
        e["presses"] = (e.get("presses", []) + [presses])[-10:]
        for m in menus:
            if m not in e.setdefault("menus", []):
                e["menus"].append(m)
        for c in choices:
            if c not in e.setdefault("choices", []):
                e["choices"].append(c)

    def interaction_known(self, map_id, x, y, facing) -> bool:
        return f"{x},{y},{facing}" in self.m(map_id).get("interactions", {})

    def choose(self, map_id, x, y, facing: str, tilemap: bytes | None = None, tileset: int = 0) -> tuple[str, str]:
        d = self.m(map_id); best = None
        tried = [n for n in DIRS if f"{x},{y},{n}" in d["blocked"]]
        if tilemap is not None:  # tile ids ahead already known solid (bookshelf, wall, desk) count as tried
            for n in DIRS:
                if n not in tried and self.known_solid(tileset, ahead_tiles(tilemap, n)):
                    tried.append(n)
        # Something blocks the way we face and we never talked to it: that is an interaction point candidate.
        if facing in tried and not self.interaction_known(map_id, x, y, facing):
            return "A", f"at ({x},{y}) facing {facing} is blocked and untested: pressing A to see if it talks"
        for name, (dx, dy) in DIRS.items():
            if name in tried:
                continue
            warp = d["warps"].get(f"{x},{y},{name}")
            if warp:  # a warp leads off this map: score it by how often we already took it, not by an off-map tile
                visits = d.get("warp_taken", {}).get(f"{x},{y},{name}", 1) * 3
            else:
                visits = d["visited"].get(f"{x + dx},{y + dy}", 0)
            if best is None or visits < best[0]:
                best = (visits, name)
        if best is None:
            return "A", "every direction known blocked: pressing A to look around"
        why = f"at ({x},{y}) blocked={tried or 'none'}; {best[1]} leads to a tile seen {best[0]}x"
        return best[1], why

    def save(self):
        self.data["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")  # atomic replace: a kill mid-write cannot corrupt the memory
        tmp.write_text(json.dumps(self.data, indent=1))
        os.replace(tmp, self.path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rom", default="roms/Pokemon Red.gb")
    ap.add_argument("--state", default="baselines/bedroom.state")
    ap.add_argument("--maps", default="runs/maps.json")
    ap.add_argument("--steps", type=int, default=300)
    ap.add_argument("--frames-per-step", type=int, default=30)
    ap.add_argument("--control-port", type=int, default=8765, help="localhost HTTP control API for Claude/MCP")
    ap.add_argument("--starter", default="any", choices=["any", "random", "bulbasaur", "charmander", "squirtle"],
                    help="which ball to take on Oak's table (random picks one per run, for the starter sweep)")
    ap.add_argument("--headless", action="store_true", help="no window: run as fast as the emulator allows (swarm learners)")
    ap.add_argument("--seed", type=int, default=None, help="random seed (swarm learners get different ones)")
    ap.add_argument("--explore-rate", type=float, default=0.2,
                    help="probability that a run ignores known demonstrations and partly ignores the planner, to try to beat the record")
    a = ap.parse_args(argv)
    if a.seed is not None:
        random.seed(a.seed)
    if a.headless:
        a.frames_per_step = 4  # the readiness check still paces presses; nobody is watching
    if a.starter == "random":
        a.starter = random.choice(["bulbasaur", "charmander", "squirtle"])
    explore_run = random.random() < a.explore_rate

    run_dir = Path("runs") / f"explore-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"  # unique even for a swarm started in one second
    run_dir.mkdir(parents=True, exist_ok=True)
    trans = (run_dir / "transitions.jsonl").open("a", encoding="utf-8")
    mem = MapMemory(Path(a.maps))
    emu = PyBoyEmulator(Path(a.rom), headless=True)
    emu.tick(60); emu.load_state(Path(a.state)); emu.tick(30)

    root = tk.Tk(); root.title("PokeAgent explorer demo - 1x  (t turbo, p pause, arrows/a/s/Enter/Shift steer)")
    root.configure(bg="#111")
    screen = tk.Label(root, bg="#111", bd=0); screen.grid(row=0, column=0, padx=8, pady=8)
    con = tk.Text(root, width=78, height=28, bg="#0b0b0b", fg="#d8d8d8", font=("Consolas", 10), bd=0, padx=10, pady=8, wrap="word")
    con.grid(row=0, column=1, padx=(0, 8), pady=8, sticky="ns")
    # third pane: what the agent SEES (tile map as text) and what it REMEMBERS (map memory around it)
    vis = tk.Label(root, bg="#0b0b0b", fg="#9fd8ff", font=("Consolas", 13), justify="left", anchor="nw",
                   padx=10, pady=8, width=22, height=27)
    vis.grid(row=0, column=2, padx=(0, 8), pady=8, sticky="ns")
    # fourth pane under the game: the current dialog / menu text, goals, and battle flag (not on the map)
    dlg = tk.Label(root, bg="#0b0b0b", fg="#ffd9a0", font=("Consolas", 11), justify="left", anchor="nw",
                   padx=10, pady=6, width=58, height=6)
    dlg.grid(row=1, column=0, padx=8, pady=(0, 8), sticky="ew")
    for tag, col in {"hdr": "#7fd1ff", "why": "#c9f29b", "btn": "#ffd166", "res": "#ff9f7f", "human": "#f78fff"}.items():
        con.tag_config(tag, foreground=col)
    st = {"step": 0, "frame": 0, "photo": None, "paused": False, "done": False,
          "facing": "DOWN", "last_fail": None, "box_streak": 0, "settle": 0, "inter": None, "goal_steps": {}, "stable_frames": 0, "explore_run": explore_run, "speed": 1}

    def log(t, tag=None):
        con.insert("end", t + "\n", tag); con.see("end")

    def pos():
        s = read_state(emu); return (s.map_id, s.x, s.y)

    def settle_position(before, max_frames=600):
        """Tick in 8-frame slices until the position has been stable for 3 reads; a map change (warp fade)
        gets 60 more frames and a re-read, so the recorded arrival is the real one, not a mid-fade value."""
        prev, stable, waited = pos(), 0, 0
        while waited < max_frames:
            emu.tick(8); waited += 8
            cur = pos()
            stable = stable + 1 if cur == prev else 0
            prev = cur
            if stable >= 3:
                break
        if prev[0] != before[0]:
            emu.tick(60); prev = pos()
        return prev

    def record_intervention(name: str, source: str, before, tm, goals_before):
        """Human/Claude presses become demonstrations: a sequence from a situation, with what it achieved."""
        ep = st.get("episode")
        if ep is None:
            ep = st["episode"] = {"source": source, "start": list(before), "facing": st["facing"],
                                  "screen": frame_lines(tm)[:3] if box_open(tm) else [], "buttons": [],
                                  "goals_before": goals_before, "step": st["step"]}
        ep["buttons"].append(name)

    def close_episode(after, goals_after):
        ep = st.pop("episode", None)
        if not ep or not ep["buttons"]:
            return
        ep["end"] = list(after); ep["goals_after"] = goals_after
        ep["achieved"] = [g for g in GOALS if goals_after.get(g) and not ep["goals_before"].get(g)]
        with Path("runs/interventions.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(ep) + "\n")
        demos = mem.m(ep["start"][0]).setdefault("demos", [])
        demos.append({"at": ep["start"][1:], "facing": ep["facing"], "screen": ep["screen"], "buttons": ep["buttons"],
                      "achieved": ep["achieved"], "source": ep["source"], "end": ep["end"], "grade": 0, "replays": 0})
        del demos[:-20]
        log(f"[learned a {ep['source']} demonstration: {len(ep['buttons'])} presses from {tuple(ep['start'])}"
            f"{' -> ' + ', '.join(ep['achieved']) if ep['achieved'] else ''}]", "res")

    def matching_demo(m, x, y, tm):
        """A demonstration is a hypothesis, not an order: it is replayed only while its grade is >= 0, and only
        if it achieved a goal when recorded. Every replay is graded afterwards (see grade_replay)."""
        screen = frame_lines(tm)[:3] if box_open(tm) else []
        cands = [d for d in mem.m(m).get("demos", []) if d["at"] == [x, y] and d["screen"] == screen
                 and d.get("achieved") and d.get("buttons") and d.get("grade", 0) >= 0]
        return max(cands, key=lambda d: (d.get("grade", 0), len(d["achieved"]))) if cands else None

    def grade_replay():
        """Called when a replay finishes: did it make progress (a goal, a new map, a new tile)? Grade it."""
        rp = st.pop("replay_ctx", None)
        if not rp:
            return
        goals_now = check_goals(emu, st)
        progressed = any(goals_now[g] and not rp["goals"].get(g) for g in GOALS) or pos()[0] != rp["pos"][0] \
            or (pos() != rp["pos"] and not box_open(emu.read_range(TILEMAP, TILEMAP_LEN)))
        rp["demo"]["grade"] = rp["demo"].get("grade", 0) + (1 if progressed else -1)
        rp["demo"]["replays"] = rp["demo"].get("replays", 0) + 1
        log(f"[replay graded {'GOOD' if progressed else 'BAD'} -> grade {rp['demo']['grade']}"
            f"{'; this demonstration will not be used again' if rp['demo']['grade'] < 0 else ''}]", "res")

    def do_press(name: str, source: str, why: str):
        before = pos(); st["step"] += 1
        tm = emu.read_range(TILEMAP, TILEMAP_LEN)
        box_before = box_open(tm)
        goals_before = check_goals(emu, st)
        if source in ("human", "claude"):
            record_intervention(name, source, before, tm, goals_before)
        elif st.get("episode"):
            close_episode(before, goals_before)  # the agent is back in control: the demonstration is over
        extra: dict = {}
        flag = emu.read(0xD057)
        if flag or st.get("in_battle"):
            extra["battle_flag"] = flag  # wIsInBattle 0xD057 (unverified): logged every battle step to verify it
        if name in DIRS and not box_before:
            extra["ahead_tiles"] = ahead_tiles(tm, name)  # lets the KB learn which tile ids are walls
        if name not in DIRS or box_before:
            st["last_fail"] = None  # a wall is only 'confirmed' by two consecutive identical move presses
        snap_pre = emu.read_range(*EFFECT_WINDOW) if not box_before else None
        emu.press(Button[name])
        after = settle_position(before)
        tm2 = emu.read_range(TILEMAP, TILEMAP_LEN)
        box_after = box_open(tm2)
        text = box_text(tm2) if box_after else ""
        if text and not is_menu(tm2):
            st["last_text"] = text  # the question a YES/NO box will be about
            # Dialog arrives in fragments ("So! You want | the fire POKeMON," then "CHARMANDER?"): keep the whole
            # conversation since the box opened, so a YES/NO decision can read the name even if it scrolled off.
            if not box_before:
                st["dialog"] = []
            if not st.get("dialog") or st["dialog"][-1] != text:
                st.setdefault("dialog", []).append(text)
                del st["dialog"][:-12]
        if name in DIRS and not box_before:
            st["facing"] = name
        inter = st.get("inter")
        if box_before:
            if inter:
                inter["presses"] += 1
                # The first capture happens while the text is still printing ("So! Y"): keep the fullest dialog seen.
                full = " / ".join(st.get("dialog", []))[:400]
                if len(full) > len(inter["entry"].get("text", "")):
                    inter["entry"]["text"] = full
                if is_menu(tm) and name == "A":  # a choice was made on a menu: remember which line the cursor was on
                    chosen = next((ln for ln in frame_lines(tm) if ">" in ln), "").replace(">", "").strip()
                    yn = st.pop("yesno", None)
                    if yn and chosen.endswith(yn["answer"]):
                        chosen = f"YES/NO '{yn['question']}' -> {yn['answer']}"
                    if chosen:
                        inter["choices"].append(chosen)
                if box_after and is_menu(tm2):
                    menu = box_text(tm2)
                    if menu not in inter["menus"]:
                        inter["menus"].append(menu)
            if not box_after and inter:
                mem.finish_interaction(inter["entry"], inter["presses"], inter["menus"], inter["choices"])
                extra["ram_diff"], fx = effects(inter["snap"], emu.read_range(*EFFECT_WINDOW))
                inter["entry"].setdefault("effects", [])
                if fx not in inter["entry"]["effects"]:
                    inter["entry"]["effects"].append(fx)
                result = (f"interaction closed after {inter['presses']} presses; menus seen: {len(inter['menus'])}, "
                          f"choices: {inter['choices'] or 'none'}; effects: {fx}")
                st["inter"] = None
            else:
                result = f"text box: advanced ({'menu' if is_menu(tm2) else 'dialog'})"
        elif name == "A":
            # Record the A press either way, so a silent wall is tested once and never again.
            entry = mem.interact(before[0], before[1], before[2], st["facing"], text if box_after else "")
            if box_after:
                st["inter"] = {"entry": entry, "presses": 1, "menus": [box_text(tm2)] if is_menu(tm2) else [],
                               "choices": [], "snap": snap_pre}
                extra["sprites"] = sprite_snapshot(emu)
            result = (f"INTERACTION at ({before[1]},{before[2]}) facing {st['facing']}: \"{text[:60]}\""
                      if box_after else f"nothing to interact with facing {st['facing']} (remembered)")
        else:
            fail_key = (before, name)
            confirmed = st["last_fail"] == fail_key
            result = mem.learn(before, name, after, confirmed=confirmed)
            if "ahead_tiles" in extra and after[0] == before[0]:
                dx, dy = DIRS[name]
                npc_ahead = (before[1] + dx, before[2] + dy) in npc_positions(emu)
                if result.startswith("blocked (confirmed)") and not npc_ahead and not box_after:
                    mem.learn_tiles(emu.read(0xD367), extra["ahead_tiles"], walkable=False)  # a real wall, not a person
                elif result.startswith("moved"):
                    mem.learn_tiles(emu.read(0xD367), extra["ahead_tiles"], walkable=True)
            st["last_fail"] = fail_key if (name in DIRS and after == before) else None
            if after[0] != before[0]:
                st["settle"] = 30  # fade already waited out; a short pause so the watcher sees the arrival
            if box_after and not st.get("inter"):  # walked into an NPC, or a scripted event fired (Oak!)
                entry = mem.interact(before[0], before[1], before[2], st["facing"], text)
                st["inter"] = {"entry": entry, "presses": 1, "menus": [box_text(tm2)] if is_menu(tm2) else [],
                               "choices": [], "snap": snap_pre}
                extra["sprites"] = sprite_snapshot(emu)
                extra["trigger"] = True  # a box with no A press is a contact/scripted event, not an interaction
                result += f'; event on contact: "{text[:50]}"'
        mem.visit(after[0], after[1], after[2], st["step"])
        st["box_streak"] = st["box_streak"] + 1 if box_after else 0
        trans.write(json.dumps({"step": st["step"], "from": list(before), "button": name, "to": list(after),
                                "moved": before != after, "textbox": "dialog" if box_before else "none",
                                "text": text, "facing": st["facing"], "source": source, **extra}) + "\n")
        trans.flush()  # the later process reads this file while the demo is still running
        mm = mem.m(after[0])
        goals = check_goals(emu, st)
        if goals["left_house"]:
            st["goal_left_house"] = True
        for g in GOALS:  # first time each goal is reached: remember the step and persist it
            if goals[g] and g not in st["goal_steps"]:
                st["goal_steps"][g] = st["step"]; log(f"*** GOAL REACHED: {g} at step {st['step']} ***", "res")
                gp = Path("runs/milestones.json")
                try:
                    hist = json.loads(gp.read_text()) if gp.exists() else {}
                except json.JSONDecodeError:
                    hist = {}
                rec = {"run": run_dir.name, "step": st["step"]}
                if g == "first_pokemon":
                    rec["species_byte"] = emu.read(0xD164)  # wPartySpecies[0] (unverified): 0xB0 Charmander? we learn it
                    rec["wanted"] = a.starter
                hist.setdefault(g, []).append(rec)
                tmp = gp.with_suffix(f".{os.getpid()}.tmp"); tmp.write_text(json.dumps(hist, indent=1)); os.replace(tmp, gp)
        gtxt = " ".join(f"{g}{'+' if goals[g] else '-'}" for g in GOALS)
        log(f"--- step {st['step']}/{a.steps}  map=0x{after[0]:02X} pos=({after[1]},{after[2]}) facing {st['facing']}  "
            f"party={emu.read(0xD163)} bag={emu.read(0xD31D)}  goals: {gtxt}\n"
            f"    learned here: {len(mm['visited'])} tiles, {len(mm['blocked'])} walls, {len(mm['warps'])} warps, "
            f"{len(mm.get('interactions', {}))} interactions", "hdr")
        log(f"{'human:   ' if source == 'human' else 'thinking:'} {why}", "human" if source == "human" else "why")
        log(f"button:   {name:<8} result: {result}", "btn")
        log("", None)
        if st["step"] % 10 == 0:
            mem.save()
        if st["step"] >= a.steps and not st["done"]:
            st["done"] = True; shutdown(); log(f"done. map memory saved to {a.maps}; transitions in {run_dir}", "hdr")

    def shutdown():
        if st.get("episode"):
            close_episode(pos(), check_goals(emu, st))
        inter = st.get("inter")
        if inter:  # keep what an unfinished interaction taught us
            mem.finish_interaction(inter["entry"], inter["presses"], inter["menus"], inter["choices"]); st["inter"] = None
        mem.save()

    def agent_step():
        if st["settle"] > 0:
            st["settle"] -= a.frames_per_step; return
        # Input readiness: do not press while the screen is still changing on its own (cutscene, forced walk,
        # fade, battle animation) or while the game says it is ignoring the joypad (wJoyIgnore, unverified).
        joy_ignore = emu.read(0xCD6B)
        tm_ready = emu.read_range(TILEMAP, TILEMAP_LEN)
        # Only the OVERWORLD needs the stillness check (forced walks, fades, Oak dragging you to the lab).
        # Boxes and menus are paced by the game itself: pressing while text prints is harmless, and a
        # blinking cursor would otherwise look like "still changing" forever (that stalled the 23:20 run).
        busy = not box_open(tm_ready) and (st["stable_frames"] < 8 or joy_ignore)
        if busy:
            if not st.get("waiting"):
                st["waiting"] = True
                log(f"[waiting: {'joypad ignored (0x%02X)' % joy_ignore if joy_ignore else 'screen still changing'} - cutscene?]", "res")
            st["wait_frames"] = st.get("wait_frames", 0) + a.frames_per_step
            extra_wait = {"joy": joy_ignore, "stable": st["stable_frames"], "frames": st["wait_frames"]}
            if st["wait_frames"] < 60 * 4:  # at most ~4 s of game time, then act anyway and log it
                return
            log(f"[waited 4 s, acting anyway: {extra_wait}]", "res")
        if st.get("waiting"):
            st["waiting"] = False
            log(f"[ready after waiting {st.get('wait_frames', 0)} frames]", "res"); st["wait_frames"] = 0
        m, x, y = pos()
        tm_now = emu.read_range(TILEMAP, TILEMAP_LEN)
        lines_now = frame_lines(tm_now) if box_open(tm_now) else []
        in_battle = emu.read(0xD057) != 0 or any(ln.startswith("FIGHT") or "FIGHT" in ln for ln in lines_now)
        if st.get("replay") and (in_battle or box_open(tm_now)):
            st["replay"] = []; grade_replay()  # a box or a battle interrupted the demonstration: grade it now
        if in_battle:
            # First battle logic: always FIGHT with the first move. (A on FIGHT, A on move 1, A through text.)
            if not st.get("in_battle"):
                st["battles"] = st.get("battles", 0) + 1; st["battle_pos"] = (m, x, y)
            st["in_battle"] = True
            st["box_streak"] = 0
            do_press("A", "agent", f"BATTLE (wIsInBattle=0x{emu.read(0xD057):02X}): FIGHT with the first move"); return
        if st.get("in_battle"):
            st["in_battle"] = False
            # Won = still standing where the battle happened with a Pokemon in the party; a loss warps you home.
            won = emu.read(0xD163) > 0 and (m, x, y) == st.get("battle_pos")  # a blackout warps you away
            st["battles_won"] = st.get("battles_won", 0) + (1 if won else 0)
            log(f"[battle over - {'WON' if won else 'lost?'}; {st['battles']} battles this run]", "res")
        if box_open(tm_now):
            if st["box_streak"] >= 12 and is_menu(tm_now):
                do_press("B", "agent", "a menu has stayed open for 12 presses - pressing B to back out"); return
            if st["box_streak"] >= 60:
                do_press("B", "agent", "a dialog has run 60 presses - pressing B in case it is a hidden prompt"); return
            tm = emu.read_range(TILEMAP, TILEMAP_LEN)
            if is_menu(tm):
                # Explore menus: pick the first option we have not chosen at this interaction point yet.
                inter = st.get("inter"); lines = frame_lines(tm)
                options = [ln.replace(">", "").strip() for ln in lines if ">" in ln or (ln.isupper() and len(ln.split()) <= 3)]
                cursor = next((ln.replace(">", "").strip() for ln in lines if ">" in ln), "")
                if {"YES", "NO"} <= {o.split()[-1] for o in options if o}:  # a YES/NO box
                    question = " ".join(ln for ln in lines if "YES" not in ln and "NO" not in ln) or st.get("last_text", "")
                    context = " ".join(st.get("dialog", [])[-4:]) + " " + question
                    ans, why = yesno_answer(context, a.starter)
                    st["yesno"] = {"question": question[:80], "answer": ans}
                    if cursor.endswith(ans):
                        do_press("A", "agent", f"YES/NO box: answering {ans} ({why}) to \"{question[:50]}\""); return
                    do_press("DOWN" if ans == "NO" else "UP", "agent", f"YES/NO box: moving the cursor to {ans} ({why})"); return
                want = goal_menu_choice(check_goals(emu, st), options)
                if want:  # a goal tells us which option to take here
                    if cursor == want:
                        do_press("A", "agent", f"goal menu choice: '{want}'"); return
                    do_press("DOWN", "agent", f"goal menu choice: moving the cursor toward '{want}'"); return
                tried = (inter or {}).get("entry", {}).get("choices", []) + (inter or {}).get("choices", [])
                if cursor and cursor not in tried:
                    do_press("A", "agent", f"menu open, cursor on '{cursor}' (new) - choosing it"); return
                if any(o not in tried for o in options):
                    do_press("DOWN", "agent", f"menu open, '{cursor}' already tried - moving the cursor down"); return
                do_press("B", "agent", "menu open, every option tried here - backing out"); return
            do_press("A", "agent", "a text box is open - finishing the interaction before moving"); return
        if st.get("goto"):  # a human/Claude asked for a destination: route there over the learned world
            target = tuple(st["goto"])
            if (m, x, y) == target:
                st["goto"] = None; log(f"[arrived at {target}]", "res")
            else:
                p = WorldGraph(mem.data["maps"]).path((m, x, y), lambda n: n == target)
                if p:
                    do_press(p[0], "agent", f"goto {target}: {len(p)} steps left"); return
                st["goto"] = None; log(f"[no known route to {target}; exploring instead]", "res")
        if st.get("replay"):  # replaying a demonstration (graded afterwards, dropped if it does not work)
            btn = st["replay"].pop(0)
            do_press(btn, "agent", f"testing a {st['replay_ctx']['demo']['source']} demonstration ({len(st['replay'])} presses left)")
            if not st["replay"]:
                grade_replay()
            return
        demo = matching_demo(m, x, y, tm_now)
        if demo and st["explore_run"]:
            demo = None  # this run is an exploration run: ignore known demonstrations and try to beat them
        if demo and not st.get("replayed_here") == (m, x, y, st["step"] // 50):
            st["replay"] = list(demo["buttons"]); st["replayed_here"] = (m, x, y, st["step"] // 50)
            st["replay_ctx"] = {"demo": demo, "pos": (m, x, y), "goals": check_goals(emu, st)}
            log(f"[testing a {demo['source']} demonstration for this spot (grade {demo.get('grade', 0)}): {demo['buttons']}]", "res")
            return
        # Stall detector: same tile, same screen, no goal for 15 agent steps -> escalate instead of repeating.
        sig = (m, x, y, hash(tm_now), tuple(sorted(st["goal_steps"])))
        st["stall"] = st.get("stall", 0) + 1 if sig == st.get("last_sig") else 0
        st["last_sig"] = sig
        if st["stall"] >= 15:
            st["stall"] = 0; st["stalls"] = st.get("stalls", 0) + 1
            if st.get("replay_ctx"):
                st["replay"] = []; grade_replay()
            esc = ["B", "B", random.choice(list(DIRS)), "A", random.choice(list(DIRS))][st["stalls"] % 5]
            do_press(esc, "agent", f"STALL #{st['stalls']} detected here - escalating with {esc}"); return
        planned = plan_step({**check_goals(emu, st), "_starter": a.starter}, mem.data["maps"], (m, x, y), st["facing"])
        if planned and not (st["explore_run"] and m != 0x28 and random.random() < 0.3):  # never gamble in the lab
            do_press(planned[0], "agent", planned[1]); return
        name, why = mem.choose(m, x, y, st["facing"], tm_now, emu.read(0xD367)); do_press(name, "agent", why)

    def on_key(ev):
        if ev.keysym == "p":
            st["paused"] = not st["paused"]; log(f"[agent {'paused' if st['paused'] else 'resumed'}]", "res"); return
        if ev.keysym == "t":  # turbo: 1x -> 2x -> 4x -> 8x -> 1x (frameskip in the window; headless is always unthrottled)
            st["speed"] = {1: 2, 2: 4, 4: 8}.get(st["speed"], 1)
            root.title(f"PokeAgent explorer demo - {st['speed']}x  (t turbo, p pause, arrows/a/s/Enter/Shift steer)")
            log(f"[turbo {st['speed']}x]", "res"); return
        name = KEYS.get(ev.keysym)
        if name:
            do_press(name, "human", f"you pressed {name}")

    # --- remote control (Claude via curl now, MCP later): handlers run on this thread between frames ---
    jobs: queue.Queue = queue.Queue()

    def call(fn):
        fut: Future = Future(); jobs.put((fn, fut)); return fut.result(timeout=30)

    ctl = ControlServer(call, port=a.control_port)

    @ctl.route("GET", "/status")
    def _status():
        m, x, y = pos()
        return {"step": st["step"], "map": m, "x": x, "y": y, "facing": st["facing"], "paused": st["paused"],
                "in_battle": bool(st.get("in_battle")), "goals": check_goals(emu, st), "goal_steps": st["goal_steps"],
                "goto": st.get("goto"), "party": emu.read(0xD163), "bag_items": emu.read(0xD31D),
                "box_open": box_open(emu.read_range(TILEMAP, TILEMAP_LEN)), "maps_known": sorted(mem.data["maps"])}

    @ctl.route("GET", "/goals")
    def _goals(): return {"goals": check_goals(emu, st), "first_reached_step": st["goal_steps"]}

    @ctl.route("GET", "/screen")
    def _screen(): return {"lines": frame_lines(emu.read_range(TILEMAP, TILEMAP_LEN))}

    @ctl.route("GET", "/screenshot.png")
    def _shot(): return png_bytes(emu.screenshot())

    @ctl.route("GET", "/map")
    def _map(id=None, **_):
        mid = str(id if id is not None else pos()[0]); return {"map": mid, **mem.data["maps"].get(mid, {})}

    @ctl.route("POST", "/press")
    def _press(button="A", **_):
        if button.upper() not in Button.__members__:
            raise ValueError(f"unknown button {button!r}; use {sorted(Button.__members__)}")
        do_press(button.upper(), "claude", f"remote press {button.upper()}"); return _status()

    @ctl.route("POST", "/pause")
    def _pause(**_): st["paused"] = True; log("[agent paused by remote]", "res"); return {"paused": True}

    @ctl.route("POST", "/resume")
    def _resume(**_): st["paused"] = False; log("[agent resumed by remote]", "res"); return {"paused": False}

    @ctl.route("POST", "/goto")
    def _goto(map=None, x=None, y=None, **_):
        st["goto"] = [int(map if map is not None else pos()[0]), int(x), int(y)]
        log(f"[remote goto {st['goto']}]", "res"); return {"goto": st["goto"]}

    @ctl.route("GET", "/vision")
    def _vision(**_):
        return {"rows": battle_view(emu) if emu.read(0xD057) else ascii_vision(emu, mem, emu.read(0xD367))}

    @ctl.route("GET", "/peek")
    def _peek(addr="0xD35E", length="1", **_):
        a0, n = int(str(addr), 16) if str(addr).lower().startswith("0x") else int(addr), min(int(length), 512)
        data = emu.read_range(a0, n) if n > 1 else bytes([emu.read(a0)])
        return {"addr": f"0x{a0:04X}", "hex": data.hex(" "), "bytes": list(data)}

    @ctl.route("GET", "/sprites")
    def _sprites(**_):
        return {"player": [emu.read(0xD362), emu.read(0xD361)],
                "slots": [{"slot": i, "pic": emu.read(0xC100 + 16 * i), "c2x4": emu.read(0xC204 + 16 * i),
                           "c2x5": emu.read(0xC205 + 16 * i), "c1x4": emu.read(0xC104 + 16 * i), "c1x6": emu.read(0xC106 + 16 * i)}
                          for i in range(16) if emu.read(0xC100 + 16 * i)]}

    @ctl.route("POST", "/say")
    def _say(text="", **_): log(f"claude:   {text}", "human"); return {"ok": True}

    ctl.start()

    def frame():
        while not jobs.empty():  # remote-control jobs run here, on the emulator's thread
            fn, fut = jobs.get()
            try:
                fut.set_result(fn())
            except Exception as e:
                fut.set_exception(e)
        if st["done"]:
            root.after(100, frame)  # only job draining after the run, so /status still answers; ONE reschedule
            return
        if a.headless:
            emu.tick(1)  # no rendering at all
        else:
            if st["speed"] > 1:
                emu.tick(st["speed"] - 1)  # turbo: frameskip - run extra frames unrendered, draw one
            img = emu.screenshot().resize((480, 432), Image.NEAREST)  # screenshot renders one frame
            st["photo"] = ImageTk.PhotoImage(img); screen.configure(image=st["photo"])
        st["frame"] += 1
        if st["frame"] % 15 == 0 and not a.headless:
            try:
                m_, x_, y_ = pos(); npcs = npc_positions(emu)
                if emu.read(0xD057):
                    vis.configure(text="SEES (battle)\n" + "\n".join(battle_view(emu)))
                else:
                    vis.configure(text="SEES (10x9 tiles)\n" + "\n".join(ascii_vision(emu, mem, emu.read(0xD367)))
                                  + f"\n\nREMEMBERS map 0x{m_:02X}\n" + "\n".join(mem.render_memory(m_, x_, y_, npcs))
                                  + "\n\n@ you  N npc  W warp\ni talks  # wall  . seen")
                tm_d = emu.read_range(TILEMAP, TILEMAP_LEN)
                lines_d = frame_lines(tm_d) if box_open(tm_d) else []
                g = check_goals(emu, st)
                dlg.configure(text=("DIALOG: " + " | ".join(lines_d)[:150] if lines_d else "DIALOG: (none)")
                              + f"\nGOALS:  " + "  ".join(f"{k}{'+' if v else '-'}" for k, v in g.items())
                              + f"\nBATTLE: {'yes (0x%02X)' % emu.read(0xD057) if emu.read(0xD057) else 'no'}"
                              f"   party={emu.read(0xD163)} bag={emu.read(0xD31D)} money={read_state(emu).money}")
            except Exception as e:
                vis.configure(text=f"vision error: {e!r}")
        h = hash(emu.read_range(TILEMAP, TILEMAP_LEN))  # screen tiles only; wandering NPCs must not count as a cutscene
        st["stable_frames"] = st["stable_frames"] + 1 if h == st.get("last_hash") else 0
        st["last_hash"] = h
        try:
            if not st["paused"] and st["frame"] % a.frames_per_step == 0:
                agent_step()
        except Exception as e:  # never let one bad step freeze the window: log it and keep the loop alive
            log(f"[agent step error: {e!r}]", "res")
        finally:
            if st["done"] and a.headless:
                try:
                    shutdown(); trans.close(); emu.close(); root.destroy()
                except Exception:
                    os._exit(0)  # a swarm parent is waiting on us; never hang in mainloop
            else:
                root.after(1 if a.headless else 16, frame)

    root.bind("<Key>", on_key)
    if a.headless:
        root.withdraw()  # keep tk's event loop (it drives everything) but show no window
    log("Explorer demo. Rule-based agent learning the map; your key presses are learned too. Click the window to steer.", "hdr")
    log(f"Remote control for Claude: http://127.0.0.1:{a.control_port}/status  (press, pause, resume, goto, say)\n", "hdr")
    log(f"map memory: {a.maps} ({len(mem.data['maps'])} maps known so far); starter: {a.starter}; "
        f"{'EXPLORATION run (trying to beat the record)' if explore_run else 'exploitation run (follows what works)'}\n", "res")
    root.after(300, frame)
    root.protocol("WM_DELETE_WINDOW", lambda: (shutdown(), trans.close(), emu.close(), root.destroy()))
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
