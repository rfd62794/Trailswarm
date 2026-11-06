"""Agent-side control server: ``GET /snapshot`` and ``POST /command`` on a daemon thread (stdlib).

Security: every request must carry ``X-PokeAgent-Token`` (``ControlServer.token``), have no
``Origin`` header and a Host of 127.0.0.1:<port> or localhost:<port>, else 403. POST needs
Content-Type application/json (415). Commands v1 are listed in ``COMMAND_ARGS`` (name -> {arg: type}). The server validates argument
presence and type before calling ``handlers[name](**args)``, then returns the handler's dict merged
with ``{"ok": true}``.

``press`` carries an optional ``source`` (default ``"human"``). Agents MUST call
``HumanHold.touch()`` (see ``pokeagent.human_hold``) for ``source == "human"`` presses so the agent
stops deciding while a human steers; ``hold_release`` ends the hold immediately. ``claude_hold`` (seconds 1..600) is
the same for a Claude lease (``source:"claude"`` presses refresh it); ``macro`` runs a screen-verified procedure.
"""
from __future__ import annotations

import hmac
import json
import re
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import parse_qs

from pokeagent.snapshot import AgentSnapshot

BUTTONS = ("A", "B", "START", "SELECT", "UP", "DOWN", "LEFT", "RIGHT")
SPEEDS = (1, 2, 4, 8)
TOKEN_HEADER = "X-PokeAgent-Token"
MAX_BODY = 65536
NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

PAUSE, RESUME, SPEED, PRESS, STEER = "pause", "resume", "speed", "press", "steer"
HAND_TO, SAVE_STATE, LOAD_STATE, HOLD_RELEASE = "hand_to", "save_state", "load_state", "hold_release"
CLAUDE_HOLD, MACRO = "claude_hold", "macro"   # intervene/: lease + screen-verified macros (see pokeagent.intervene)

# name -> (required args, optional args), each {arg: type}
COMMAND_ARGS: dict[str, tuple[dict[str, type], dict[str, type]]] = {
    PAUSE: ({}, {}), RESUME: ({}, {}), HOLD_RELEASE: ({}, {}),
    SPEED: ({"n": int}, {}),
    PRESS: ({"button": str}, {"source": str}),
    STEER: ({"on": bool}, {}),
    HAND_TO: ({"driver": str}, {}),
    SAVE_STATE: ({"name": str}, {}),
    LOAD_STATE: ({"name": str}, {}),
    CLAUDE_HOLD: ({"seconds": int}, {}),
    MACRO: ({"name": str}, {"args": dict}),
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
    if cmd == CLAUDE_HOLD and not 1 <= args["seconds"] <= 600:
        return "claude_hold: seconds must be 1..600"
    if cmd in (SAVE_STATE, LOAD_STATE, MACRO) and not NAME_RE.match(args["name"]):
        return f"{cmd}: name must match [A-Za-z0-9_-]{{1,64}}"
    return None


class ControlServer:
    def __init__(self, snapshot_fn: Callable[[], AgentSnapshot], handlers: dict[str, Callable[..., dict]],
                 host: str = "127.0.0.1", port: int = 0, token: str | None = None,
                 events_fn: Callable[[int], list] | None = None) -> None:
        self.events_fn = events_fn   # since-seq -> list of event dicts (``GET /events?since=N``); None = 404
        self.token = token or secrets.token_urlsafe(24)
        self.snapshot_fn, self.handlers = snapshot_fn, handlers
        self.host, self.port = host, port
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> int:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            timeout = 2  # a slow client cannot hold a thread

            def log_message(self, *a) -> None:  # silence request logging
                pass

            def _send(self, code: int, body) -> None:
                raw = json.dumps(body).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                if code >= 400:
                    self.send_header("Connection", "close")
                    self.close_connection = True
                self.end_headers()
                self.wfile.write(raw)

            def _guard(self) -> bool:
                """403 on Origin header, foreign Host, or bad/missing token."""
                host = self.headers.get("Host", "")
                ok = (self.headers.get("Origin") is None
                      and host in (f"127.0.0.1:{outer.port}", f"localhost:{outer.port}")
                      and hmac.compare_digest(self.headers.get(TOKEN_HEADER, "").encode(), outer.token.encode()))
                if not ok:
                    self._send(403, {"ok": False, "error": "forbidden"})
                return ok

            def do_GET(self) -> None:
                if not self._guard():
                    return
                route, _, query = self.path.partition("?")
                if route == "/events" and outer.events_fn is not None:
                    try:
                        since = int(parse_qs(query).get("since", ["0"])[0])
                        return self._send(200, outer.events_fn(max(0, since)))
                    except ValueError:
                        return self._send(400, {"ok": False, "error": "since must be an integer"})
                    except Exception as exc:
                        return self._send(500, {"ok": False, "error": str(exc)})
                if route != "/snapshot":
                    return self._send(404, {"ok": False, "error": "not found"})
                try:
                    self._send(200, outer.snapshot_fn().to_dict())
                except Exception as exc:
                    self._send(500, {"ok": False, "error": str(exc)})

            def do_POST(self) -> None:
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                    if not 0 <= length <= MAX_BODY:
                        raise ValueError
                except ValueError:
                    return self._send(400, {"ok": False, "error": "bad content-length"})
                try:
                    raw = self.rfile.read(length) if length else b""  # always drain before replying
                except OSError:
                    return self._send(400, {"ok": False, "error": "bad body"})
                if not self._guard():
                    return
                ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                if ctype != "application/json":
                    return self._send(415, {"ok": False, "error": "content-type must be application/json"})
                if self.path.split("?")[0] != "/command":
                    return self._send(404, {"ok": False, "error": "not found"})
                try:
                    body = json.loads(raw or b"")
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
            out = self.handlers[name](**args) or {}
            if "error" in out:  # e.g. the emulator thread did not pick the command up in time
                return 504, {**out, "ok": False}
            return 200, {"ok": True, **out}  # a handler may report ok=False (a macro that stopped)
        except Exception as exc:
            return 500, {"ok": False, "error": str(exc)}

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
