"""Planning and remote control for the explorer demo (imported by tools/explore_demo.py).

WorldGraph : multi-map BFS over what the explorer has learned (visited tiles, confirmed walls, warps),
             so `goto` and goal plans can route across floors and doors without any hard-coded map.
plan_step  : goal-directed policy on top of exploration - Robert's targets in order: potion (PC),
             leave the house, first pokemon (Oak's trigger), win the first battle (FIGHT).
ControlServer : a tiny localhost HTTP API (default port 8765) so Claude (curl) and later the MCP server can
             observe and interfere while the rule-based agent keeps the main steer:
               GET  /status   /goals   /screen   /screenshot.png   /map?id=38
               POST /press {"button": "A"}   /pause   /resume   /goto {"map": 38, "x": 0, "y": 2}   /say {"text": ...}
"""
from __future__ import annotations

import io
import json
import threading
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

DIRS = {"UP": (0, -1), "DOWN": (0, 1), "LEFT": (-1, 0), "RIGHT": (1, 0)}
STARTERS = ("BULBASAUR", "CHARMANDER", "SQUIRTLE")


class WorldGraph:
    """Nodes are (map, x, y). Edges: visited neighbours not separated by a confirmed wall, plus warps."""

    def __init__(self, maps: dict):
        self.maps = maps

    strict = True  # False = optimistic: ignore learned walls (some are false, learned behind an NPC or a fade)

    def neighbours(self, node):
        m, x, y = node
        d = self.maps.get(str(m))
        if not d:
            return
        for name, (dx, dy) in DIRS.items():
            key = f"{x},{y},{name}"
            warp = d.get("warps", {}).get(key)
            if warp:
                yield (warp[0], warp[1], warp[2]), name
                continue
            jump = d.get("jumps", {}).get(key)
            if jump:  # a learned ledge: one-way hop to a tile more than one step away
                yield (m, jump[0], jump[1]), name
                continue
            if self.strict and key in d.get("blocked", []):
                continue
            nx, ny = x + dx, y + dy
            if f"{nx},{ny}" in d.get("visited", {}):
                yield (m, nx, ny), name

    def path(self, start, goal_fn: Callable[[tuple], bool], limit: int = 5000) -> list[str] | None:
        """Strict BFS first; if no route, an optimistic one (walls ignored): a false wall gets re-tested and
        cleared on the way instead of leaving the agent with no plan (seen 2026-11-03: stuck at Mom)."""
        p = self._bfs(start, goal_fn, limit)
        if p is None and self.strict:
            self.strict = False
            try:
                p = self._bfs(start, goal_fn, limit)
            finally:
                self.strict = True
        return p

    def _bfs(self, start, goal_fn, limit):
        prev = {start: None}
        q = deque([start])
        while q and len(prev) < limit:
            cur = q.popleft()
            if goal_fn(cur):
                out, node = [], cur
                while prev[node]:
                    node, btn = prev[node]
                    out.append(btn)
                return out[::-1]
            for nxt, btn in self.neighbours(cur):
                if nxt not in prev:
                    prev[nxt] = (cur, btn)
                    q.append(nxt)
        return None


def interaction_spots(maps: dict, needle: str) -> list[tuple[int, int, int, str]]:
    """(map, x, y, facing) of recorded interactions whose text mentions `needle`."""
    out = []
    for mid, d in maps.items():
        for key, e in d.get("interactions", {}).items():
            hay = ((e.get("text") or "") + " " + " ".join(e.get("choices", []) or [])).lower()
            if needle.lower() in hay:
                x, y, f = key.split(",")
                out.append((int(mid), int(x), int(y), f))
    return out


def plan_step(goals: dict, maps: dict, pos: tuple, facing: str) -> tuple[str, str] | None:
    """Next button toward the first unmet goal that the learned world already knows how to reach, else None."""
    g = WorldGraph(maps)
    hp, mx = goals.get("_hp", (0, 0))
    if goals.get("first_pokemon") and mx and hp / mx < 0.4 and pos[0] in (0x00, 0x25, 0x26, 0x0C) and not goals.get("_mom_failed"):
        # Weak and near home: Mom heals the party when talked to. She is the one static sprite downstairs
        # (learned in maps.json npcs; fallback (5,4)); stand below her facing UP and press A.
        mom = next((e for e in maps.get(str(0x25), {}).get("npcs", {}).values() if not e.get("moves") and e.get("last")), None)
        mx_, my_ = (mom["last"][0], mom["last"][1]) if mom else (5, 4)
        spot = (0x25, mx_, my_ + 1)
        if pos == spot:
            return ("A" if facing == "UP" else "UP"), f"HP {hp}/{mx}: at Mom, {'talking' if facing == 'UP' else 'facing her'} to heal"
        p = g.path(pos, lambda n: n == spot)
        if p:
            return p[0], f"HP {hp}/{mx}: going home to Mom to heal ({len(p)} steps)"
    if not goals.get("potion"):
        for (m, x, y, f) in interaction_spots(maps, "PC"):
            if pos == (m, x, y):
                return ("A" if facing == f else f), f"goal potion: at the PC, {'using it' if facing == f else 'facing it'}"
            p = g.path(pos, lambda n: n == (m, x, y))
            if p:  # [] cannot happen here (pos == spot handled above)
                return p[0], f"goal potion: {len(p)} steps to the PC at ({x},{y}) on map 0x{m:02X}"
    if not goals.get("left_house"):
        p = g.path(pos, lambda n: n[0] not in (0x25, 0x26))
        if p:
            return p[0], f"goal leave the house: {len(p)} steps to the door"
    if not goals.get("first_pokemon"):
        # In Oak's lab: go to the ball that offers the wanted starter (learned from earlier "Do you want X?" boxes).
        if pos[0] == 0x28:
            want = (goals.get("_starter") or "any").upper()

            def spot_text(m, x, y, f):
                e = maps.get(str(m), {}).get("interactions", {}).get(f"{x},{y},{f}", {})
                return ((e.get("text") or "") + " " + " ".join(e.get("choices", []) or [])).upper()

            # Balls = spots in the lab whose dialog named a starter. The wanted one may be an untried neighbour
            # on the same table row, so try those too. NEVER fall through to the Pallet Town OAK spot from here:
            # that is what walked the agent back out of the lab.
            # A ball spot is one whose dialog had the OFFER phrase ("So! You want the water POKeMON, SQUIRTLE?").
            # Plain "want" also matches the nickname question, which contaminated a spot where the agent merely
            # stood while that dialog ran (5,5,DOWN "received a BULBASAUR"); the offer phrase does not.
            OFFER = "YOU WANT THE"
            ELEMENT = {"FIRE": "CHARMANDER", "WATER": "SQUIRTLE", "PLANT": "BULBASAUR", "GRASS": "BULBASAUR"}

            def ball_species(s):
                """Which starter THIS ball offers, read from its own offer text ('You want the fire POKeMON, CHARMANDER?'),
                never from later dialog that may mention another starter (that contamination sent a Bulbasaur run to the
                Charmander ball forever)."""
                import re as _re
                m = _re.search(r"YOU WANT THE\W*(FIRE|WATER|PLANT|GRASS)\W*POK", spot_text(*s))
                return ELEMENT[m.group(1)] if m else None
            balls = [s for s in interaction_spots(maps, OFFER) if s[0] == 0x28 and ball_species(s)]
            targets = [s for s in balls if want == "ANY" or ball_species(s) == want]
            if not targets and balls:
                tried = {(s[1], s[2], s[3]) for s in balls}
                for (m, x, y, f) in balls:
                    for dx in (-1, 1):
                        if (x + dx, y, f) not in tried and not any(n in spot_text(m, x + dx, y, f) for n in STARTERS if n != want):
                            targets.append((m, x + dx, y, f))
            for (m, x, y, f) in sorted(targets, key=lambda s: abs(s[1] - pos[1]) + abs(s[2] - pos[2])):
                if pos == (m, x, y):
                    return ("A" if facing == f else f), f"goal first pokemon: at a ball spot for {want}, {'taking it' if facing == f else 'facing it'}"
                p = g.path(pos, lambda n: n == (m, x, y))
                if p:
                    return p[0], f"goal first pokemon: {len(p)} steps to the ball spot ({x},{y}) for {want}"
            return None  # unknown table so far: explore the lab (the caller's exploration prefers untested walls)
        # Oak's trigger is the outdoor "Hey! Wait!" event in Pallet Town (map 0). Any spot whose text merely mentions OAK
        # also matched Mom's line "...Oak is looking for you", which sent every starter-segment agent into its own
        # house to talk to Mom for 1800 steps.
        for (m, x, y, f) in [s for s in interaction_spots(maps, "WAIT") if s[0] == 0x00]:
            if pos == (m, x, y):
                return f, f"goal first pokemon: standing where OAK appeared; stepping {f} to fire the event again"
            p = g.path(pos, lambda n: n == (m, x, y))
            if p:
                return p[0], f"goal first pokemon: {len(p)} steps to where OAK appeared ({x},{y}) on map 0x{m:02X}"
    if goals.get("first_pokemon") and not goals.get("won_battle") and pos[0] == 0x28:
        # The rival only challenges you when you try to leave the lab: head for the exit (a learned warp out of
        # 0x28 if we have one, else the lowest visited tile - the door is on the bottom edge).
        p = g.path(pos, lambda n: n[0] != 0x28)
        if p is not None and p:
            return p[0], f"goal first battle: walking to the lab exit so the rival challenges us ({len(p)} steps)"
        d = maps.get(str(0x28), {})
        tiles = [tuple(map(int, k.split(","))) for k in d.get("visited", {})]
        if tiles:
            tx, ty = max(tiles, key=lambda t: (t[1], -abs(t[0] - 4)))
            if (pos[1], pos[2]) != (tx, ty):
                p = g.path(pos, lambda n: n == (0x28, tx, ty))
                if p:
                    return p[0], f"goal first battle: heading to the bottom of the lab ({tx},{ty}) to find the door"
            return "DOWN", "goal first battle: at the lowest known tile, trying DOWN for the door"
    level = goals.get("_level", 0)
    carrying_parcel = goals.get("oaks_parcel") and not goals.get("deliver_parcel")
    if goals.get("won_battle") and goals.get("to_route1") and 0 < level < 8 and mx and hp / mx >= 0.5 and not carrying_parcel:
        # (never while carrying Oak's parcel: delivering it came last in every deliver_parcel run because this branch
        #  sent the agent back to Route 1 to train - they spent 600+ presses there and never reached the lab)
        # Training: wander the Route 1 grass while healthy; wild battles are fought (FIGHT), fled when weak.
        if pos[0] != 0x0C:
            p = g.path(pos, lambda n: n[0] == 0x0C)
            if p:
                return p[0], f"goal train to L8 (now L{level}, HP {hp}/{mx}): {len(p)} steps back to Route 1"
        return None  # on Route 1: let exploration roam (grass encounters happen on their own)
    if goals.get("to_viridian") and not goals.get("oaks_parcel"):
        # Already known from earlier agents: the spot where "got OAK PARCEL" was seen. Go there and talk (known facts first).
        known = [tuple(goals["_parcel_spot"])] if goals.get("_parcel_spot") else []  # (map, x, y, facing) from the item log
        for (m, x, y, f) in known + interaction_spots(maps, "OAK PARCEL") + interaction_spots(maps, "PARCEL"):
            if pos == (m, x, y):
                return ("A" if facing == f else f), f"goal parcel: at the mart clerk spot ({x},{y}), {'talking' if facing == f else 'facing him'}"
            p = g.path(pos, lambda n: n == (m, x, y))
            if p:
                return p[0], f"goal parcel: {len(p)} steps to the known mart clerk spot ({x},{y}) on map 0x{m:02X}"
        # The parcel is at the Viridian Mart: explore Viridian's buildings - take warps on map 0x01 never taken yet.
        if pos[0] == 0x01:
            d = maps.get("1", {})
            fresh = [k for k in d.get("warps", {}) if d.get("warp_taken", {}).get(k, 0) == 0]
            for k in fresh:
                wx, wy, wd = k.split(",")
                target = (0x01, int(wx), int(wy))
                if pos == target:
                    return wd, f"goal parcel: trying an unexplored door at ({wx},{wy})"
                p = g.path(pos, lambda n: n == target)
                if p:
                    return p[0], f"goal parcel: {len(p)} steps to an unexplored door at ({wx},{wy})"
        elif pos[0] not in (0x00, 0x0C, 0x25, 0x26, 0x28):
            return None  # inside a Viridian building: explore it (talk to the clerk - the parcel is a bag change)
        else:
            p = g.path(pos, lambda n: n[0] == 0x01)
            if p:
                return p[0], f"goal parcel: {len(p)} steps back to Viridian City"
    if goals.get("oaks_parcel") and not goals.get("deliver_parcel"):
        if pos[0] == 0x28:
            # Talk to PROF. OAK himself: the tile+facing where an interaction's text starts with his speaker tag
            # ("OAK BCN, raise your young POKeMON...") - NOT the aides or the rival. Oak stands static at (5,2).
            oak = [s for s in interaction_spots(maps, "RAISE YOUR") + interaction_spots(maps, "OAK B") if s[0] == 0x28]
            for (m, x, y, f) in oak:
                if pos == (m, x, y):
                    return ("A" if facing == f else f), f"goal deliver the parcel: at Oak's spot ({x},{y}), {'talking' if facing == f else 'facing him'}"
                p = g.path(pos, lambda n: n == (m, x, y))
                if p:
                    return p[0], f"goal deliver the parcel: {len(p)} steps to Oak at ({x},{y})"
            return None  # unknown yet: exploration talks to the NPCs
        p = g.path(pos, lambda n: n[0] == 0x28)
        if p:
            return p[0], f"goal deliver the parcel: {len(p)} steps to Oak's lab"
    after_parcel = goals.get("deliver_parcel") and not goals.get("to_pewter")
    if (goals.get("first_pokemon") and not goals.get("to_viridian")) or after_parcel:
        # The road north: Route 1 (0x0C), Viridian (0x01), then (parcel delivered, the old man steps aside) Route 2 (0x0D)
        # and Pewter City (0x02). Use known transitions if any; otherwise push to the northernmost explored tile of the
        # current outdoor map and keep going UP (map edges are connections).
        if after_parcel:
            target_map = 0x02 if goals.get("to_route2") else 0x0D
        else:
            target_map = 0x01 if goals.get("to_route1") else 0x0C
        p = g.path(pos, lambda n: n[0] == target_map)
        if p:
            return p[0], f"goal road north: {len(p)} steps to map 0x{target_map:02X}"
        outdoors = (0x00, 0x0C, 0x01, 0x0D, 0x02)
        if pos[0] not in outdoors:  # indoors (house, lab): get outside first - never probe house walls for a road
            p = g.path(pos, lambda n: n[0] in outdoors)
            if p:
                return p[0], f"goal road north: leaving map 0x{pos[0]:02X} for the outdoors ({len(p)} steps)"
            return None
        if pos[0] == 0x00:  # in Pallet Town: Route 1 is the known way north
            p = g.path(pos, lambda n: n[0] == 0x0C)
            if p:
                return p[0], f"goal road north: {len(p)} steps to Route 1"
        d = maps.get(str(pos[0]), {})
        blocked = set(d.get("blocked", []))
        # candidate frontier tiles: northernmost first, but never one whose UP is a confirmed wall (that was the
        # 'keeps pushing up into a wall' loop); a tile only counts if UP from it is still unknown
        tiles = [tuple(map(int, k.split(","))) for k in d.get("visited", {})]
        tiles = [t for t in tiles if f"{t[0]},{t[1]},UP" not in blocked and f"{t[0]},{t[1] - 1}" not in d.get("visited", {})]
        if tiles:
            tx, ty = min(tiles, key=lambda t: (t[1], abs(t[0] - pos[1])))
            if (pos[1], pos[2]) == (tx, ty):
                return "UP", "goal road north: at the northernmost open tile, pushing UP for the map edge"
            p = g.path(pos, lambda n: n == (pos[0], tx, ty))
            if p:
                return p[0], f"goal road north: {len(p)} steps to the northernmost known tile ({tx},{ty})"
    return None


class ControlServer:
    """Runs on its own thread; every handler is executed on the demo's main (tk/emulator) thread via `call`."""

    def __init__(self, call: Callable[[Callable], object], port: int = 8765):
        self.call, self.port = call, port
        self.routes: dict[tuple[str, str], Callable] = {}

    def route(self, method: str, path: str):
        def deco(fn):
            self.routes[(method, path)] = fn
            return fn
        return deco

    def start(self):
        srv = self
        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):  # keep the demo's stdout silent (MCP-safe)
                pass
            def _send(self, code, body, ctype="application/json"):
                data = body if isinstance(body, bytes) else json.dumps(body, indent=1).encode()
                self.send_response(code); self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
            def _dispatch(self, method):
                path, _, query = self.path.partition("?")
                fn = srv.routes.get((method, path))
                if not fn:
                    return self._send(404, {"error": f"no route {method} {path}", "routes": sorted(f"{m} {p}" for m, p in srv.routes)})
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}") if n else {}
                params = dict(kv.split("=", 1) for kv in query.split("&") if "=" in kv)
                def job():  # runs on the tk thread: serialise there too, so no live dict is walked concurrently
                    r = fn(**{**params, **body})
                    return (r, "image/png") if isinstance(r, bytes) else (json.dumps(r, indent=1).encode(), "application/json")
                try:
                    data, ctype = srv.call(job)
                except Exception as e:  # report, never kill the demo
                    return self._send(500, {"error": repr(e)})
                self._send(200, data, ctype)
            def do_GET(self): self._dispatch("GET")
            def do_POST(self): self._dispatch("POST")
        self.httpd = ThreadingHTTPServer(("127.0.0.1", self.port), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self

    def stop(self):
        self.httpd.shutdown()


def png_bytes(image) -> bytes:
    buf = io.BytesIO(); image.save(buf, format="PNG"); return buf.getvalue()
