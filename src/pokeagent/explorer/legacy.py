"""The framework's older, simpler explorer policy (the MCP server's ``Explorer``), ported from tools/explore_demo.py.

The demo's policy lives inside its tkinter loop, so the framework keeps this
self-contained port: same ``runs/maps.json`` schema (the framework and the
demo share that file), same rule order - advance dialog, explore menus, FIGHT
in battle, otherwise walk toward the least-visited tile that is not known
blocked - and the same blocked/warp learning with the two-strike confirm.
"""

from __future__ import annotations

from pathlib import Path

from pokeagent.emulator import Button, Emulator
from pokeagent.explorer.memory import MapMemory
from pokeagent.explorer.perceive import (
    BATTLE_FLAG, DIRS, TILEMAP_ADDR, TILEMAP_LEN, box_open, frame_lines, is_menu,
)
from pokeagent.goals import store_path
from pokeagent.ram import read_state
from pokeagent.screencontext import classify_screen


class Explorer:
    """Runs the demo's rule-based policy one press at a time on any Emulator."""

    def __init__(self, maps_path: Path | str = store_path("runs/maps.json")) -> None:  # POKEAGENT_GAME read once at def time
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
