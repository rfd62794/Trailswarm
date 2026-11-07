"""Which goals a save state had COMPLETED when it was written, and whether it may start a curriculum segment.

A checkpoint is named after the goal it was written at, but goals can be reached out of order (an agent wandering into the
Cerulean bike shop sets ``bike_shop`` long before the Bill goals). Starting the next segment from such a state would send
agents at a goal whose prerequisites never happened. So every checkpoint gets a sidecar ``<state>.goals.json`` listing the
goals complete at that moment, and a segment may start from it only if every EARLIER selectable goal is in that list.
A checkpoint with no sidecar (written before this existed) is accepted only when every earlier selectable goal also has a
checkpoint file: a gap in the chain proves it was reached out of order.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable, Iterable

SUFFIX = ".goals.json"


def sidecar(state: Path) -> Path:
    return Path(state).with_name(Path(state).name + SUFFIX)


def completed_goals(goals: dict, initial: Iterable[str], order: Iterable[str]) -> list[str]:
    """Goals complete now: detectors that read true plus those assumed from the start checkpoint, in ladder order."""
    done = set(initial)
    return [g for g in order if goals.get(g) or g in done]


def write_completed(state: Path, completed: Iterable[str]) -> None:
    tmp = sidecar(state).with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps({"completed": sorted(completed)}), encoding="utf-8")
    os.replace(tmp, sidecar(state))


def read_completed(state: Path) -> set[str] | None:
    try:
        return set(json.loads(sidecar(state).read_text(encoding="utf-8"))["completed"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def copy_sidecar(src: Path, dst: Path) -> None:
    if sidecar(src).exists():
        import shutil
        shutil.copyfile(sidecar(src), sidecar(dst))


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
