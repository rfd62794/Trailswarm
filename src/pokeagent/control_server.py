"""Agent-side control server: ``GET /snapshot`` and ``POST /command`` on a daemon thread (stdlib).

Commands v1 are listed in ``COMMAND_ARGS`` (name -> {arg: type}). The server validates argument
presence and type before calling ``handlers[name](**args)``, then returns the handler's dict merged
with ``{"ok": true}``.

``press`` carries an optional ``source`` (default ``"human"``). Agents MUST call
``HumanHold.touch()`` (see ``pokeagent.human_hold``) for ``source == "human"`` presses so the agent
stops deciding while a human steers; ``hold_release`` ends the hold immediately.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from pokeagent.snapshot import AgentSnapshot

BUTTONS = ("A", "B", "START", "SELECT", "UP", "DOWN", "LEFT", "RIGHT")
SPEEDS = (1, 2, 4, 8)

PAUSE, RESUME, SPEED, PRESS, STEER = "pause", "resume", "speed", "press", "steer"
HAND_TO, SAVE_STATE, LOAD_STATE, HOLD_RELEASE = "hand_to", "save_state", "load_state", "hold_release"

# name -> (required args, optional args), each {arg: type}
COMMAND_ARGS: dict[str, tuple[dict[str, type], dict[str, type]]] = {
    PAUSE: ({}, {}), RESUME: ({}, {}), HOLD_RELEASE: ({}, {}),
    SPEED: ({"n": int}, {}),
    PRESS: ({"button": str}, {"source": str}),
    STEER: ({"on": bool}, {}),
    HAND_TO: ({"driver": str}, {}),
    SAVE_STATE: ({"name": str}, {}),
    LOAD_STATE: ({"name": str}, {}),
}


def _check_args(cmd: str, args: dict) -> str | None:
    required, optional = COMMAND_ARGS[cmd]
    for key, typ in {**required, **optional}.items():
        if key not in args:
            if key in required:
                return f"{cmd}: missing arg {key}"
            continue
        val = args[key]
        if not isinstance(val, typ) or (typ is int and isinstance(val, bool)):
            return f"{cmd}: arg {key} must be {typ.__name__}"
    for key in args:
        if key not in required and key not in optional:
            return f"{cmd}: unexpected arg {key}"
    if cmd == SPEED and args["n"] not in SPEEDS:
        return "speed: n must be one of 1, 2, 4, 8"
    if cmd == PRESS and args["button"] not in BUTTONS:
        return f"press: button must be one of {', '.join(BUTTONS)}"
    return None


class ControlServer:
    def __init__(self, snapshot_fn: Callable[[], AgentSnapshot], handlers: dict[str, Callable[..., dict]],
                 host: str = "127.0.0.1", port: int = 0) -> None:
        self.snapshot_fn, self.handlers = snapshot_fn, handlers
        self.host, self.port = host, port
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> int:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a) -> None:  # silence request logging
                pass

            def _send(self, code: int, body: dict) -> None:
                raw = json.dumps(body).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self) -> None:
                if self.path.split("?")[0] != "/snapshot":
                    return self._send(404, {"ok": False, "error": "not found"})
                try:
                    self._send(200, outer.snapshot_fn().to_dict())
                except Exception as exc:
                    self._send(500, {"ok": False, "error": str(exc)})

            def do_POST(self) -> None:
                if self.path.split("?")[0] != "/command":
                    return self._send(404, {"ok": False, "error": "not found"})
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                    body = json.loads(self.rfile.read(length) or b"")
                    if not isinstance(body, dict):
                        raise ValueError("body must be an object")
                except ValueError:
                    return self._send(400, {"ok": False, "error": "bad json"})
                code, out = outer.dispatch(body)
                self._send(code, out)

        self._httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self._httpd.daemon_threads = True
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self.port

    def dispatch(self, body: dict) -> tuple[int, dict]:
        args = dict(body)
        name = args.pop("cmd", None)
        if name not in COMMAND_ARGS or name not in self.handlers:
            return 400, {"ok": False, "error": f"unknown command {name}"}
        err = _check_args(name, args)
        if err:
            return 400, {"ok": False, "error": err}
        if name == PRESS:
            args.setdefault("source", "human")
        try:
            return 200, {**(self.handlers[name](**args) or {}), "ok": True}
        except Exception as exc:
            return 500, {"ok": False, "error": str(exc)}

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
