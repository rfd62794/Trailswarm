"""RAM fingerprint of a save state, stored beside it as ``<state>.fp.json``.

A state file is opaque; what a curriculum needs to know about it (where a blackout lands, how healthy the party is, how
much money and healing it carries) is a handful of RAM reads. Stamp them when the state is written and any consumer can
choose or refuse a state without loading an emulator. Best effort: a failed read yields fewer keys, never an exception.
Addresses: map 0xD35E, y 0xD361, x 0xD362, badges 0xD356, money 0xD347 (3 bytes BCD), wLastBlackoutMap 0xD719.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

SUFFIX = ".fp.json"
VERSION = 1
MAP, Y, X, BADGES, MONEY, RESPAWN = 0xD35E, 0xD361, 0xD362, 0xD356, 0xD347, 0xD719
HEAL_ITEMS = frozenset(range(0x10, 0x15))   # Full Restore, Max, Hyper, Super Potion, Potion


def sidecar(state: Path) -> Path:
    return Path(state).with_name(Path(state).name + SUFFIX)


def _bcd(raw: bytes) -> int:
    return int("".join(f"{b:02x}" for b in raw)) if all((b >> 4) < 10 and (b & 15) < 10 for b in raw) else -1


def fingerprint(emu, source_run: str | None = None) -> dict:
    """What the RAM says about the state ``emu`` is standing in."""
    fp: dict = {"v": VERSION}
    try:
        fp.update(map=emu.read(MAP), x=emu.read(X), y=emu.read(Y), respawn=emu.read(RESPAWN),
                  badges=bin(emu.read(BADGES)).count("1"), money=_bcd(emu.read_range(MONEY, 3)))
    except Exception:  # noqa: BLE001
        pass
    try:
        from pokeagent.ramstructs import read_bag, read_party
        fp["party"] = [[m.species, m.level, m.hp, m.max_hp] for m in read_party(emu)]
        bag = read_bag(emu)
        fp["heal_items"] = sum(q for i, q in bag if i in HEAL_ITEMS)
        fp["bag_slots"] = len(bag)
    except Exception:  # noqa: BLE001
        pass
    if isinstance(getattr(emu, "frames", None), int):
        fp["frames"] = emu.frames
    if source_run:
        fp["source_run"] = source_run
    return fp


def write(state: Path, fp: dict) -> None:
    tmp = sidecar(state).with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(fp, sort_keys=True), encoding="utf-8")
    os.replace(tmp, sidecar(state))


def read(state: Path) -> dict | None:
    try:
        fp = json.loads(sidecar(state).read_text(encoding="utf-8"))
        return fp if isinstance(fp, dict) else None
    except (OSError, ValueError, RecursionError):
        return None


LINEAGES = ("organic", "synthetic", "promoted")


def lineage_of(fp: dict | None) -> str:
    """Lineage of a fingerprint dict: the ``lineage`` key when valid; else ``synthetic`` when ``synthetic`` is true
    (every state tools/state_edit.py wrote before lineage existed); else ``organic``."""
    fp = fp or {}
    lin = fp.get("lineage")
    if lin in LINEAGES:
        return lin
    return "synthetic" if fp.get("synthetic") else "organic"


def lineage(state: Path) -> str:
    """The state's lineage; a missing or unreadable sidecar reads ``organic`` (legacy checkpoints)."""
    return lineage_of(read(state))


def is_organic(state: Path) -> bool:
    return lineage(state) == "organic"


def is_synthetic(state: Path) -> bool:
    """True only for lineage ``synthetic``: a promoted state is NOT synthetic (it may seed drills/segments)."""
    return lineage(state) == "synthetic"


def stamp(emu, state: Path, source_run: str | None = None, *, inherit: Path | str | None = None) -> dict:
    """Fingerprint the current RAM and store it beside ``state`` (call right after the state is saved).

    ``inherit`` is the run's start state: when its lineage is not organic the new fingerprint keeps that lineage
    (synthetic stays synthetic, promoted stays promoted) and records it as ``parent`` - a run cannot launder a
    synthetic start into an organic descendant."""
    fp = fingerprint(emu, source_run)
    if inherit is not None:
        lin = lineage(Path(inherit))
        if lin != "organic":
            fp["lineage"] = lin
            fp["parent"] = Path(inherit).name
    write(state, fp)
    return fp


def party_hp_fraction(fp: dict) -> float:
    """Sum of HP over sum of max HP across the party (0.0 when unknown)."""
    p = fp.get("party") or []
    mx = sum(m[3] for m in p)
    return sum(m[2] for m in p) / mx if mx else 0.0
