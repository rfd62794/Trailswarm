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

from pokeagent.qmodels import atomic_json
from pokeagent.ram import read_state


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


def write_state(emu, path: str | Path, *, source: str | Path | None = None,
                segment: str | None = None, note: str = "", verified: bool = True,
                command: list[str] | None = None) -> StateMeta:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    emu.save_state(path)
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
    }
