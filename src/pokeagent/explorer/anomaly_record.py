"""Anomaly records: rate limit, cause hint, runs/anomalies.jsonl, plus a save state and a PNG to replay and study."""
from __future__ import annotations

import json
import time
from pathlib import Path

RATE_PRESSES = 200       # one record per (type, map, tile) per this many presses
RECENT_DECISIONS = 10    # decisions attached to every record
CAUSE_LOOKBACK = 6       # decisions examined for the cause hint
NPC_TYPES = frozenset({"npc_in_doorway", "npc_blocking_path", "player_blocking_npc"})
GAME_TYPES = frozenset({"teleport", "impossible_state"})


def cause_hint(kind: str, npc: tuple | None, player: tuple, decisions: list[dict]) -> str:
    """"agent" when the last decisions walked the player next to the NPC involved, "game" when the NPC (or the
    game state) did it unprompted, else "unknown"."""
    if kind in GAME_TYPES:
        return "game"
    if kind not in NPC_TYPES or npc is None:
        return "unknown"
    if abs(npc[2] - player[0]) + abs(npc[3] - player[1]) != 1:
        return "game"
    moved = any(d.get("outcome") in ("moved", "map_change") for d in decisions[-CAUSE_LOOKBACK:])
    return "agent" if moved or kind == "player_blocking_npc" else "unknown"


class AnomalyLog:
    """Writes records under ``runs_dir``: anomalies.jsonl and anomalies/<run>-<step>-<type>.(state|png)."""

    def __init__(self, runs_dir: Path | str, run: str) -> None:
        self.runs_dir = Path(runs_dir)
        self.run = run
        self.last: dict[tuple, int] = {}
        self.count = 0

    def allow(self, kind: str, map_id: int, tile: tuple, step: int) -> bool:
        """Rate limit: True (and remember it) when this (type, map, tile) has not been recorded in RATE_PRESSES."""
        key = (kind, map_id, tuple(tile))
        if key in self.last and step - self.last[key] < RATE_PRESSES:
            return False
        self.last[key] = step
        return True

    def write(self, finding, *, step: int, frame: int, emu, decisions: list[dict], player: tuple) -> dict:
        out = self.runs_dir / "anomalies"
        out.mkdir(parents=True, exist_ok=True)
        stem = f"{self.run}-{step}-{finding.type}"
        state, png = out / f"{stem}.state", out / f"{stem}.png"
        saved = {}
        for name, path, fn in (("state", state, lambda: emu.save_state(state)), ("png", png, lambda: emu.screenshot().save(png))):
            try:
                fn()
                saved[name] = path.as_posix()
            except Exception as e:  # a failed artifact must never end a run
                saved[name] = None
                saved[name + "_error"] = repr(e)
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "run": self.run, "step": step, "frame": frame, "type": finding.type,
               "map": finding.map, "x": finding.x, "y": finding.y, "details": finding.details,
               "cause_hint": cause_hint(finding.type, finding.npc, player, decisions),
               "decisions": decisions[-RECENT_DECISIONS:], **saved}
        with (self.runs_dir / "anomalies.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
        self.count += 1
        return rec
