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


def status(entry: Entry) -> str:
    """``fresh`` | ``stale`` | ``retired``: stale = no sidecar or an older ``v`` than the code that reads it."""
    if entry.path.parent.name == "retired":
        return "retired"
    return "stale" if not entry.fp or entry.fp.get("v", 0) < statefp.VERSION else "fresh"


def _power(fp: dict) -> float:
    """sum(level * hp / max_hp) over the party - how much fight is left in it."""
    return sum(m[1] * m[2] / m[3] for m in fp.get("party") or [] if m[3] > 0)


def _respawn_rank(map_id: int) -> int:
    return RESPAWN_RANK.get(map_id, 5)


def _kept(e: Entry, w: Want) -> bool:
    fp = e.fp
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
    ok = [e for e in items if status(e) == "fresh" and _kept(e, want)]
    return max(ok, key=lambda e: ((_power(e.fp) if want.strongest else 0.0), e.mtime), default=None)


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


def retire(path: str | Path, why: str, retired_dir: str | Path = RETIRED_DIR) -> Path:
    """Move a state and its sidecars (.fp.json, .goals.json) into ``retired_dir`` - a rename, never a delete - and log
    one ``<UTC ISO>\\t<name>\\t<why>`` line in RETIRED.log. Returns where the state went."""
    if not why or not str(why).strip():
        raise ValueError("retire() needs a non-empty reason")
    path, retired_dir = Path(path), Path(retired_dir)
    retired_dir.mkdir(parents=True, exist_ok=True)
    sides = [s for s in (statefp.sidecar(path), checkpoint_goals.sidecar(path)) if s.exists()]
    dest = retired_dir / path.name
    os.replace(path, dest)
    for s in sides:
        os.replace(s, retired_dir / s.name)
    with (retired_dir / "RETIRED.log").open("a", encoding="utf-8") as fh:
        fh.write(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')}\t{path.name}\t{why}\n")
    return dest


def bad(entry: Entry) -> str | None:
    """The reason a state is bad (``list --bad``, ``check``): no sidecar, a stale ``v``, or a ship-stage checkpoint
    whose blackout respawns behind Vermilion. None = nothing wrong on record."""
    if not entry.fp:
        return "no fingerprint sidecar"
    if entry.fp.get("v", 0) < statefp.VERSION:
        return f"stale fingerprint (v{entry.fp.get('v', 0)}, want {statefp.VERSION})"
    if entry.stem in checkpoint_goals.SHIP_GOALS and entry.fp.get("respawn") in checkpoint_goals.BEHIND_VERMILION:
        return f"ship checkpoint respawns behind Vermilion (map {entry.fp['respawn']})"
    return None
