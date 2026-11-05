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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

# WorldGraph / plan_step moved into the package (the explorer package never imports from tools/); re-exported
# here so tools/make_state.py and tools/explore_demo.py keep working.
from pokeagent.explorer.planner import plan_step  # noqa: F401
from pokeagent.explorer.world import (  # noqa: F401
    DIRS, POKECENTER_MAP, POKECENTER_MAPS, STARTERS, WorldGraph, interaction_spots,
)


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
