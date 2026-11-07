"""The save-state ledger: choose a state by what it IS, not by its file name or mtime.

Pure JSON over the ``<state>.fp.json`` sidecars (statefp) - no emulator, no central file, no lock. ``entries`` reads every
``*.state`` directly in a directory; ``select`` keeps only the fresh ones, applies a consumer's hard filters (a fingerprint
that lacks a key a filter needs fails that filter - never guessed), then ranks by party power (``Want.strongest``) and mtime.
``None`` from ``select``/``pick`` is the signal to keep the old name/mtime path.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from pokeagent import checkpoint_goals, statefp

# wLastBlackoutMap towns ranked earliest to latest: Pallet 0, Viridian 1, Pewter 2, Cerulean 3, Vermilion 5. Any other
# map id ranks 5 - a documented simplification: every later town (Lavender, Celadon, ...) is at or past Vermilion.
RESPAWN_RANK = {0: 0, 1: 1, 2: 2, 3: 3, 5: 4}
RETIRED_DIR = Path("runs/retired")
# What a corrupt-but-valid-JSON fingerprint raises when a field has the wrong type or shape: such an entry is stale or
# non-matching, never an error that escapes select() (ckpt() runs inside the swarm scheduler).
CORRUPT = (ArithmeticError, TypeError, IndexError, ValueError, KeyError)  # ArithmeticError: ZeroDivision, Overflow


@dataclass(frozen=True)
class Entry:
    path: Path            # the .state file
    fp: dict              # statefp.read(path) or {} when there is no sidecar
    mtime: float          # path.stat().st_mtime
    stem: str             # re.split(r"[.@]", path.name)[0]: <goal>@63, <goal>.best and 99_13_6.1 share their base stem


@dataclass(frozen=True)
class Want:
    stem: str | None = None              # entry.stem must equal this (a checkpoint name or a leg key "M_X_Y")
    map: int | None = None               # entry.fp["map"] must equal this
    respawn_ahead_of: int | None = None  # entry.fp["respawn"] must rank AT OR PAST this town (see RESPAWN_RANK)
    min_hp: float = 0.0                  # statefp.party_hp_fraction(fp) >= min_hp
    min_lead_level: int = 0              # fp["party"][0][1] >= this
    min_heal_items: int = 0              # fp["heal_items"] >= this
    strongest: bool = False              # rank by party power first (boss stages)


_NAMES: dict[Path, tuple[float, frozenset]] = {}


def _names(d: Path) -> frozenset:
    """The file names in ``d``, cached by the dir's own mtime: NTFS/POSIX bump it on add/remove/rename, so a new state
    or sidecar is always seen; content rewrites leave the name list (all this caches) unchanged."""
    try:
        mt = d.stat().st_mtime
    except OSError:
        return frozenset()
    got = _NAMES.get(d)
    if got is None or got[0] != mt:
        got = (mt, frozenset(p.name for p in d.iterdir()))
        _NAMES[d] = got
    return got[1]


def _entry(p: Path) -> Entry | None:
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return None
    return Entry(p, statefp.read(p) or {}, mtime, re.split(r"[.@]", p.name)[0])


def _entries_of(paths) -> list[Entry]:
    return [e for p in sorted(paths, key=lambda p: p.name) if (e := _entry(p)) is not None]


def entries(directory: str | Path) -> list[Entry]:
    """Every ``*.state`` directly in ``directory`` (not recursive), sorted by name. A missing directory reads as []."""
    d = Path(directory)
    return _entries_of(d.glob("*.state")) if d.is_dir() else []


def _version(fp: dict) -> int:
    """The sidecar's ``v`` as an int; anything that is not an int (a string, a list, a missing key) counts as -1."""
    v = fp.get("v", 0)
    return v if isinstance(v, int) and not isinstance(v, bool) else -1


def status(entry: Entry) -> str:
    """``fresh`` | ``stale`` | ``retired``: stale = no sidecar or an older ``v`` than the code that reads it."""
    if entry.path.parent.name == "retired":
        return "retired"
    return "stale" if not entry.fp or _version(entry.fp) < statefp.VERSION or _malformed(entry.fp) else "fresh"


def _malformed(fp: dict) -> bool:
    """True when the party cannot be read at all (a string, short rows, non-numbers): such a fingerprint is stale."""
    try:
        statefp.party_hp_fraction(fp)
        _power(fp)
    except CORRUPT:
        return True
    return False


def _power(fp: dict) -> float:
    """sum(level * hp / max_hp) over the party - how much fight is left in it. Raises CORRUPT on a malformed party."""
    return sum(m[1] * m[2] / m[3] for m in fp.get("party") or [] if m[3] > 0)


def _respawn_rank(map_id: int) -> int:
    return RESPAWN_RANK.get(map_id, 5)


def _kept(e: Entry, w: Want) -> bool:
    """True when ``e`` passes every hard filter in ``w``. A synthetic (edited) state is never auto-selected, and a
    fingerprint too malformed to evaluate fails the filter instead of raising."""
    try:
        return _check(e, w)
    except CORRUPT:
        return False


def _check(e: Entry, w: Want) -> bool:
    fp = e.fp
    if fp.get("synthetic"):
        return False
    if w.stem is not None and e.stem != w.stem:
        return False
    if w.map is not None and fp.get("map") != w.map:
        return False
    if w.respawn_ahead_of is not None:
        if "respawn" not in fp or _respawn_rank(fp["respawn"]) < _respawn_rank(w.respawn_ahead_of):
            return False
    if w.min_hp > 0 and statefp.party_hp_fraction(fp) < w.min_hp:
        return False
    if w.min_lead_level > 0:
        party = fp.get("party") or []
        if not party or party[0][1] < w.min_lead_level:
            return False
    if w.min_heal_items > 0 and fp.get("heal_items", 0) < w.min_heal_items:
        return False
    return True


def select(items: list[Entry], want: Want) -> Entry | None:
    """The best fresh entry satisfying ``want``'s hard filters, ranked (power if strongest, mtime) descending; else None."""
    best, best_key = None, None
    for e in items:
        try:
            if status(e) != "fresh" or not _kept(e, want):
                continue
            key = (_power(e.fp) if want.strongest else 0.0, e.mtime)
        except CORRUPT:
            continue
        if best_key is None or key > best_key:
            best, best_key = e, key
    return best


def pick(directory: str | Path, want: Want) -> Path | None:
    """``entries`` then ``select``, returning the path - but only stamped states can ever win (``select`` drops the
    rest as stale), so the scan stops at the dir's name list plus the few ``<stem>*`` states with a ``.fp.json``.
    ckpt callers ask once per segment per choose, so a full stat+read sweep is too expensive here."""
    d = Path(directory)
    names = _names(d)
    stamped = {n[:-len(statefp.SUFFIX)] for n in names if n.endswith(statefp.SUFFIX)}
    paths = [d / n for n in stamped if n.endswith(".state") and (want.stem is None or n.startswith(want.stem))]
    e = select(_entries_of(paths), want)
    return e.path if e is not None else None


def _targets(retired_dir: Path, names: list, tag: str) -> list:
    """Destinations for ``names`` (the state first, then its sidecars). A non-empty ``tag`` goes before the ``.state``
    part so every file of one retire shares it: ``a.state`` -> ``a.<tag>.state``, ``a.state.fp.json`` -> ``a.<tag>.state.fp.json``."""
    state = names[0]
    head = state[:-len(".state")] if state.endswith(".state") else Path(state).stem
    return [retired_dir / ((head + tag + n[len(head):]) if tag else n) for n in names]


def retire(path: str | Path, why: str, retired_dir: str | Path = RETIRED_DIR) -> Path:
    """Move a state and its sidecars (.fp.json, .goals.json) into ``retired_dir`` - a rename, never a delete - and log
    one ``<UTC ISO>\\t<name>\\t<why>`` line in RETIRED.log. A name already taken there gets a UTC timestamp suffix
    before ``.state`` (the sidecars share it), so nothing already retired is overwritten. Returns where the state went."""
    if not why or not str(why).strip():
        raise ValueError("retire() needs a non-empty reason")
    path, retired_dir = Path(path), Path(retired_dir)
    if not path.is_file():
        raise FileNotFoundError(f"no such state: {path}")
    retired_dir.mkdir(parents=True, exist_ok=True)
    sides = [s for s in (statefp.sidecar(path), checkpoint_goals.sidecar(path)) if s.exists()]
    names = [path.name, *(s.name for s in sides)]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    tags = ["", f".{stamp}", *(f".{stamp}-{i}" for i in range(2, 1000))]
    targets = next(t for t in (_targets(retired_dir, names, tag) for tag in tags)
                   if not any(d.exists() for d in t))
    dest = targets[0]
    os.replace(path, dest)
    for s, d in zip(sides, targets[1:]):
        os.replace(s, d)
    with (retired_dir / "RETIRED.log").open("a", encoding="utf-8") as fh:
        fh.write(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')}\t{path.name}\t{why}\n")
    return dest


def bad(entry: Entry) -> str | None:
    """The reason a state is bad (``list --bad``, ``check``): no sidecar, a stale ``v``, or a ship-stage checkpoint
    whose blackout respawns behind Vermilion. None = nothing wrong on record."""
    if not entry.fp:
        return "no fingerprint sidecar"
    if _version(entry.fp) < statefp.VERSION:
        return f"stale fingerprint (v{entry.fp.get('v', 0)}, want {statefp.VERSION})"
    try:
        behind = entry.stem in checkpoint_goals.SHIP_GOALS and entry.fp.get("respawn") in checkpoint_goals.BEHIND_VERMILION
    except CORRUPT:
        return "unreadable fingerprint (malformed field)"
    if behind:
        return f"ship checkpoint respawns behind Vermilion (map {entry.fp['respawn']})"
    return None
