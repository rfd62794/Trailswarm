"""runs/novelty.json (global counts) and per-run deltas; the merge pattern is bandit.store's (lock, per-run replace).

A feature's count is the NUMBER OF RUNS that found it. A delta is one run's cumulative finds
``{"run_id", "role", "found": {key: unix ts}, "stage": {flag key: goal index}}``, rewritten on every new feature, so a
stall-kill loses nothing. Merging a delta twice replaces that run's share rather than adding it again.
"""
from __future__ import annotations

import json
from pathlib import Path

from pokeagent.bandit.store import _lock  # same lock handling as the bandit table
from pokeagent.qmodels import atomic_json

MAX_MERGED_IDS = 5000
MAX_RECENT = 30  # runs whose key lists are kept so a re-flushed delta can replace its earlier share


def empty() -> dict:
    return {"counts": {}, "first": {}, "stage": {}, "role_runs": {}, "merged": [], "recent": {}}


def load_table(path: Path | str) -> dict:
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return {**empty(), **d} if isinstance(d, dict) else empty()
    except (OSError, ValueError):
        return empty()


def write_delta(path: Path | str, run_id: str, role: str, found: dict, stage: dict) -> None:
    atomic_json(path, {"run_id": run_id, "role": role, "found": found, "stage": stage})


def delta_path_for(own: Path) -> Path:
    """The novelty delta a swarm agent writes beside its memory file (agent3-7.json -> agent3-7.novelty.json)."""
    return own.with_name(own.stem + ".novelty.json")


def _bump(counts: dict, keys, sign: int) -> None:
    for k in keys:
        counts[k] = counts.get(k, 0) + sign
        if counts[k] <= 0:
            del counts[k]


def apply_delta(table: dict, d: dict) -> bool:
    """Fold one run's cumulative delta into ``table`` (in place); True when it changed."""
    run_id, found = d["run_id"], d["found"]
    keys = sorted(found)
    recent, merged = table["recent"], table["merged"]
    if run_id in recent:
        if sorted(recent[run_id]) == keys and not _stage_news(table, d):
            return False
        _bump(table["counts"], recent[run_id], -1)
        _bump(table["counts"], keys, +1)
    elif run_id in merged:
        return False
    else:
        _bump(table["counts"], keys, +1)
        rr = table["role_runs"]
        rr[d.get("role", "")] = rr.get(d.get("role", ""), 0) + 1
    for k, ts in found.items():
        cur = table["first"].get(k)
        if cur is None or ts < cur[0]:
            table["first"][k] = [ts, d.get("role", ""), run_id]
    for k, s in d.get("stage", {}).items():
        table["stage"][k] = min(s, table["stage"].get(k, s))
    recent[run_id] = keys
    for old in list(recent)[:-MAX_RECENT]:
        del recent[old]
    if run_id not in merged:
        merged.append(run_id)
        del merged[:-MAX_MERGED_IDS]
    return True


def _stage_news(table: dict, d: dict) -> bool:
    return any(s < table["stage"].get(k, 10 ** 9) for k, s in d.get("stage", {}).items())


def merge_delta(shared: Path | str, delta: Path | str, remove: bool = True) -> bool:
    shared, delta = Path(shared), Path(delta)
    try:
        d = json.loads(delta.read_text(encoding="utf-8"))
        d["run_id"], d["found"]
    except (OSError, ValueError, KeyError, TypeError):
        return False
    with _lock(shared):
        table = load_table(shared)
        changed = apply_delta(table, d)
        if changed:
            atomic_json(shared, table)
    if remove:
        delta.unlink(missing_ok=True)
    return changed
