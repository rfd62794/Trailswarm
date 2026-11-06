"""Per-map memory in the demo's runs/maps.json schema (moved from tools/explore_demo.py, merged with the old
framework module's MapMemory). The schema is unchanged."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from pokeagent.explorer import legend, tilekind
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
        self.data = json.loads(self.path.read_text()) if self.path.exists() else {"maps": {}}
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

    def forget_warp(self, map_id: int, key: str):
        """Drop a learned warp that a press just disproved (we walked on in the same map) and tombstone it in
        bad_warps so learn() and the swarm merge never bring it back. A stale warp (learned from Oak's forced walk:
        Pallet (9,11) UP -> the lab) made the planner's shortest route to the lab a 2-step ping-pong forever."""
        d = self.m(map_id)
        d["warps"].pop(key, None)
        d.get("warp_cand", {}).pop(key, None)
        d.get("warp_taken", {}).pop(key, None)
        bad = self.data.setdefault("bad_warps", [])
        if f"{map_id}:{key}" not in bad:
            bad.append(f"{map_id}:{key}")

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
        if key in self.m(m0)["warps"] and m1 == m0 and (x1, y1) != (x0, y0) and self.m(m0)["warps"][key][0] != m0:
            self.forget_warp(m0, key)  # the press walked us along the same map: this was never a door
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

    def render_memory(self, map_id: int, x: int, y: int, npcs: set, radius: int = 6) -> legend.Rendered:
        """What the agent REMEMBERS around it, in world-legend glyphs (see explorer.legend for the kinds).
        There is no live tilemap here, so block-id kinds (grass, tile-type walls) come only from what
        memory itself recorded: blocked-edge targets for walls, interaction targets for objects."""
        d = self.m(map_id)
        trainers = tilekind.trainer_tiles(d)
        tile_types = self.data.get("tile_types", {})
        grass_ids = self.data.get("grass_ids", {})
        kinds = set()
        rows = []
        for yy in range(y - radius, y + radius + 1):
            line = ""
            for xx in range(x - radius, x + radius + 1):
                kind = "you" if (xx, yy) == (x, y) else tilekind.classify(
                    d, tile_types, grass_ids, 0, xx, yy, None, npcs, trainers)
                kinds.add(kind)
                line += legend.glyph(kind, tilekind.ledge_dir(d, xx, yy) if kind == "ledge" else None)
            rows.append(line)
        return legend.Rendered(rows, legend.line(kinds))

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

    def mark_trainer(self, map_id: int, x: int, y: int, facing: str | None = None) -> dict | None:
        """wIsInBattle == 2 means a trainer battle: the NPC we talked to or that walked up to us is a trainer.
        Flag its entry 'trainer' (the battle behaviour sets 'beaten' on a win). Returns the entry, or None
        when no NPC is adjacent - the battle could not be pinned to anyone."""
        d = self.m(map_id)
        fdx, fdy = DIRS.get(facing or "", (0, 0))
        faced = self.npc_at(map_id, x + fdx, y + fdy)
        near = [e for e in d.get("npcs", {}).values()
                if e.get("last") and max(abs(e["last"][0] - x), abs(e["last"][1] - y)) == 1]
        if faced is not None and not any(e is faced for e in near):
            near.insert(0, faced)
        if not near:
            return None
        e = max(near, key=lambda e: (e is faced, e.get("trainer", False), e.get("talked", 0)))
        e["trainer"] = True
        return e

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

    # --- goal-keyed tile outcomes: per (tile, button, goal stage) counts - the "did this press help THIS goal"
    #     memory Robert asked for. World facts stay goal-free on purpose: physics does not depend on the goal.
    def record_outcome(self, map_id, x: int, y: int, button: str, goal_stage: str,
                       progressed: bool, presses_to_goal: int | None) -> None:
        """``maps[m]["outcomes"]["x,y,BUTTON"][goal_stage] = {"n", "progress", "best"}``: n tries, how often
        the press progressed, and the fewest presses-to-goal seen (None until a segment reaches its goal)."""
        stages = self.m(map_id).setdefault("outcomes", {}).setdefault(f"{x},{y},{button}", {})
        e = stages.setdefault(goal_stage, {"n": 0, "progress": 0, "best": None})
        e["n"] += 1
        e["progress"] += int(bool(progressed))
        if presses_to_goal is not None and (e["best"] is None or presses_to_goal < e["best"]):
            e["best"] = presses_to_goal

    def save(self):
        self.data["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")  # atomic replace: a kill mid-write cannot corrupt the memory
        tmp.write_text(json.dumps(self.data, indent=1))
        os.replace(tmp, self.path)
