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
import re
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
# Procedures: (button, regex the screen must show afterwards | None). START menu order at game start:
# POKeMON, ITEM, <name>, SAVE, OPTION, EXIT (POKeMON appears once you have one). READ records the screen.
PROCEDURES = {
    "check_health": [("START", r"POK.MON|ITEM"), ("A", r"\d+/\s*\d+|L\d+"), ("READ", None), ("B", None), ("B", None)],
    "open_bag": [("START", r"ITEM"), ("DOWN", r">ITEM"), ("A", r"CANCEL"), ("READ", None), ("B", None), ("B", None)],
    "save_game": [("START", r"SAVE"), ("DOWN", r">ITEM"), ("DOWN", None), ("DOWN", r">SAVE"), ("A", r"save|SAVE"),
                  ("A", r"YES|Saving|saved"), ("A", r"saved|SAVE"), ("A", None), ("B", None), ("B", None)],
    # A new discovery gets maximal exploration (Robert): the TOWN MAP is opened and read the moment we get it.
    "use_town_map": [("START", r"ITEM"), ("DOWN", r">ITEM"), ("A", r"TOWN MAP|CANCEL"), ("A", r"USE|TOSS"), ("A", None),
                     ("READ", None), ("B", None), ("B", None), ("B", None)],
}
# YES/NO boxes: the answer depends on the question that was on screen just before. First match wins; default YES.
YESNO_RULES = [("nickname", "NO"), (" name ", "NO"), ("toss", "NO"), ("deposit", "NO"), ("release", "NO"),
               ("give up", "NO"), (" run ", "NO"), ("", "YES")]  # spaced needles = whole words


STARTERS = ["BULBASAUR", "CHARMANDER", "SQUIRTLE"]


def move_value(name: str) -> float:
    """Cartridge value of a move by name (power x accuracy, status moves 0); used when learning/forgetting moves."""
    if not ROM_KB:
        return 0.0
    n = "".join(ch for ch in name.upper() if ch.isalnum())
    for mv in ROM_KB["moves"].values():
        if "".join(ch for ch in mv["name"].upper() if ch.isalnum()) == n:
            return mv["power"] * mv["accuracy"]
    return 0.0


def learn_decision(question: str, current_moves: list[str]) -> tuple[str, str, str | None]:
    """'X is trying to learn Y! ... Delete a move to make room for Y?' -> (YES/NO, why, move to forget)."""
    m = re.search(r"LEARN ([A-Z][A-Z ]+?)[!?]", question.upper())
    new = m.group(1).strip() if m else None
    if not new or not current_moves:
        return "YES", "new move: default accept", None
    worst = min(current_moves, key=move_value)
    if move_value(new) > move_value(worst):  # a status move (0) never replaces a damaging one
        return "YES", f"{new} ({move_value(new):.0f}) beats {worst} ({move_value(worst):.0f})", worst
    return "NO", f"{new} ({move_value(new):.0f}) is not better than our weakest {worst} ({move_value(worst):.0f})", None


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
_KB = Path(__file__).resolve().parents[1] / "kb" / "rom_tables.json"
ROM_KB = json.loads(_KB.read_text(encoding="utf-8")) if _KB.exists() else None  # tools/rom_tables.py drains it from the cartridge


def move_scores(emu) -> dict[str, tuple[float, str]]:
    """Knowledge-based move values for the current battle: power x type effectiveness (ROM type chart) x STAB x
    accuracy, from the cartridge's own tables; moves with 0 PP score 0. Returns {MOVE NAME: (score, reason)}."""
    if not ROM_KB:
        return {}
    chart = {(a, d): e for a, d, e in ROM_KB["type_chart"]}
    enemy_types = {ROM_KB["moves"]["1"]["type"]} if False else set()
    et1, et2 = emu.read(0xCFEA), emu.read(0xCFEB)
    names = {"NORMAL": 0, "FIGHTING": 1, "FLYING": 2, "POISON": 3, "GROUND": 4, "ROCK": 5, "BUG": 7, "GHOST": 8, "FIRE": 20,
             "WATER": 21, "GRASS": 22, "ELECTRIC": 23, "PSYCHIC": 24, "ICE": 25, "DRAGON": 26}
    inv = {v: k for k, v in names.items()}
    enemy_types = {inv.get(et1, "?"), inv.get(et2, "?")}
    my_types = {inv.get(emu.read(0xD170), "?"), inv.get(emu.read(0xD171), "?")}
    out = {}
    for slot in range(4):
        mid, pp = emu.read(0xD01C + slot), emu.read(0xD02D + slot) & 0x3F
        mv = ROM_KB["moves"].get(str(mid))
        if not mv or not mid:
            continue
        eff = 1.0
        for t in enemy_types:
            eff *= chart.get((mv["type"], t), 1.0)
        stab = 1.5 if mv["type"] in my_types else 1.0
        score = mv["power"] * eff * stab * mv["accuracy"] if pp > 0 else 0.0
        out[mv["name"]] = (score, f"pow {mv['power']} x{eff:g} type{' STAB' if stab > 1 else ''} pp {pp}")
    return out


GOALS = ["potion", "left_house", "first_pokemon", "won_battle", "to_route1", "to_viridian", "oaks_parcel", "deliver_parcel"]  # goals.json order


ITEM_NAMES = {0x01: "MASTER BALL", 0x02: "ULTRA BALL", 0x03: "GREAT BALL", 0x04: "POKE BALL", 0x05: "TOWN MAP", 0x06: "BICYCLE",
              0x0B: "ANTIDOTE", 0x0C: "BURN HEAL", 0x0D: "ICE HEAL", 0x0E: "AWAKENING", 0x0F: "PARLYZ HEAL", 0x10: "FULL RESTORE",
              0x11: "MAX POTION", 0x12: "HYPER POTION", 0x13: "SUPER POTION", 0x14: "POTION", 0x1D: "ESCAPE ROPE", 0x1E: "REPEL",
              0x46: "OAK'S PARCEL"}  # pokered item constants; only POTION (0x14) verified so far


def bag_contents(emu) -> dict[int, int]:
    n = emu.read(0xD31D)
    if not 0 < n < 21:
        return {}
    raw = emu.read_range(0xD31E, 2 * n)
    return {raw[i]: raw[i + 1] for i in range(0, len(raw), 2)}


def party_hp(emu) -> tuple[int, int]:
    """Lead pokemon HP and max HP. VERIFIED 2026-11-03: wPartyMon1HP 0xD16C/6D, wPartyMon1MaxHP 0xD18D/8E
    (read 11/20 for a level-5 Bulbasaur; wPartyMon1Level 0xD18C read 5; species at 0xD16B read 0x99)."""
    hp = (emu.read(0xD16C) << 8) | emu.read(0xD16D)
    mx = (emu.read(0xD18D) << 8) | emu.read(0xD18E)
    return hp, mx


def check_goals(emu, st: dict) -> dict[str, bool]:
    """Milestones read straight from RAM (bag 0xD31D/E verified; party 0xD163 and battle 0xD057 unverified)."""
    bag_n = emu.read(0xD31D)
    bag = emu.read_range(0xD31E, 2 * bag_n) if 0 < bag_n < 21 else b""  # PyBoy rejects empty slices
    potion = any(bag[i] == 0x14 for i in range(0, len(bag), 2))
    m = emu.read(0xD35E)
    seen = st.setdefault("seen_maps", set()); seen.add(m)
    has_parcel = 0x46 in bag_contents(emu)
    if has_parcel:
        st["had_parcel"] = True
    g = {"potion": potion, "left_house": m not in (0x25, 0x26) or st.get("goal_left_house", False),
         "first_pokemon": emu.read(0xD163) > 0, "won_battle": st.get("battles_won", 0) > 0,
         "to_route1": 0x0C in seen, "to_viridian": 0x01 in seen,
         "oaks_parcel": has_parcel or st.get("had_parcel", False),
         "deliver_parcel": st.get("had_parcel", False) and not has_parcel}
    # A goal, once achieved in this run (or already true at its start), stays achieved: using the potion in a battle
    # must not send the agent back to an empty PC (seen 2026-11-03 04:30).
    for k in g:
        if k in st.get("goal_steps", {}) or k in st.get("initial_goals", set()):
            g[k] = True
    return g


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
        self.recent_talk: set = set()  # spots talked to this run: never re-probe them (Mom loop, 2026-11-03)

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
        ddx, ddy = x1 - x0, y1 - y0
        exact = (abs(ddx) == 2 and ddy == 0 and button in ("LEFT", "RIGHT")) or (abs(ddy) == 2 and ddx == 0 and button in ("UP", "DOWN"))
        if m1 == m0 and abs(ddx) + abs(ddy) == 1 and key in self.m(m0).get("jumps", {}):
            del self.m(m0)["jumps"][key]  # a later press moved one tile: that was not a ledge (forced walk / fade)
        if m1 == m0 and exact:
            # A LEDGE JUMP (one-way): the press moved us more than one tile. Remember the jump, and that the landing
            # tile cannot go back the way we came - without this the agent looped jump/walk-around forever.
            self.m(m0).setdefault("jumps", {})[key] = [x1, y1]
            back = {"UP": "DOWN", "DOWN": "UP", "LEFT": "RIGHT", "RIGHT": "LEFT"}[button]
            bk = f"{x1},{y1},{back}"
            if bk not in blocked:
                blocked.append(bk)
            return f"LEDGE jump {button} to ({x1},{y1}) - one way"
        if (x1, y1) == (x0, y0):
            fails = self.m(m0).setdefault("fails", {})  # failures NOT required to be consecutive: alternating
            fails[key] = fails.get(key, 0) + 1          # presses at a map edge never confirmed a wall before
            if fails[key] >= 2:
                confirmed = True
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

    # --- beats: text-triggered button sequences, learned from every agent, graded, replayed when the text recurs ---
    def beat_for(self, sig: str) -> dict | None:
        b = self.data.get("beats", {}).get(sig)
        return b if b and b.get("grade", 0) >= 0 and b.get("buttons") else None

    def learn_beat(self, sig: str, buttons: list[str], progressed: bool, source: str):
        if not sig or not buttons or len(buttons) > 40:
            return
        beats = self.data.setdefault("beats", {})
        cur = beats.get(sig)
        if progressed and (cur is None or len(buttons) < len(cur["buttons"]) or cur.get("grade", 0) < 0):
            beats[sig] = {"buttons": list(buttons), "grade": 1, "replays": 0, "source": source, "seen": 1}
        elif cur:
            cur["seen"] = cur.get("seen", 0) + 1

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

    def observe_npcs(self, map_id: int, emu, step: int):
        """NPCs by hex: the sprite table (slots 1-15: picture id at 0xC1x0, map y/x+4 at 0xC2x4/5) sampled every
        press. A slot's picture id plus its first-seen tile identifies the NPC; positions accumulate, so a
        wandering NPC shows 'moves': true and a static one keeps one tile. Addresses are being verified by this
        very data: a slot that never moves across runs at a known NPC spot is a static NPC."""
        npcs = self.m(map_id).setdefault("npcs", {})
        for i in range(1, 16):
            pic = emu.read(0xC100 + 16 * i)
            if not pic:
                continue
            x, y = emu.read(0xC205 + 16 * i) - 4, emu.read(0xC204 + 16 * i) - 4
            key = f"slot{i}:pic{pic}"
            e = npcs.setdefault(key, {"pic": pic, "slot": i, "positions": {}, "first_seen": step, "text": "", "talked": 0})
            e["positions"][f"{x},{y}"] = e["positions"].get(f"{x},{y}", 0) + 1
            e["moves"] = len(e["positions"]) > 1
            e["last"] = [x, y]

    def npc_at(self, map_id: int, x: int, y: int) -> dict | None:
        for e in self.m(map_id).get("npcs", {}).values():
            if e.get("last") == [x, y]:
                return e
        return None

    def interaction_known(self, map_id, x, y, facing) -> bool:
        return f"{x},{y},{facing}" in self.m(map_id).get("interactions", {})

    # --- wild grass: where encounters happened (per tile) and which tile ids are grass (per tileset) ---
    def learn_encounter(self, map_id, x, y, tileset: int, under: list[int]):
        enc = self.m(map_id).setdefault("encounters", {})
        enc[f"{x},{y}"] = enc.get(f"{x},{y}", 0) + 1
        g = self.data.setdefault("grass_ids", {}).setdefault(str(tileset), {})
        key = ",".join(f"{b:02X}" for b in under)
        g[key] = g.get(key, 0) + 1

    def is_grass(self, tileset: int, block: list[int]) -> bool:
        return ",".join(f"{b:02X}" for b in block) in self.data.get("grass_ids", {}).get(str(tileset), {})

    def choose(self, map_id, x, y, facing: str, tilemap: bytes | None = None, tileset: int = 0,
               avoid_maps: set | None = None, grass: str = "neutral") -> tuple[str, str]:
        """grass: 'seek' (training: prefer grass ahead), 'avoid' (weak: never step into known grass), 'neutral'."""
        d = self.m(map_id); best = None
        tried = [n for n in DIRS if f"{x},{y},{n}" in d["blocked"]]
        if tilemap is not None:  # tile ids ahead already known solid (bookshelf, wall, desk) count as tried
            for n in DIRS:
                if n not in tried and self.known_solid(tileset, ahead_tiles(tilemap, n)):
                    tried.append(n)
                    # remember it as a wall edge too: the frontier search only knows 'blocked', so without this it kept
                    # sending agents to a 'frontier' tile whose open side was a known-solid tile (move/A loop at Viridian)
                    if f"{x},{y},{n}" not in d["blocked"]:
                        d["blocked"].append(f"{x},{y},{n}")
                if grass == "avoid" and n not in tried and self.is_grass(tileset, ahead_tiles(tilemap, n)):
                    tried.append(n)
        for n in list(DIRS):  # do not take a connection/warp back to a map we are deliberately done with
            w = d["warps"].get(f"{x},{y},{n}")
            if w and avoid_maps and w[0] in avoid_maps and n not in tried:
                tried.append(n)
        # Something blocks the way we face and we never talked to it: that is an interaction point candidate.
        fdx, fdy = DIRS.get(facing, (0, 0))
        npc_ahead = self.npc_at(map_id, x + fdx, y + fdy)
        if npc_ahead is not None and facing in tried and not npc_ahead.get("talked") and f"{x},{y},{facing}" not in self.recent_talk:
            return "A", f"an NPC we have not talked to is in front (pic {npc_ahead['pic']}): pressing A"
        if npc_ahead is not None:
            pass  # a person: never treated as an object to probe again, and never learned as a wall tile
        elif facing in tried and not self.interaction_known(map_id, x, y, facing) and f"{x},{y},{facing}" not in self.recent_talk:
            return "A", f"at ({x},{y}) facing {facing} is blocked and untested: pressing A to see if it talks"
        for name, (dx, dy) in DIRS.items():
            if name in tried:
                continue
            warp = d["warps"].get(f"{x},{y},{name}")
            if warp:  # a warp leads off this map: score it by how often we already took it, not by an off-map tile
                visits = d.get("warp_taken", {}).get(f"{x},{y},{name}", 1) * 3
            else:
                visits = d["visited"].get(f"{x + dx},{y + dy}", 0)
                if grass == "seek" and tilemap is not None and self.is_grass(tileset, ahead_tiles(tilemap, name)):
                    visits = -1  # training: grass first
            if best is None or visits < best[0]:
                best = (visits, name)
        if best is None:
            return "A", "every direction known blocked: pressing A to look around"
        if best[0] > 0:  # every neighbour already seen: go to the nearest FRONTIER tile instead of wandering locally
            step = self.frontier_step(map_id, x, y)
            if step:
                return step
        why = f"at ({x},{y}) blocked={tried or 'none'}; {best[1]} leads to a tile seen {best[0]}x"
        return best[1], why

    def frontier_step(self, map_id, x, y) -> tuple[str, str] | None:
        """First step of the shortest known route to a tile that still has an unexplored side (big towns need
        this: local least-visited wandering never reaches the far side of Viridian)."""
        d = self.m(map_id); visited, blocked = d["visited"], set(d["blocked"])
        def frontier(n):
            if n[0] != map_id:
                return False
            for name, (dx, dy) in DIRS.items():
                if f"{n[1]},{n[2]},{name}" not in blocked and f"{n[1] + dx},{n[2] + dy}" not in visited \
                        and f"{n[1]},{n[2]},{name}" not in d.get("warps", {}):
                    return True
            return False
        from explore_plan import WorldGraph
        g = WorldGraph(self.data["maps"]); g.strict = True
        p = g._bfs((map_id, x, y), frontier, 4000)
        if p:
            return p[0], f"frontier: {len(p)} steps to the nearest tile with an unexplored side"
        return None

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
    ap.add_argument("--frames-per-step", type=int, default=10, help="frames between agent decisions in the window (was 30: too deliberate)")
    ap.add_argument("--control-port", type=int, default=8765, help="localhost HTTP control API for Claude/MCP")
    ap.add_argument("--starter", default="any", choices=["any", "random", "bulbasaur", "charmander", "squirtle"],
                    help="which ball to take on Oak's table (random picks one per run, for the starter sweep)")
    ap.add_argument("--headless", action="store_true", help="no window: run as fast as the emulator allows (swarm learners)")
    ap.add_argument("--stop-at-goal", default=None, choices=GOALS, help="end the run when this goal lands (segment runs)")
    ap.add_argument("--box-pace", type=int, default=6,
                    help="frames between presses while a text box is open (A skips text faster); swarm agents vary it")
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
    (run_dir / "meta.json").write_text(json.dumps({"start": Path(a.state).stem if a.state else "baseline",
                                                    "stop_at_goal": a.stop_at_goal, "starter": a.starter, "seed": a.seed}))
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
        st["last_press"] = name
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
            extra["battle_flag"] = flag  # wIsInBattle 0xD057 (verified = 2 for trainer battles)
            u16 = lambda a: (emu.read(a) << 8) | emu.read(a + 1)
            bl = st.setdefault("battle_log", {"start": st["step"], "kind": flag, "turns": [],
                                              "you": [emu.read(0xD014), emu.read(0xD022)], "enemy": [emu.read(0xCFE5), emu.read(0xCFF3)]})
            if emu.read(0xCFE5):
                bl["enemy_species"] = emu.read(0xCFE5); bl["enemy"] = [emu.read(0xCFE5), emu.read(0xCFF3)]  # filled once the battle data loads
            lines_b = frame_lines(tm)
            cursor_b = next((ln.replace(">", "").strip() for ln in lines_b if ">" in ln), "")
            if name == "A" and cursor_b:  # a battle choice: what was chosen and the HP situation at that moment
                bl["turns"].append({"step": st["step"], "chose": cursor_b, "menu": [ln for ln in lines_b if ln.isupper() or ">" in ln][:6],
                                    "hp_you": u16(0xD015), "hp_enemy": u16(0xCFE6)})
            extra["battle_turn"] = len(bl["turns"])
        if name in DIRS and not box_before:
            extra["ahead_tiles"] = ahead_tiles(tm, name)  # lets the KB learn which tile ids are walls
        if name not in DIRS or box_before:
            st["last_fail"] = None  # a wall is only 'confirmed' by two consecutive identical move presses
        snap_pre = emu.read_range(*EFFECT_WINDOW) if not box_before else None
        bag_pre = bag_contents(emu)
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
            fdx, fdy = DIRS[st["facing"]]
            npc_in_front = mem.npc_at(before[0], before[1] + fdx, before[2] + fdy)
            if npc_in_front is not None:  # people move: their results belong to the NPC record, not to the tile
                npc_in_front["talked"] = npc_in_front.get("talked", 0) + 1
                if len(text) > len(npc_in_front.get("text", "")):
                    npc_in_front["text"] = text[:160]
                entry = npc_in_front.setdefault("results", {"count": 0, "text": "", "presses": [], "menus": [], "choices": []})
                entry["count"] += 1
            else:
                entry = mem.interact(before[0], before[1], before[2], st["facing"], text if box_after else "")
            mem.recent_talk.add(f"{before[1]},{before[2]},{st['facing']}")
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
        mem.observe_npcs(after[0], emu, st["step"])
        # Event/completion tracking: the story flags (wEventFlags 0xD747-0xD886, from pokered.sym) are the game's own
        # record of what has been done once. Any bit that flips is remembered with where, when and what was on screen.
        ev = emu.read_range(0xD747, 0x140)
        if st.get("events_prev") is not None and ev != st["events_prev"]:
            flips = [(i, (st["events_prev"][i], ev[i])) for i in range(len(ev)) if ev[i] != st["events_prev"][i]]
            rec = {"step": st["step"], "map": before[0], "at": [before[1], before[2]], "text": (st.get("last_text") or text)[:80],
                   "flags": [[f"0x{0xD747 + i:04X}", o, n] for i, (o, n) in flips[:8]], "run": run_dir.name}
            mem.data.setdefault("events", []).append(rec); del mem.data["events"][:-300]
            extra["event_flags"] = rec["flags"]
            log(f"*** EVENT: {len(flips)} story flag byte(s) changed at map 0x{before[0]:02X} ({before[1]},{before[2]}): {rec['flags'][:3]} ***", "res")
        st["events_prev"] = ev
        # Team checkpoint: whenever the lead pokemon's level beats the best ever, save a 'team_best' state the
        # explorer agents start from (Robert: trainer agents feed the stronger team to the map-clearing agents).
        lvl = emu.read(0xD18C)
        if lvl > st.get("best_level_seen", 0):
            st["best_level_seen"] = lvl
            best = mem.data.get("team_best_level", 0)
            side = Path("runs/checkpoints/team_best.level")
            try:  # another agent may have saved a stronger team than our copy of the memory knows about
                best = max(best, int(side.read_text())) if side.exists() else best
            except Exception:
                pass
            if lvl > best and emu.read(0xD057) == 0 and not box_after:
                try:
                    cp = Path("runs/checkpoints"); cp.mkdir(parents=True, exist_ok=True)
                    side.write_text(str(lvl))
                    tmp = cp / f"team_best.{os.getpid()}.tmp"; emu.save_state(tmp); os.replace(tmp, cp / "team_best.state")
                    mem.data["team_best_level"] = lvl; log(f"*** TEAM CHECKPOINT: level {lvl} saved as team_best.state ***", "res")
                except Exception as e:
                    log(f"[team checkpoint failed: {e!r}]", "res")
        # Training economics: experience gained per map (wPartyMon1Exp 0xD179, 3 bytes) so the trainer can pick the
        # grass with the best XP per step for its level - the 'optimized training strategy' data.
        exp_now = (emu.read(0xD179) << 16) | (emu.read(0xD17A) << 8) | emu.read(0xD17B)
        if st.get("exp_prev") is not None and exp_now > st["exp_prev"]:
            tr = mem.data.setdefault("training", {}).setdefault(str(before[0]), {"exp": 0, "steps": 0, "by_level": {}})
            tr["exp"] += exp_now - st["exp_prev"]
            lv = str(emu.read(0xD18C)); tr["by_level"][lv] = tr["by_level"].get(lv, 0) + (exp_now - st["exp_prev"])
        if st.get("exp_prev") is not None:
            mem.data.setdefault("training", {}).setdefault(str(before[0]), {"exp": 0, "steps": 0, "by_level": {}})["steps"] += 1
        st["exp_prev"] = exp_now
        bag_post = bag_contents(emu)
        if bag_post != bag_pre:  # an item was received, used, bought or sold: remember where and from what
            for item in set(bag_pre) | set(bag_post):
                delta = bag_post.get(item, 0) - bag_pre.get(item, 0)
                if delta:
                    iname = ITEM_NAMES.get(item, f"item 0x{item:02X}")
                    rec = {"item": iname, "id": item, "delta": delta, "map": before[0], "at": [before[1], before[2]],
                           "facing": st["facing"], "text": (st.get("last_text") or text)[:80], "step": st["step"], "run": run_dir.name}
                    mem.data.setdefault("items", []).append(rec); del mem.data["items"][:-200]
                    extra["item"] = rec
                    if delta > 0 and item == 0x05 and "use_town_map" not in st.get("proc_done", set()):
                        st.setdefault("proc_due", []).append("use_town_map"); st.setdefault("proc_done", set()).add("use_town_map")
                    if delta > 0:
                        st["explore_burst"] = 60  # something new: look around properly before moving on
                    log(f"*** ITEM {'RECEIVED' if delta > 0 else 'USED/LOST'}: {iname} x{abs(delta)} at map 0x{before[0]:02X} ({before[1]},{before[2]}) ***", "res")
        if name == "A" and box_after and not box_before:  # talked to whatever is in front: tie the text to the NPC there
            dx, dy = DIRS[st["facing"]]
            npc = mem.npc_at(before[0], before[1] + dx, before[2] + dy)
            if npc is not None:
                npc["talked"] += 1
                if len(text) > len(npc.get("text", "")):
                    npc["text"] = text[:160]
                result += f" [NPC pic {npc['pic']}{' (moves)' if npc.get('moves') else ''}]"
        st["box_streak"] = st["box_streak"] + 1 if box_after else 0
        # Beat capture: the presses from a box opening (keyed by its first text) to its closing, graded by progress.
        if box_after and not box_before:
            st["beat"] = {"sig": None, "buttons": [], "goals": goals_before, "pos": before, "sources": set()}
        elif st.get("beat") and box_before:
            lines_b = frame_lines(tm)
            if st["beat"]["sig"] is None and len(lines_b) >= 2:  # first line is complete once a second line exists
                st["beat"]["sig"] = lines_b[0][:60]
            if is_menu(tm):  # a beat must never carry a decision (YES/NO, menu): rules decide those, not replays
                st["beat"]["choice"] = True
            st["beat"]["buttons"].append(name); st["beat"]["sources"].add(source)
            if not box_after:
                bt = st.pop("beat"); goals_now = check_goals(emu, st)
                progressed = (any(goals_now[g] and not bt["goals"].get(g) for g in GOALS) or bool(extra.get("ram_diff"))) \
                    and not bt.get("choice")
                src = "human" if "human" in bt["sources"] else "claude" if "claude" in bt["sources"] else "agent"
                mem.learn_beat(bt["sig"], bt["buttons"], progressed, src)
                if progressed:
                    log(f"[beat learned for \"{bt['sig'][:40]}\": {len(bt['buttons'])} presses ({src})]", "res")
        trans.write(json.dumps({"step": st["step"], "from": list(before), "button": name, "to": list(after),
                                "moved": before != after, "textbox": "dialog" if box_before else "none",
                                "text": text, "facing": st["facing"], "source": source, **extra}) + "\n")
        trans.flush()  # the later process reads this file while the demo is still running
        mm = mem.m(after[0])
        goals = check_goals(emu, st)
        if goals["left_house"]:
            st["goal_left_house"] = True
        if "initial_goals" not in st:  # goals already true when the run began (segment runs start from a checkpoint)
            st["initial_goals"] = {g for g in GOALS if goals[g]}
            # A checkpoint named after a goal implies every earlier goal too (a used potion must not send a run that
            # starts in Viridian City all the way home to the PC - seen 2026-11-03 06:00).
            stem = Path(a.state).stem if a.state else ""
            if stem in GOALS:
                st["initial_goals"] |= set(GOALS[:GOALS.index(stem) + 1])
            elif stem == "team_best":
                st["initial_goals"] |= set(GOALS[:GOALS.index("to_route1") + 1])
            if st["initial_goals"]:
                log(f"[starting from {stem or 'the baseline'}: goals assumed done: {sorted(st['initial_goals'])}]", "res")
            try:  # the swarm orchestrator scores 'attempts' from this: a run cannot attempt a goal it already started past
                mp = run_dir / "meta.json"; meta = json.loads(mp.read_text()); meta["initial_goals"] = sorted(st["initial_goals"])
                mp.write_text(json.dumps(meta))
            except Exception:
                pass
        for g in GOALS:  # first time each goal is reached IN THIS RUN: remember the step and persist it
            if goals[g] and g not in st["goal_steps"] and g not in st["initial_goals"]:
                st["goal_steps"][g] = st["step"]; log(f"*** GOAL REACHED: {g} at step {st['step']} ***", "res")
                try:  # checkpoint: the swarm re-runs the NEXT segment from here (tools/swarm.py --segment)
                    cp = Path("runs/checkpoints"); cp.mkdir(parents=True, exist_ok=True)
                    tmp = cp / f"{g}.{os.getpid()}.tmp"; emu.save_state(tmp); os.replace(tmp, cp / f"{g}.state")
                except Exception as e:
                    log(f"[checkpoint save failed: {e!r}]", "res")
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
                tmp = gp.with_suffix(f".{os.getpid()}.tmp"); tmp.write_text(json.dumps(hist, indent=1))
                for _try in range(5):  # Windows: another agent may hold the file for a moment
                    try:
                        os.replace(tmp, gp); break
                    except PermissionError:
                        time.sleep(0.2)
                if a.stop_at_goal == g:  # AFTER the milestone is persisted (it used to return before recording it)
                    st["done"] = True; shutdown(); log(f"segment done: {g} at step {st['step']}", "hdr")
                    if a.headless:
                        return
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
        # Cycle breaker: positions of the last 60 presses; <= 6 unique tiles and no goal/HP/battle change = a loop the
        # planners cannot see (ledge cycles, frontier ping-pong, sign loops). Shake: ~25 random walks, then back to normal.
        pw = pos()
        hist = st.setdefault("pos_hist", [])
        hist.append(pw); del hist[:-150]
        gnow = tuple(sorted(st["goal_steps"]))
        if st.get("shake_goals_150") != gnow:  # a goal landed: restart the 150-press window (it went dead after goal 1)
            st["shake_goals_150"] = gnow; hist.clear(); hist.append(pw)
        if st.get("shake", 0) > 0:
            tm_s = emu.read_range(TILEMAP, TILEMAP_LEN)
            st["shake"] -= 1
            if box_open(tm_s):
                do_press("B", "agent", f"shake: closing a box ({st['shake']} left)"); return
            if emu.read(0xD057) == 0:
                away = random.choice(list(DIRS))
                do_press(away, "agent", f"SHAKE: breaking a loop with a random walk {away} ({st['shake']} left)"); return
        elif len(hist) >= 150 and len(set(hist[-150:])) <= 2 and emu.read(0xD057) == 0                 and tuple(sorted(st["goal_steps"])) == st.get("shake_goals_150"):
            # 150 presses on <=2 tiles with no goal progress, EVEN with boxes open: a dialog/answer cycle (A..., DOWN, A,
            # repeat) that never reaches 40 A in a row (Bulbasaur run re-asking the Charmander ball for 1700 steps).
            st["shake"] = 25; st["shakes"] = st.get("shakes", 0) + 1; hist.clear()
            log(f"[dialog cycle detected: 150 presses on <=2 tiles - shaking #{st['shakes']}]", "res")
        elif len(hist) >= 60 and len(set(hist[-60:])) <= 6 and not box_open(emu.read_range(TILEMAP, TILEMAP_LEN))                 and emu.read(0xD057) == 0 and not st.get("explore_burst"):
            st["shake"] = 25; st["shakes"] = st.get("shakes", 0) + 1; hist.clear()
            log(f"[loop detected: 60 presses on {len(set(hist)) or '<=6'} tiles - shaking #{st['shakes']}]", "res")
        # Endless-A guard (runs BEFORE any box handling): 40 presses in a row that are all A while the position has
        # not changed = a sign/looping dialog. Close the box with B, then walk away.
        pos0 = pos()
        if st.get("a_pos") != pos0 or st.get("last_press") != "A":
            st["a_streak"] = 0
        st["a_pos"] = pos0
        if st.get("last_press") == "A":
            st["a_streak"] = st.get("a_streak", 0) + 1
        if st.get("a_streak", 0) >= 40:
            tm_g = emu.read_range(TILEMAP, TILEMAP_LEN)
            if box_open(tm_g):
                do_press("B", "agent", "40 A presses at the same tile: closing the box with B"); return
            st["a_streak"] = 0; st["stalls"] = st.get("stalls", 0) + 1; st["shake"] = 25
            away = random.choice([d for d in DIRS if d != st["facing"]])
            do_press(away, "agent", f"40 A presses at ({pos0[1]},{pos0[2]}): walking away {away}, then a shake"); return
        # Input readiness: do not press while the screen is still changing on its own (cutscene, forced walk,
        # fade, battle animation) or while the game says it is ignoring the joypad (wJoyIgnore, unverified).
        joy_ignore = emu.read(0xCD6B)
        tm_ready = emu.read_range(TILEMAP, TILEMAP_LEN)
        # Only the OVERWORLD needs the stillness check (forced walks, fades, Oak dragging you to the lab).
        # Boxes and menus are paced by the game itself: pressing while text prints is harmless, and a
        # blinking cursor would otherwise look like "still changing" forever (that stalled the 23:20 run).
        busy = not box_open(tm_ready) and (st["stable_frames"] < 4 or joy_ignore)
        if busy:
            # Cutscene / forced walk / fade (Robert, 2026-11-03): do not wait for it - MASH A. A is harmless while the
            # joypad is ignored and it skips any text the moment it appears. The press is logged like any other.
            st["mash"] = st.get("mash", 0) + 1
            if st["mash"] == 1:
                log(f"[cutscene: {'joypad ignored (0x%02X)' % joy_ignore if joy_ignore else 'screen moving on its own'} - mashing A]", "res")
            do_press("A", "agent", "cutscene/forced walk: mashing A to get through it"); return
        if st.get("mash"):
            log(f"[cutscene over after {st['mash']} A presses]", "res"); st["mash"] = 0
        m, x, y = pos()
        tm_now = emu.read_range(TILEMAP, TILEMAP_LEN)
        lines_now = frame_lines(tm_now) if box_open(tm_now) else []
        in_battle = emu.read(0xD057) != 0 or any(ln.startswith("FIGHT") or "FIGHT" in ln for ln in lines_now)
        if st.get("replay") and (in_battle or box_open(tm_now)):
            st["replay"] = []; grade_replay()  # a box or a battle interrupted the demonstration: grade it now
        if in_battle:
            if not st.get("in_battle"):
                st["battles"] = st.get("battles", 0) + 1; st["battle_pos"] = (m, x, y)
                if emu.read(0xD057) == 1:  # wild: remember this tile spawns pokemon, and what tile ids grass has
                    under = [tm_now[8 * 20 + 8], tm_now[8 * 20 + 9], tm_now[9 * 20 + 8], tm_now[9 * 20 + 9]]
                    mem.learn_encounter(m, x, y, emu.read(0xD367), under)
                    log(f"[wild encounter at ({x},{y}): grass tile learned]", "res")
            st["in_battle"] = True
            st["box_streak"] = 0
            kind = emu.read(0xD057)
            hp, mx = party_hp(emu)
            weak = mx > 0 and hp / mx < 0.4
            run_line = next((ln for ln in lines_now if "RUN" in ln), None)
            # --- learn the opponent's damage: HP drop since our last battle decision, per enemy species ---
            species = emu.read(0xCFE5)
            my_sp, my_lvl, e_lvl = emu.read(0xD16B), emu.read(0xD18C), emu.read(0xCFF3)
            if st.get("last_battle_hp") is not None and hp < st["last_battle_hp"]:
                taken = st["last_battle_hp"] - hp
                dmg = mem.data.setdefault("enemy_damage", {}).setdefault(str(species), [])
                dmg.append(taken); del dmg[:-20]
                # Full-context record (Robert): which enemy move, at which levels, did how much to which of ours.
                m_used = re.search(r"used ([A-Z][A-Z ]+?)!", " ".join(st.get("dialog", [])[-3:]))
                emove = m_used.group(1).strip() if m_used else "?"
                key = f"{species}L{e_lvl}:{emove}->{my_sp}L{my_lvl}"
                rec = mem.data.setdefault("damage_taken", {}).setdefault(key, [])
                rec.append(taken); del rec[:-20]
            st["last_battle_hp"] = hp
            expected = max(mem.data.get("enemy_damage", {}).get(str(species), [0]) or [0])
            # --- potion timing: use one when the next expected hit could take us below ~1 hit of safety and the heal
            #     is not wasted (POTION restores 20 HP in Gen 1; the observed heal is learned into item_heal) ---
            heal = max(mem.data.get("item_heal", {}).get("20", [20]) or [20])
            has_potion = bag_contents(emu).get(0x14, 0) > 0
            want_potion = has_potion and mx and hp <= max(expected * 2, 6) and (mx - hp) >= min(heal, 12) and kind != 0
            cur = next((ln for ln in lines_now if ">" in ln), "")
            if want_potion and (run_line is not None or any("POTION" in ln for ln in lines_now) or "which" in " ".join(lines_now).lower()):
                st["potion_hp_before"] = hp
                if any("POTION" in ln and ">" in ln for ln in lines_now):
                    do_press("A", "agent", f"BATTLE HP {hp}/{mx}, enemy hits up to {expected}: using POTION (+{heal})"); return
                if any("POTION" in ln for ln in lines_now):
                    do_press("DOWN", "agent", "item list: moving to POTION"); return
                if ">ITEM" in cur:
                    do_press("A", "agent", f"BATTLE HP {hp}/{mx}: opening ITEM for a POTION"); return
                if "FIGHT" in cur or "PKMN" in cur:
                    do_press("DOWN", "agent", "battle menu: down to ITEM"); return
                if "RUN" in cur:
                    do_press("LEFT", "agent", "battle menu: left to ITEM"); return
                do_press("A", "agent", "item use: confirming"); return
            if st.get("potion_hp_before") is not None and hp > st["potion_hp_before"]:
                mem.data.setdefault("item_heal", {}).setdefault("20", []).append(hp - st["potion_hp_before"])
                log(f"[POTION healed {hp - st['potion_hp_before']} HP: learned]", "res"); st["potion_hp_before"] = None
            if kind == 1 and weak and run_line is not None:  # wild battle and too weak: flee
                if ">RUN" in run_line:
                    do_press("A", "agent", f"BATTLE wild, HP {hp}/{mx}: RUN"); return
                cur = next((ln for ln in lines_now if ">" in ln), "")
                if "FIGHT" in cur or "PKMN" in cur:
                    do_press("DOWN", "agent", f"BATTLE wild, HP {hp}/{mx}: moving the cursor down toward RUN"); return
                if "ITEM" in cur:
                    do_press("RIGHT", "agent", f"BATTLE wild, HP {hp}/{mx}: moving the cursor right to RUN"); return
            # --- catching: a wild species we do not own yet, with a POKe BALL in the bag -> weaken to <=35% HP, then
            #     ITEM -> POKe BALL. Attempts and results (per species, level, HP%) are recorded to learn catch odds.
            balls = bag_contents(emu).get(0x04, 0)
            dex_no = int((ROM_KB or {}).get("dex_of_internal", {}).get(str(species), 0) or 0)
            owned = bool(dex_no) and bool(emu.read(0xD2F7 + (dex_no - 1) // 8) >> ((dex_no - 1) % 8) & 1)
            e_hp, e_max = ((emu.read(0xCFE6) << 8) | emu.read(0xCFE7)), ((emu.read(0xCFF4) << 8) | emu.read(0xCFF5))
            if kind == 1 and balls and dex_no and not owned and e_max:
                ratio = e_hp / e_max
                if ratio <= 0.35 and (run_line is not None or any("BALL" in ln for ln in lines_now)):
                    st["catch_attempt"] = {"species": species, "level": e_lvl, "hp_pct": round(ratio, 2), "step": st["step"], "dex": dex_no}
                    cur_c = next((ln for ln in lines_now if ">" in ln), "")
                    if any("BALL" in ln and ">" in ln for ln in lines_now):
                        do_press("A", "agent", f"CATCH {ROM_KB['name_of_internal'].get(str(species), species)} at {ratio:.0%} HP: throwing a POKe BALL"); return
                    if any("BALL" in ln for ln in lines_now):
                        do_press("DOWN", "agent", "item list: moving to POKe BALL"); return
                    if ">ITEM" in cur_c:
                        do_press("A", "agent", "opening ITEM for a POKe BALL"); return
                    if "FIGHT" in cur_c or "PKMN" in cur_c:
                        do_press("DOWN", "agent", "battle menu: down to ITEM (catching)"); return
                    if "RUN" in cur_c:
                        do_press("LEFT", "agent", "battle menu: left to ITEM (catching)"); return
                st["catch_mode"] = True  # weaken, do not KO: the move chooser picks the WEAKEST damaging move
            else:
                st["catch_mode"] = False
            # --- move choice with memory: damage dealt per (enemy species, move) is learned from the enemy HP drop
            #     after our move; untried moves are tried first (variety), then the best average; 0-PP moves skipped ---
            enemy_hp = (emu.read(0xCFE6) << 8) | emu.read(0xCFE7)
            pm = st.get("pending_move")
            if pm and pm["species"] == species and enemy_hp < pm["enemy_hp"]:
                dealt = pm["enemy_hp"] - enemy_hp
                stats = mem.data.setdefault("move_damage", {}).setdefault(f"{species}:{pm['move']}", [])
                stats.append(dealt); del stats[:-20]; st["pending_move"] = None
                key = f"{my_sp}L{my_lvl}:{pm['move']}->{species}L{e_lvl}"  # our move, our level, their species and level
                rec = mem.data.setdefault("damage_dealt", {}).setdefault(key, [])
                rec.append(dealt); del rec[:-20]
            # The move menu reads: TYPE/ | NORMAL | 29/30 | TACKLE | >TAIL WHIP  -> moves are the lines AFTER the PP line
            pp_idx = next((i for i, ln in enumerate(lines_now) if re.fullmatch(r"\d+/\d+", ln.replace(">", "").strip())), None)
            move_lines = [ln for ln in lines_now[pp_idx + 1:] if ln.replace(">", "").strip() not in ("", "-")] if pp_idx is not None else []
            cursor_mv = next((ln.replace(">", "").strip() for ln in move_lines if ">" in ln), None)
            if cursor_mv and 1 <= len(move_lines) <= 4:  # the move menu
                moves = [ln.replace(">", "").strip() for ln in move_lines]
                def score(mv):
                    d = mem.data.get("move_damage", {}).get(f"{species}:{mv}")
                    return (0, 0) if not d else (1, sum(d) / len(d))
                tried = [mv for mv in moves if score(mv)[0]]
                ks = move_scores(emu)  # cartridge knowledge: power x type chart x STAB x accuracy, 0 when out of PP
                norm0 = lambda s: "".join(ch for ch in s.upper() if ch.isalnum())
                known = {norm0(k): v for k, v in ks.items()}
                if known and any(known.get(norm0(mv), (0, ""))[0] > 0 for mv in moves):
                    # Willing to try: a damaging move never used against this species gets one trial (x1.3 bonus)
                    def kscore(mv):
                        base = known.get(norm0(mv), (0, ""))[0]
                        return base * (1.3 if base > 0 and mv not in tried else 1.0)
                    if st.get("catch_mode"):  # weaken without a KO: the weakest move that still does damage
                        target = min((mv for mv in moves if kscore(mv) > 0), key=kscore)
                        st["move_reason"] = "weakest hit, catching"
                    else:
                        target = max(moves, key=lambda mv: (kscore(mv), score(mv)[1]))
                        st["move_reason"] = known.get(norm0(target), (0, ""))[1] + ("" if target in tried else " first try")
                else:  # no knowledge (or all out of PP): variety first, then the best observed damage
                    target = next((mv for mv in moves if mv not in tried), None) or max(moves, key=lambda mv: score(mv)[1])
                    st["move_reason"] = "untried" if target not in tried else f"best avg {score(target)[1]:.1f} dmg"
                norm = lambda s: "".join(ch for ch in s.upper() if ch.isalnum())
                st["move_nav"] = st.get("move_nav", 0) + 1
                if norm(cursor_mv) == norm(target) or st["move_nav"] > 5:  # never bounce: after 5 moves take what is under the cursor
                    chosen = cursor_mv if st["move_nav"] > 5 else target
                    st["move_nav"] = 0
                    st["pending_move"] = {"species": species, "move": chosen, "enemy_hp": enemy_hp}
                    ename = (ROM_KB or {}).get("name_of_internal", {}).get(str(species), f"#{species}")
                    do_press("A", "agent", f"BATTLE vs {ename} L{emu.read(0xCFF3)}: {chosen} ({st.get('move_reason', '')})"); return
                do_press("DOWN", "agent", f"move menu: cursor to {target} (now on {cursor_mv})"); return
            if ">ITEM" in cur and not want_potion:  # never open ITEM without a reason (a bare CANCEL list stalls)
                do_press("UP", "agent", "battle menu: back up to FIGHT"); return
            if any("CANCEL" in ln and ">" in ln for ln in lines_now):
                do_press("A", "agent", "battle: closing an empty list"); return
            do_press("A", "agent", f"BATTLE kind=0x{kind:02X} HP {hp}/{mx}: FIGHT"); return
        if st.get("in_battle"):
            st["in_battle"] = False; st["last_battle_hp"] = None; st["potion_hp_before"] = None
            ca = st.pop("catch_attempt", None)
            if ca:  # resolved at the END of the battle, against the species we threw at (not the next enemy)
                dn = ca.get("dex") or 0
                caught = bool(dn) and bool(emu.read(0xD2F7 + (dn - 1) // 8) >> ((dn - 1) % 8) & 1)
                mem.data.setdefault("catches", []).append({**{k: v for k, v in ca.items() if k != "dex"}, "caught": caught}); del mem.data["catches"][:-100]
                log(f"[catch attempt {'SUCCEEDED' if caught else 'failed'} vs #{ca['species']} L{ca['level']} at {ca['hp_pct']:.0%}]", "res")
            # Won = still standing where the battle happened with a Pokemon in the party; a loss warps you home.
            won = emu.read(0xD163) > 0 and (m, x, y) == st.get("battle_pos")  # a blackout warps you away
            st["battles_won"] = st.get("battles_won", 0) + (1 if won else 0)
            log(f"[battle over - {'WON' if won else 'lost?'}; {st['battles']} battles this run]", "res")
            bl = st.pop("battle_log", None)
            if bl:  # one record per battle: who, choices per turn with HP, result - the data for battle strategy
                hp_end, mx_end = party_hp(emu)
                bl.update({"end": st["step"], "won": won, "run": run_dir.name, "map": m, "presses": st["step"] - bl["start"],
                           "hp_end": [hp_end, mx_end], "fled": not won and hp_end > 0})
                with Path("runs/battles.jsonl").open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(bl) + "\n")
                # Every battle is a lesson: per enemy species keep fights/wins/fled, HP lost, turns, and the move that
                # actually did the most damage. The planner reads these to pick fights and set the flee threshold.
                sp = str(bl.get("enemy_species") or emu.read(0xCFE5))
                ls = mem.data.setdefault("battle_lessons", {}).setdefault(sp, {"fights": 0, "wins": 0, "fled": 0, "turns": [], "hp_lost": []})
                ls["fights"] += 1; ls["wins"] += int(won); ls["fled"] += int(bl["fled"])
                ls["turns"].append(len(bl["turns"])); del ls["turns"][:-20]
                first = bl["turns"][0]["hp_you"] if bl["turns"] else hp_end
                ls["hp_lost"].append(max(0, first - hp_end)); del ls["hp_lost"][:-20]
                dmg = {k.split(":")[1]: round(sum(v) / len(v), 1) for k, v in mem.data.get("move_damage", {}).items() if k.startswith(sp + ":") and v}
                if dmg:
                    ls["best_move"] = max(dmg, key=dmg.get); ls["move_avg_damage"] = dmg
                ename = (ROM_KB or {}).get("name_of_internal", {}).get(sp, f"#{sp}")
                log(f"[lesson vs {ename}: {ls['wins']}/{ls['fights']} won, fled {ls['fled']}, avg turns {sum(ls['turns']) / len(ls['turns']):.1f}, "
                    f"avg HP lost {sum(ls['hp_lost']) / len(ls['hp_lost']):.1f}, best move {ls.get('best_move', '?')}]", "res")
        if box_open(tm_now):
            if any("A B C D E" in ln for ln in lines_now):  # the naming KEYBOARD: START = END (B only deletes letters)
                if st.get("replay_ctx"):
                    st["replay"] = []; rp = st["replay_ctx"]; rp["demo"]["grade"] = -1; st.pop("replay_ctx", None)
                    log("[the replayed beat led into the keyboard: graded BAD]", "res")
                do_press("START", "agent", "naming keyboard open: START ends it (default name)"); return
            # Text-triggered beat: a known good sequence for this box text runs automatically (and gets graded).
            sig = lines_now[0][:60] if len(lines_now) >= 2 else None
            beat = mem.beat_for(sig) if sig else None
            if is_menu(tm_now) and st.get("replay"):  # a menu/YES-NO appeared mid-replay: stop, let the rules decide
                st["replay"] = []; st.pop("replay_ctx", None)
            if beat and not st.get("replay") and not is_menu(tm_now) and st.get("beat_sig_done") != sig and not st["explore_run"]:
                st["replay"] = list(beat["buttons"]); st["beat_sig_done"] = sig
                st["replay_ctx"] = {"demo": beat, "pos": (m, x, y), "goals": check_goals(emu, st)}
                log(f"[recognised \"{sig[:40]}\": running the known {len(beat['buttons'])}-press beat (grade {beat['grade']})]", "res")
                btn = st["replay"].pop(0); do_press(btn, "agent", "beat replay")
                if not st["replay"]:
                    grade_replay()
                return
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
                    ql = question.lower()
                    if "abandon" in ql:
                        ans, why, forget = "YES", "abandon learning: only when we chose not to forget a move", None
                        st["forget_move"] = None
                    elif "learn" in context.lower() and ("make room" in ql or "delete" in ql):
                        cur_moves = [ROM_KB["moves"].get(str(emu.read(0xD173 + i)), {}).get("name", "?") for i in range(4) if emu.read(0xD173 + i)] if ROM_KB else []
                        ans, why, forget = learn_decision(context, cur_moves)
                        st["forget_move"] = forget
                    else:
                        ans, why = yesno_answer(context, a.starter)
                    st["yesno"] = {"question": question[:80], "answer": ans}
                    if cursor.endswith(ans):
                        do_press("A", "agent", f"YES/NO box: answering {ans} ({why}) to \"{question[:50]}\""); return
                    do_press("DOWN" if ans == "NO" else "UP", "agent", f"YES/NO box: moving the cursor to {ans} ({why})"); return
                if st.get("forget_move"):  # the 'which move to forget' list: pick the weakest by cartridge value
                    normf = lambda s: "".join(ch for ch in s.upper() if ch.isalnum())
                    if normf(cursor) == normf(st["forget_move"]):
                        fm = st.pop("forget_move"); do_press("A", "agent", f"forgetting {fm} for the new move"); return
                    if any(normf(o) == normf(st["forget_move"]) for o in options):
                        do_press("DOWN", "agent", f"move list: cursor to {st['forget_move']}"); return
                goals_now = check_goals(emu, st)
                want = goal_menu_choice(goals_now, options)
                if not want and goals_now.get("potion") and any("WITHDRAW" in o or "DEPOSIT" in o for o in options):
                    do_press("B", "agent", "potion already in the bag: nothing else to do at the PC, backing out"); return
                if want:  # a goal tells us which option to take here
                    if cursor == want:
                        do_press("A", "agent", f"goal menu choice: '{want}'"); return
                    do_press("DOWN", "agent", f"goal menu choice: moving the cursor toward '{want}'"); return
                tried = (inter or {}).get("entry", {}).get("choices", []) + (inter or {}).get("choices", [])
                if any(cursor.endswith(w) for w in ("CANCEL", "LOG OFF", "EXIT", "QUIT")):
                    # Exits are always a fine choice once nothing here is wanted (seen 2026-11-03: the agent sat on
                    # 'CANCEL' pressing DOWN because CANCEL counted as 'already tried').
                    do_press("A", "agent", f"menu: cursor on '{cursor}' - leaving this menu"); return
                if cursor and cursor not in tried:
                    do_press("A", "agent", f"menu open, cursor on '{cursor}' (new) - choosing it"); return
                if any(o not in tried for o in options):
                    do_press("DOWN", "agent", f"menu open, '{cursor}' already tried - moving the cursor down"); return
                do_press("B", "agent", "menu open, every option tried here - backing out"); return
            do_press("A", "agent", "a text box is open - finishing the interaction before moving"); return
        # Procedures (Robert): named button sequences for menu tasks - check health, open the bag, save - each step
        # verified against the screen text it should produce; a step that does not register is retried slower, and the
        # pace that works is remembered per procedure (maps.json procedures), so they become consistent over runs.
        proc = st.get("proc")
        if proc is None and st.get("proc_due") and not box_open(tm_now) and emu.read(0xD057) == 0:
            name = st["proc_due"].pop(0)
            if name in PROCEDURES:
                rec = mem.data.setdefault("procedures", {}).setdefault(name, {"ok": 0, "fail": 0, "pace": a.box_pace or 12})
                st["proc"] = proc = {"name": name, "steps": list(PROCEDURES[name]), "i": 0, "retries": 0, "pace": rec["pace"], "wait": 0}
                log(f"[procedure {name}: start, pace {proc['pace']} frames]", "res")
        if proc:
            if proc["wait"] > 0:
                proc["wait"] -= a.frames_per_step; return  # pacing between steps (the per-procedure learned pace)
            if proc["i"] >= len(proc["steps"]):
                rec = mem.data["procedures"][proc["name"]]; rec["ok"] += 1; rec["pace"] = proc["pace"]
                log(f"[procedure {proc['name']}: done in {len(proc['steps'])} steps at pace {proc['pace']} ({rec['ok']} ok / {rec['fail']} fail)]", "res")
                st["proc"] = None; return
            btn, expect = proc["steps"][proc["i"]]
            if btn == "READ":
                lines = frame_lines(emu.read_range(TILEMAP, TILEMAP_LEN))
                mem.data.setdefault("menus", {})[proc["name"]] = lines[:10]
                hp_r, mx_r = party_hp(emu)
                log(f"[procedure {proc['name']}: screen reads {' | '.join(lines[:4])[:90]} (RAM HP {hp_r}/{mx_r}, bag {bag_contents(emu)})]", "res")
                proc["i"] += 1; return
            if expect and proc.get("checking"):  # did the previous press produce what we expected?
                lines = frame_lines(emu.read_range(TILEMAP, TILEMAP_LEN))
                if any(re.search(expect, ln) for ln in lines):
                    proc["checking"] = False; proc["i"] += 1; proc["wait"] = proc["pace"]; return
                proc["retries"] += 1
                if proc["retries"] > 3:
                    rec = mem.data["procedures"][proc["name"]]; rec["fail"] += 1
                    log(f"[procedure {proc['name']}: step {proc['i']} ({btn}) never showed /{expect}/ - abandoning, pace raised]", "res")
                    rec["pace"] = min(60, proc["pace"] * 2); st["proc"] = None
                    do_press("B", "agent", "procedure failed: backing out"); return
                proc["pace"] = min(60, proc["pace"] * 2); proc["wait"] = proc["pace"]
                do_press(btn, "agent", f"procedure {proc['name']}: retry {btn} slower (pace {proc['pace']})"); return
            do_press(btn, "agent", f"procedure {proc['name']}: step {proc['i'] + 1}/{len(proc['steps'])} {btn}")
            if expect:
                proc["checking"] = True; proc["wait"] = proc["pace"]
            else:
                proc["i"] += 1; proc["wait"] = proc["pace"]
            return
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
        sig = (m, x, y, tuple(sorted(st["goal_steps"])))  # NOT the screen hash: printing text changes it every press
        st["stall"] = st.get("stall", 0) + 1 if sig == st.get("last_sig") else 0
        st["last_sig"] = sig
        if st["stall"] >= 15:
            st["stall"] = 0; st["stalls"] = st.get("stalls", 0) + 1
            if st.get("replay_ctx"):
                st["replay"] = []; grade_replay()
            esc = ["B", "START", random.choice(list(DIRS)), "A", "B", random.choice(list(DIRS))][st["stalls"] % 6]
            do_press(esc, "agent", f"STALL #{st['stalls']} detected here - escalating with {esc}"); return
        hp_now, mx_now = party_hp(emu)
        # Mom-heal loop guard: if we talked to her and HP did not rise, stop going back for a while.
        if st.get("mom_talk_step") and st["step"] - st["mom_talk_step"] > 6:
            if hp_now <= st.get("mom_talk_hp", 0) and mx_now and hp_now / mx_now < 0.4:
                st["mom_failed_until"] = st["step"] + 150
                log(f"[Mom did not heal us (HP {hp_now}/{mx_now}); not retrying for 150 steps]", "res")
            else:
                log(f"[healed at Mom: HP {hp_now}/{mx_now}]", "res")
                st.setdefault("proc_due", []).extend(n for n in ("check_health", "open_bag", "save_game") if n not in st.get("proc_done", set()))
                st.setdefault("proc_done", set()).update({"check_health", "open_bag", "save_game"})
            st["mom_talk_step"] = None
        goals_now_all = check_goals(emu, st)
        if "known_maps_at_start" not in st:
            st["known_maps_at_start"] = {int(k) for k in mem.data["maps"] if len(mem.data["maps"][k].get("visited", {})) >= 5}
        if m not in st.setdefault("burst_maps", set()):  # a map NEW TO MEMORY: maximal exploration before plans resume
            st["burst_maps"].add(m)
            if m not in st["known_maps_at_start"]:
                st["explore_burst"] = max(st.get("explore_burst", 0), 120)
                log(f"[new map 0x{m:02X}: exploration burst, 120 steps before plans resume]", "res")
        if st.get("explore_burst", 0) > 0 and not (mx_now and hp_now / mx_now < 0.4):
            st["explore_burst"] -= 1
            name, why = mem.choose(m, x, y, st["facing"], tm_now, emu.read(0xD367), grass="neutral")
            do_press(name, "agent", f"exploring a new discovery ({st['explore_burst']} left): {why}"); return
        planned = plan_step({**goals_now_all, "_starter": a.starter, "_hp": (hp_now, mx_now),
                             "_level": emu.read(0xD18C), "_mom_failed": st.get("mom_failed_until", 0) > st["step"]},
                            mem.data["maps"], (m, x, y), st["facing"])
        if planned and "at Mom, talking" in planned[1]:
            st["mom_talk_step"] = st["step"]; st["mom_talk_hp"] = hp_now
            st["slow_until"] = st["step"] + 12  # healing has a fade: slow down so completion is recognised
        if planned and not (st["explore_run"] and m != 0x28 and random.random() < 0.3):  # never gamble in the lab
            do_press(planned[0], "agent", planned[1]); return
        weak = mx_now and hp_now / mx_now < 0.4
        training = goals_now_all.get("won_battle") and goals_now_all.get("to_route1") and 0 < emu.read(0xD18C) < 8 and not weak
        name, why = mem.choose(m, x, y, st["facing"], tm_now, emu.read(0xD367),
                               avoid_maps={0x00} if (training and m == 0x0C) else None,
                               grass="seek" if training else "avoid" if weak else "neutral")
        do_press(name, "agent", why)

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
                "goto": st.get("goto"), "party": emu.read(0xD163), "bag_items": emu.read(0xD31D), "hp": party_hp(emu),
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

    try:
        ctl.start()
    except OSError as e:  # port taken (another agent): run without the API rather than crash
        log(f"[control API unavailable: {e}]", "res")

    def frame():
        while not jobs.empty():  # remote-control jobs run here, on the emulator's thread
            fn, fut = jobs.get()
            try:
                fut.set_result(fn())
            except Exception as e:
                fut.set_exception(e)
        if st["done"]:
            if a.headless:  # a finished headless agent must EXIT (swarm rounds wait on it)
                try:
                    shutdown(); trans.close(); emu.close(); root.destroy()
                except Exception:
                    pass
                os._exit(0)
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
        tm_f = emu.read_range(TILEMAP, TILEMAP_LEN)
        st["box_open_now"] = box_open(tm_f)
        h = hash(tm_f)  # screen tiles only; wandering NPCs must not count as a cutscene
        st["stable_frames"] = st["stable_frames"] + 1 if h == st.get("last_hash") else 0
        st["last_hash"] = h
        try:
            pace = a.box_pace if (a.box_pace and st.get("box_open_now")) else a.frames_per_step
            if st.get("slow_until", 0) > st["step"]:
                pace = max(pace, 40)  # some tasks need a slower hand (Mom's heal, fades): per-task speed
            if not st["paused"] and st["frame"] % pace == 0:
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
