"""Agent sources: how the viewer reads a snapshot, a frame, and sends a command. Never raise."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Protocol

from pokeagent.agent_registry import list_agents
from pokeagent.snapshot import AgentSnapshot
from pokeagent.telemetry import FrameSubscriber

TIMEOUT_S = 0.5
_SLOT_PREFIX = "pokeagent_frames_"


class AgentSource(Protocol):
    agent_id: str

    def snapshot(self) -> AgentSnapshot | None: ...
    def frame(self) -> tuple[bytes, int, int] | None: ...
    def send(self, cmd: str, **args) -> dict: ...


class HttpShmSource:
    """Snapshot and commands over HTTP, frames over shared memory; ``entry`` is a registry entry."""

    def __init__(self, entry: dict) -> None:
        self.agent_id = str(entry["id"])
        self._headers = {"X-PokeAgent-Token": str(entry.get("token", ""))}
        self.base = f"http://127.0.0.1:{entry['port']}"
        slot = str(entry.get("frame_slot") or "")
        self._sub = FrameSubscriber(slot[len(_SLOT_PREFIX):] if slot.startswith(_SLOT_PREFIX) else slot) if slot else None

    def snapshot(self) -> AgentSnapshot | None:
        try:
            with urllib.request.urlopen(urllib.request.Request(self.base + "/snapshot", headers=self._headers),
                                        timeout=TIMEOUT_S) as r:
                return AgentSnapshot.from_dict(json.loads(r.read()))
        except Exception:
            return None

    def frame(self) -> tuple[bytes, int, int] | None:
        return self._sub.read() if self._sub is not None else None

    def send(self, cmd: str, **args) -> dict:
        req = urllib.request.Request(self.base + "/command", data=json.dumps({"cmd": cmd, **args}).encode(),
                                     headers={**self._headers, "Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as exc:
            try:
                return json.loads(exc.read())
            except Exception:
                return {"ok": False, "error": str(exc)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}


class FakeSource:
    """Replays given snapshots/frames (last one repeats) and records sent commands."""

    def __init__(self, agent_id: str, snapshots: list | None = None, frames: list | None = None) -> None:
        self.agent_id = agent_id
        self._snaps, self._frames = list(snapshots or []), list(frames or [])
        self.sent: list[tuple[str, dict]] = []

    @staticmethod
    def _next(items: list):
        if not items:
            return None
        return items.pop(0) if len(items) > 1 else items[0]

    def snapshot(self) -> AgentSnapshot | None:
        return self._next(self._snaps)

    def frame(self) -> tuple[bytes, int, int] | None:
        return self._next(self._frames)

    def send(self, cmd: str, **args) -> dict:
        self.sent.append((cmd, args))
        return {"ok": True}


def discover(root: Path) -> list[HttpShmSource]:
    return [HttpShmSource(e) for e in list_agents(root)]
