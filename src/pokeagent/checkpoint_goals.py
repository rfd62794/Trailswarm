"""Which goals a save state had COMPLETED when it was written, and whether it may start a curriculum segment.

A checkpoint is named after the goal it was written at, but goals can be reached out of order (an agent wandering into the
Cerulean bike shop sets ``bike_shop`` long before the Bill goals). Starting the next segment from such a state would send
agents at a goal whose prerequisites never happened. So every checkpoint gets a sidecar ``<state>.goals.json`` listing the
goals complete at that moment, and a segment may start from it only if every EARLIER selectable goal is in that list.
A checkpoint with no sidecar (written before this existed) is accepted only when every earlier selectable goal also has a
checkpoint file: a gap in the chain proves it was reached out of order.
"""
from __future__ import annotations
from pokeagent.fsutil import replace_retry

import json
import logging
import os
from pathlib import Path
from typing import Callable, Iterable

_log = logging.getLogger(__name__)

SUFFIX = ".goals.json"


def sidecar(state: Path) -> Path:
    return Path(state).with_name(Path(state).name + SUFFIX)


def completed_goals(goals: dict, initial: Iterable[str], order: Iterable[str]) -> list[str]:
    """Goals complete now: detectors that read true plus those assumed from the start checkpoint, in ladder order."""
    done = set(initial)
    return [g for g in order if goals.get(g) or g in done]


def write_completed(state: Path, completed: Iterable[str], respawn: int | None = None) -> None:
    """``respawn`` = wLastBlackoutMap (0xD719) when the state was written: where a blackout from this state lands."""
    tmp = sidecar(state).with_suffix(f".{os.getpid()}.tmp")
    rec = {"completed": sorted(completed)}
    if respawn is not None:
        rec["respawn"] = respawn
    tmp.write_text(json.dumps(rec), encoding="utf-8")
    replace_retry(tmp, sidecar(state))


# Segments aboard / at the S.S. Anne: a blackout must land in Vermilion (5) or beyond. Pallet 0, Viridian 1, Pewter 2 and
# Cerulean 3 are behind it (2026-11-06: a ship segment saved with respawn 3 sent every run back to Cerulean).
SHIP_GOALS = frozenset({"to_ss_anne", "ss_anne_2f", "rival_ss_anne", "ss_anne_captain"})
BEHIND_VERMILION = frozenset({0, 1, 2, 3})


def read_respawn(state: Path) -> int | None:
    """The state's recorded respawn map: the goals sidecar first, else its RAM fingerprint (statefp), else unknown."""
    try:
        r = json.loads(sidecar(state).read_text(encoding="utf-8")).get("respawn")
    except (OSError, ValueError, TypeError, AttributeError):
        r = None
    if not isinstance(r, int):
        from pokeagent import statefp
        r = (statefp.read(state) or {}).get("respawn")
    return r if isinstance(r, int) else None


def respawn_behind(name: str, state: Path | None) -> bool:
    """True when the checkpoint ``name`` belongs to a ship segment and its recorded respawn point is behind Vermilion
    (a state with no record is unknown, not behind)."""
    return state is not None and name.split("@", 1)[0] in SHIP_GOALS and read_respawn(state) in BEHIND_VERMILION


def read_completed(state: Path) -> set[str] | None:
    try:
        return set(json.loads(sidecar(state).read_text(encoding="utf-8"))["completed"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


_LINEAGE_LOGGED: set[str] = set()


def _lineage_note(key: str, text: str) -> None:
    """One log line per distinct reason per process: the provenance read is per run, not per step."""
    if key not in _LINEAGE_LOGGED:
        _LINEAGE_LOGGED.add(key)
        _log.warning("%s", text)


def start_lineage(state_path) -> str:
    """Record provenance for a run (the standing rule): the start state's lineage - 'organic' | 'synthetic' |
    'unknown' when there is no state or no lineage record, never guessed. A 'promoted' start counts as organic
    (its organic equivalence was verified); an unreadable statefp reads 'unknown'."""
    try:
        from pokeagent import statefp
        fp = statefp.read(Path(state_path)) if state_path else None
    except Exception as exc:  # noqa: BLE001
        _lineage_note("error", f"start_lineage: statefp read failed ({exc!r}): provenance 'unknown'")
        return "unknown"
    if fp is None:
        if state_path:
            _lineage_note("norecord", f"start_lineage: no readable fingerprint beside {state_path}: provenance 'unknown'")
        return "unknown"
    return {"organic": "organic", "synthetic": "synthetic", "promoted": "organic"}.get(statefp.lineage_of(fp), "unknown")


def stamp_fingerprint(emu, state: Path, source_run: str | None = None, *, inherit=None) -> None:
    """A fresh RAM fingerprint (statefp) beside a just-written checkpoint state; the caller's try keeps it best effort.
    ``inherit`` is the run's start state: a non-organic start's lineage is carried into the new fingerprint."""
    from pokeagent import statefp
    statefp.stamp(emu, state, source_run, inherit=inherit)


def copy_sidecar(src: Path, dst: Path) -> None:
    import shutil
    from pokeagent import statefp
    for side in (sidecar, statefp.sidecar):
        if side(src).exists():
            shutil.copyfile(side(src), side(dst))


def required(name: str, order: tuple[str, ...]) -> list[str]:
    """Goals that must be complete in a checkpoint called ``name``: every selectable goal before its goal, and the goal
    itself unless ``name`` is a sub-segment checkpoint (``goal@map``), which lies inside the goal."""
    goal = name.split("@", 1)[0]
    if goal not in order:
        return []
    i = order.index(goal)
    return list(order[:i]) if "@" in name and not name.endswith("@end") else list(order[:i + 1])


def valid(name: str, state: Path | None, order: tuple[str, ...], has_checkpoint: Callable[[str], bool]) -> bool:
    """May the checkpoint ``state`` (called ``name``) start a segment? See the module docstring."""
    if state is None:
        return False
    from pokeagent.novelty.discoveries import is_discovery_state
    if is_discovery_state(state):
        return False  # a discovery save may be glitch-corrupted: evidence for review, never a starting point
    need = required(name, order)
    done = read_completed(state)
    if done is not None:
        return set(need) <= done
    return all(has_checkpoint(g) for g in need)   # legacy: no gap in the chain
