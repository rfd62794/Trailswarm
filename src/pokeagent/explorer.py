"""The rule-based explorer policy, ported from tools/explore_demo.py.

The demo's policy lives inside its tkinter loop, so the framework keeps this
self-contained port: same ``runs/maps.json`` schema (the framework and the
demo share that file), same rule order - advance dialog, explore menus, FIGHT
in battle, otherwise walk toward the least-visited tile that is not known
blocked - and the same blocked/warp learning with the two-strike confirm.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from pokeagent.emulator import Button, Emulator
from pokeagent.ram import read_state
from pokeagent.screencontext import classify_screen
from pokeagent.screentext import CHARMAP

TILEMAP_ADDR, TILEMAP_LEN, BORDER_TL = 0xC3A0, 360, 0x79
BATTLE_FLAG = 0xD057  # wIsInBattle (unverified)
DIRS = {"UP": (0, -1), "DOWN": (0, 1), "LEFT": (-1, 0), "RIGHT": (1, 0)}


def box_open(tilemap: bytes) -> bool:
    """A frame is open when a top-left corner tile is followed by a top-edge tile."""
    return tilemap.find(bytes([BORDER_TL, 0x7A])) >= 0


def is_menu(tilemap: bytes) -> bool:
    return 0xED in tilemap  # the menu cursor tile (verified)


def frame_lines(tilemap: bytes) -> list[str]:
    """Readable text lines inside an open frame; '>' marks the menu cursor."""
    out = []
    for r in range(18):
        row = tilemap[r * 20 : (r + 1) * 20]
        if row.count(0x7C) < 2:  # both frame edges present
            continue
        inner = row[row.index(0x7C) + 1 : len(row) - row[::-1].index(0x7C) - 1]
        line = "".join(
            ch if ch.isprintable() else " "
            for ch in (CHARMAP.get(b, " ") or " " for b in inner)
        ).strip()
        if any(ch.isalnum() for ch in line):
            out.append(" ".join(line.split()))
    return out


class MapMemory:
    """Per-map memory in the demo's runs/maps.json schema."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.data = json.loads(self.path.read_text()) if self.path.exists() else {"maps": {}}

    def m(self, map_id: int) -> dict:
        return self.data["maps"].setdefault(
            str(map_id), {"visited": {}, "blocked": [], "warps": {}, "last_seen": 0}
        )

    def visit(self, map_id: int, x: int, y: int, step: int) -> None:
        d = self.m(map_id)
        d["visited"][f"{x},{y}"] = d["visited"].get(f"{x},{y}", 0) + 1
        d["last_seen"] = step

    def learn(self, before: tuple, button: str, after: tuple, *, confirmed: bool) -> str:
        """Record what a press did; a failed move is 'blocked' only when confirmed."""
        (m0, x0, y0), (m1, x1, y1) = before, after
        if button not in DIRS:
            return "pressed"
        key = f"{x0},{y0},{button}"
        blocked = self.m(m0)["blocked"]
        if (m1, x1, y1) != (m0, x0, y0):
            paths = self.m(m0).setdefault("paths", {})
            edge = paths.setdefault(key, {"to": [m1, x1, y1], "count": 0})
            edge["to"] = [m1, x1, y1]
            edge["count"] += 1
        if m1 != m0:
            w = self.m(m0)["warps"]
            taken = self.m(m0).setdefault("warp_taken", {})
            taken[key] = taken.get(key, 0) + 1
            w[key] = [m1, x1, y1]
            return f"WARP to map 0x{m1:02X} ({x1},{y1}) - taken {taken[key]}x"
        if (x1, y1) == (x0, y0):
            if not confirmed:
                return "no move (turned? fading?) - will retry once before calling it blocked"
            if key not in blocked:
                blocked.append(key)
            return "blocked (confirmed)"
        if key in blocked:
            blocked.remove(key)  # it was a false 'blocked' (learned during a fade)
            return "moved - cleared a false wall"
        return "moved"

    def interact(self, map_id: int, x: int, y: int, facing: str, text: str, *,
                 screen: str | None = None, menu: str | None = None,
                 outcome: str | None = None, transition: list | None = None,
                 npc: dict | None = None) -> dict:
        d = self.m(map_id).setdefault("interactions", {})
        e = d.setdefault(
            f"{x},{y},{facing}",
            {"count": 0, "text": "", "presses": [], "menus": [], "choices": [],
             "outcomes": {}, "screens": {}, "transitions": []},
        )
        e["count"] += 1
        if text and not e["text"]:
            e["text"] = text[:160]
        if outcome:
            e.setdefault("outcomes", {})[outcome] = e.setdefault("outcomes", {}).get(outcome, 0) + 1
        if screen:
            e.setdefault("screens", {})[screen] = e.setdefault("screens", {}).get(screen, 0) + 1
        if menu and menu != "UNKNOWN" and menu not in e.setdefault("menus", []):
            e["menus"].append(menu)
        if transition and transition not in e.setdefault("transitions", []):
            e["transitions"].append(transition)
        if npc:
            e["npc"] = {"pic": npc.get("pic"), "slot": npc.get("slot"), "last": npc.get("last")}
        return e

    def observe_npcs(self, map_id: int, emu: Emulator, step: int) -> None:
        npcs = self.m(map_id).setdefault("npcs", {})
        for slot in range(1, 16):
            pic = emu.read(0xC100 + 16 * slot)
            if not pic:
                continue
            x, y = emu.read(0xC205 + 16 * slot) - 4, emu.read(0xC204 + 16 * slot) - 4
            key = f"slot{slot}:pic{pic}"
            e = npcs.setdefault(key, {"pic": pic, "slot": slot, "positions": {},
                                      "first_seen": step, "text": "", "talked": 0})
            e["positions"][f"{x},{y}"] = e["positions"].get(f"{x},{y}", 0) + 1
            e["moves"] = len(e["positions"]) > 1
            e["last"] = [x, y]

    def npc_at(self, map_id: int, x: int, y: int) -> dict | None:
        for entry in self.m(map_id).get("npcs", {}).values():
            if entry.get("last") == [x, y]:
                return entry
        return None

    def interaction_known(self, map_id: int, x: int, y: int, facing: str) -> bool:
        return f"{x},{y},{facing}" in self.m(map_id).get("interactions", {})

    def choose(self, map_id: int, x: int, y: int, facing: str) -> tuple[str, str]:
        d = self.m(map_id)
        best = None
        tried = [n for n in DIRS if f"{x},{y},{n}" in d["blocked"]]
        if facing in tried and not self.interaction_known(map_id, x, y, facing):
            return "A", f"at ({x},{y}) facing {facing} is blocked and untested: pressing A"
        for name, (dx, dy) in DIRS.items():
            if name in tried:
                continue
            warp = d["warps"].get(f"{x},{y},{name}")
            if warp:
                visits = d.get("warp_taken", {}).get(f"{x},{y},{name}", 1) * 3
            else:
                visits = d["visited"].get(f"{x + dx},{y + dy}", 0)
            if best is None or visits < best[0]:
                best = (visits, name)
        if best is None:
            return "A", "every direction known blocked: pressing A to look around"
        why = f"at ({x},{y}) blocked={tried or 'none'}; {best[1]} leads to a tile seen {best[0]}x"
        return best[1], why

    def save(self) -> None:
        self.data["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")  # atomic replace
        tmp.write_text(json.dumps(self.data, indent=1))
        os.replace(tmp, self.path)


class Explorer:
    """Runs the demo's rule-based policy one press at a time on any Emulator."""

    def __init__(self, maps_path: Path | str = Path("runs/maps.json")) -> None:
        self.mem = MapMemory(maps_path)
        self.facing = "DOWN"
        self.box_streak = 0
        self.last_fail: tuple | None = None
        self.menu_tried: dict[tuple, set[str]] = {}
        self.step_count = 0

    def step(self, emu: Emulator) -> dict:
        """One explorer press: returns {button, why, result, pos}."""
        s = read_state(emu)
        before = (s.map_id, s.x, s.y)
        tm = emu.read_range(TILEMAP_ADDR, TILEMAP_LEN)
        box = box_open(tm)
        lines = frame_lines(tm) if box else []
        if emu.read(BATTLE_FLAG) != 0 or any("FIGHT" in ln for ln in lines):
            return self._press(emu, "A", before, box,
                               f"battle (wIsInBattle=0x{emu.read(BATTLE_FLAG):02X}): FIGHT first move")
        if box:
            if self.box_streak >= 12 and is_menu(tm):
                return self._press(emu, "B", before, box,
                                   "a menu stayed open 12 presses - backing out")
            if self.box_streak >= 60:
                return self._press(emu, "B", before, box,
                                   "a dialog ran 60 presses - B in case it is a hidden prompt")
            if is_menu(tm):
                options = [
                    ln.replace(">", "").strip()
                    for ln in lines
                    if ">" in ln or (ln.isupper() and len(ln.split()) <= 3)
                ]
                cursor = next((ln.replace(">", "").strip() for ln in lines if ">" in ln), "")
                tried = self.menu_tried.setdefault(before + (self.facing,), set())
                if cursor and cursor not in tried:
                    tried.add(cursor)
                    return self._press(emu, "A", before, box,
                                       f"menu open, cursor on '{cursor}' (new) - choosing it")
                if any(o not in tried for o in options):
                    return self._press(emu, "DOWN", before, box,
                                       f"menu open, '{cursor}' already tried - moving cursor down")
                return self._press(emu, "B", before, box,
                                   "menu open, every option tried here - backing out")
            return self._press(emu, "A", before, box,
                               "a text box is open - finishing the interaction")
        name, why = self.mem.choose(before[0], before[1], before[2], self.facing)
        return self._press(emu, name, before, box, why)

    def run(self, emu: Emulator, steps: int) -> dict:
        """Run ``steps`` explorer presses; returns the run tail and memory summary."""
        out = [self.step(emu) for _ in range(max(0, steps))]
        self.mem.save()
        return {"ran": len(out), "recent": out[-10:], "memory": self.summary()}

    def summary(self) -> dict:
        """Totals across the whole map memory."""
        maps = self.mem.data["maps"]
        return {
            "maps": sorted(int(m) for m in maps),
            "visited": sum(len(d["visited"]) for d in maps.values()),
            "blocked": sum(len(d["blocked"]) for d in maps.values()),
            "warps": sum(len(d["warps"]) for d in maps.values()),
            "interactions": sum(len(d.get("interactions", {})) for d in maps.values()),
        }

    def _press(self, emu: Emulator, name: str, before: tuple, box_before: bool, why: str) -> dict:
        self.step_count += 1
        self.mem.observe_npcs(before[0], emu, self.step_count)
        emu.press(Button[name])
        after = self._settle(emu, before)
        tm2 = emu.read_range(TILEMAP_ADDR, TILEMAP_LEN)
        box_after = box_open(tm2)
        if box_before:
            self.last_fail = None
            result = f"text box: advanced ({'menu' if is_menu(tm2) else 'dialog'})"
        else:
            if name in DIRS:
                self.facing = name
            confirmed = self.last_fail == (before, name)
            result = self.mem.learn(before, name, after, confirmed=confirmed)
            self.last_fail = (before, name) if (name in DIRS and after == before) else None
            if name == "A":
                text = " | ".join(frame_lines(tm2)) if box_after else ""
                context = classify_screen(tm2, emu.read(BATTLE_FLAG))
                transition = list(after) if after[0] != before[0] else None
                dx, dy = DIRS[self.facing]
                npc = self.mem.npc_at(before[0], before[1] + dx, before[2] + dy)
                outcome = ("map_transition" if transition else "battle" if emu.read(BATTLE_FLAG)
                           else "menu" if is_menu(tm2) else "dialog" if box_after else "none")
                self.mem.interact(before[0], before[1], before[2], self.facing, text,
                                  screen=context.screen.name, menu=context.menu.name,
                                  outcome=outcome, transition=transition, npc=npc)
                result = (
                    f'INTERACTION at ({before[1]},{before[2]}) facing {self.facing}: "{text[:60]}"'
                    if box_after
                    else f"nothing to interact with facing {self.facing} (remembered)"
                )
        self.mem.visit(after[0], after[1], after[2], self.step_count)
        self.box_streak = self.box_streak + 1 if box_after else 0
        return {"button": name, "why": why, "result": result, "pos": list(after)}

    def _settle(self, emu: Emulator, before: tuple, max_frames: int = 600) -> tuple:
        """Tick until the position holds for 3 reads; a map change gets 60 more frames."""
        s = read_state(emu)
        prev, stable, waited = (s.map_id, s.x, s.y), 0, 0
        while waited < max_frames:
            emu.tick(8)
            waited += 8
            s = read_state(emu)
            cur = (s.map_id, s.x, s.y)
            stable = stable + 1 if cur == prev else 0
            prev = cur
            if stable >= 3:
                break
        if prev[0] != before[0]:
            emu.tick(60)
            s = read_state(emu)
            prev = (s.map_id, s.x, s.y)
        return prev
