"""Per-map memory in the demo's runs/maps.json schema (moved from tools/explore_demo.py, merged with the old
framework module's MapMemory). The schema is unchanged."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from pokeagent.explorer.memory_nav import NavMixin
from pokeagent.explorer.perceive import DIRS

# After a blackout the game drops us at the last Pokecenter's door (Viridian (23,26) once we healed there) or at home
# (Pallet (5,6)). Arriving there from any other map is a respawn, never a door: it made a ghost 3-step 'warp' from the
# Forest to the Pokecenter that the heal planner oscillated on for 1000+ steps (2026-11-03 06:12). value = the only
# map those landings are legitimately reached from.
WHITEOUT_LANDINGS = {(1, 23, 26): 41, (0, 5, 6): 37}


class MapMemory(NavMixin):
    """Per-map memory in the runs/maps.json schema; the demo's version, merged with the old framework one.

    ``record_paths`` keeps the old framework module's ``paths`` edges (``m(id)["paths"]``); the demo passes
    False so its maps.json gains no new key.
    """

    def __init__(self, path: Path | str, *, record_paths: bool = True):
        self.path = Path(path)
        self.record_paths = record_paths
        self.data = json.loads(path.read_text()) if path.exists() else {"maps": {}}
        self.recent_talk: set = set()  # spots talked to this run: never re-probe them (Mom loop, 2026-11-03)
        self.purge_bad_warps()

    def purge_bad_warps(self):
        """Warps listed in data['bad_warps'] ('map:x,y,DIR') were learned from forced walks (Oak's escort) and do not
        actually warp; they are removed on load and never merged back by the swarm."""
        for mid, d in self.data.get("maps", {}).items():  # whiteout respawns recorded as doors (see WHITEOUT_LANDINGS)
            for key, dest in list(d.get("warps", {}).items()):
                if tuple(dest) in WHITEOUT_LANDINGS and int(mid) != WHITEOUT_LANDINGS[tuple(dest)]:
                    d["warps"].pop(key, None); d.get("warp_cand", {}).pop(key, None)
        for ref in self.data.get("bad_warps", []):
            mid, sep, key = ref.partition(":")
            if not sep:
                continue  # malformed tombstone: ignore it rather than failing every load
            d = self.data.get("maps", {}).get(mid, {})
            d.get("warps", {}).pop(key, None)
            d.get("warp_cand", {}).pop(key, None)  # or learn() would re-add it on the next sighting

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
        if self.record_paths and (m1, x1, y1) != (m0, x0, y0):
            paths = self.m(m0).setdefault("paths", {})
            edge = paths.setdefault(key, {"to": [m1, x1, y1], "count": 0})
            edge["to"] = [m1, x1, y1]
            edge["count"] += 1
        if m1 != m0:
            w = self.m(m0)["warps"]
            if WHITEOUT_LANDINGS.get((m1, x1, y1), m0) != m0:
                return f"map changed to 0x{m1:02X} (a whiteout respawn, not a door)"
            if f"{m0}:{key}" in self.data.get("bad_warps", []):
                return f"map changed to 0x{m1:02X} (known forced walk - not a warp)"
            cand = self.m(m0).setdefault("warp_cand", {})
            cand[key] = cand.get(key, 0) + 1
            if key not in w and cand[key] < 2:  # a map change seen ONCE from this tile+direction may be a forced walk
                return f"map changed to 0x{m1:02X} (seen once - not recorded as a warp yet)"
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

    def interact(self, map_id, x, y, facing, text: str, *, screen: str | None = None, menu: str | None = None,
                 outcome: str | None = None, transition: list | None = None, npc: dict | None = None) -> dict:
        """Record one interaction. The keyword extras are the old framework explorer's richer record; the demo
        passes none, so its entries keep exactly their old shape."""
        d = self.m(map_id).setdefault("interactions", {})
        e = d.setdefault(f"{x},{y},{facing}", {"count": 0, "text": "", "presses": [], "menus": [], "choices": []})
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


    def save(self):
        self.data["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")  # atomic replace: a kill mid-write cannot corrupt the memory
        tmp.write_text(json.dumps(self.data, indent=1))
        os.replace(tmp, self.path)
