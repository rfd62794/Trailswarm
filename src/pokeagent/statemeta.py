"""Savestate metadata: sidecar records for provenance and reproducibility.

A `.state` file is opaque emulator bytes. `write_state` stores a sibling
`<name>.state.meta.json` describing what was saved, where it came from, and
which command/code produced it. Existing states without sidecars remain usable;
readers should treat them as unlabeled rather than inventing provenance.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from pokeagent.game.stores import store_path
from pokeagent.observations import SpatialObserver, local_tile_window
from pokeagent.qmodels import atomic_json
from pokeagent.ram import read_state
from pokeagent.ram_symbols import IS_IN_BATTLE


@dataclass(frozen=True)
class StateMeta:
    path: str
    digest: str
    created_at: float
    game: dict[str, Any]
    source: str | None = None
    segment: str | None = None
    note: str = ""
    command: list[str] | None = None
    git_sha: str | None = None
    verified: bool = True
    tiles: dict[str, Any] | None = None
    game_key: str | None = None  # which game wrote the state (the guard key); absent in older sidecars


def _git_sha() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None


def sidecar(path: str | Path) -> Path:
    path = Path(path)
    return path.with_name(path.name + ".meta.json")


def digest(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def game_snapshot(emu) -> dict[str, Any]:
    state = read_state(emu)
    return {
        "map_id": state.map_id,
        "x": state.x,
        "y": state.y,
        "party_count": state.party_count,
        "badges": state.badges,
        "badge_count": state.badge_count,
        "in_battle": state.in_battle,
        "money": state.money,
    }


def tile_snapshot(emu, maps_path: str | Path | None = None) -> dict[str, Any]:
    maps_path = store_path("runs/maps.json") if maps_path is None else maps_path
    state = read_state(emu)
    tilemap = emu.read_range(0xC3A0, 360)
    box_open = tilemap.find(bytes([0x79, 0x7A])) >= 0
    obscured = bool(emu.read(IS_IN_BATTLE) or box_open)
    snapshot = {
        "map_id": state.map_id,
        "x": state.x,
        "y": state.y,
        "tileset": emu.read(0xD367),
        "obscured": obscured,
        "window_keys": list(local_tile_window(tilemap)),
    }
    try:
        observer = SpatialObserver(maps_path)
        values = observer.observe(tilemap, state.map_id, state.x, state.y,
                                  snapshot["tileset"], obscured=obscured)
        snapshot.update(window_classes=list(values[:9]), blocked_mask=values[9],
                        maps_digest=observer.digest)
    except (OSError, ValueError, TypeError, KeyError):
        snapshot.update(window_classes=None, blocked_mask=None)
    return snapshot


def write_state(emu, path: str | Path, *, source: str | Path | None = None,
                segment: str | None = None, note: str = "", verified: bool = True,
                command: list[str] | None = None) -> StateMeta:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    emu.save_state(path)
    game_key = getattr(getattr(emu, "game", None), "key", None) \
        if hasattr(emu, "game") else "pokemon-red"  # the fallback covers test doubles with no game attr
    meta = StateMeta(
        path=str(path),
        digest=digest(path),
        created_at=time.time(),
        game=game_snapshot(emu),
        source=str(source) if source else None,
        segment=segment,
        note=note,
        command=command if command is not None else [os.path.basename(sys.executable), *sys.argv[1:]],
        git_sha=_git_sha(),
        verified=verified,
        tiles=tile_snapshot(emu),
        game_key=game_key,
    )
    atomic_json(sidecar(path), asdict(meta))
    return meta


def load_state(emu, path: str | Path) -> StateMeta | None:
    emu.load_state(Path(path))
    return read_meta(path)


def read_meta(path: str | Path) -> StateMeta | None:
    meta_path = sidecar(path)
    if not meta_path.exists():
        return None
    data = json.loads(meta_path.read_text())
    return StateMeta(**data)


def describe(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    meta = read_meta(path)
    if meta is not None:
        return asdict(meta)
    return {
        "path": str(path),
        "digest": digest(path),
        "created_at": path.stat().st_mtime,
        "game": {},
        "source": None,
        "segment": None,
        "note": "",
        "command": None,
        "git_sha": None,
        "verified": False,
        "tiles": None,
        "game_key": None,
    }
