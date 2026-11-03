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


class WorldGraph:
    """Nodes are (map, x, y). Edges: visited neighbours not separated by a confirmed wall, plus warps."""

    def __init__(self, maps: dict):
        self.maps = maps

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
            if key in d.get("blocked", []):
                continue
            nx, ny = x + dx, y + dy
            if f"{nx},{ny}" in d.get("visited", {}):
                yield (m, nx, ny), name

    def path(self, start, goal_fn: Callable[[tuple], bool], limit: int = 5000) -> list[str] | None:
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
            if needle.lower() in (e.get("text") or "").lower():
                x, y, f = key.split(",")
                out.append((int(mid), int(x), int(y), f))
    return out


def plan_step(goals: dict, maps: dict, pos: tuple, facing: str) -> tuple[str, str] | None:
    """Next button toward the first unmet goal that the learned world already knows how to reach, else None."""
    g = WorldGraph(maps)
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
            spots = interaction_spots(maps, want if want != "ANY" else "want")
            for (m, x, y, f) in sorted(spots, key=lambda s: s != (pos[0], pos[1], pos[2], facing)):
                if m != 0x28:
                    continue
                if pos == (m, x, y):
                    return ("A" if facing == f else f), f"goal first pokemon: at the ball for {want}, {'taking it' if facing == f else 'facing it'}"
                p = g.path(pos, lambda n: n == (m, x, y))
                if p:
                    return p[0], f"goal first pokemon: {len(p)} steps to the ball for {want} at ({x},{y})"
        for (m, x, y, f) in interaction_spots(maps, "OAK"):
            if pos == (m, x, y):
                return f, f"goal first pokemon: standing where OAK appeared; stepping {f} to fire the event again"
            p = g.path(pos, lambda n: n == (m, x, y))
            if p:
                return p[0], f"goal first pokemon: {len(p)} steps to where OAK appeared ({x},{y}) on map 0x{m:02X}"
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
