"""The stall bundle: ``runs/stalls/<run>-<reason>-<press>.json`` - the post-mortem one look buys.

Written atomically (tmp + rename via fsutil), sibling to the swarm dossiers but named per episode:
the key is (run, reason, last-goal step), so re-checking the same stall reports the existing file
and a new goal landing starts a new episode (a new bundle, possibly at a new press).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from pokeagent.fsutil import atomic_write_text

SEGMENTS_KEPT = 30   # last map segments summarised, with their press ranges
THINKING_TOP = 8     # most repeated `thinking:` lines kept, with counts


def episode_key(view, reason: str) -> tuple:
    """One stall episode: a new goal landing starts a new key (and so a new bundle)."""
    return (view.name, reason, view.last_goal_press)


def _existing(stalls_dir: Path, key: tuple) -> Path | None:
    for p in sorted(stalls_dir.glob(f"{key[0]}-*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (d.get("run"), d.get("reason"), d.get("last_goal_step")) == key:
            return p
    return None


def build(view, reason: str, hit_codes: list[str]) -> dict:
    pending = view.pending_goals
    return {
        "run": view.name, "tag": view.meta.get("tag"), "step": view.presses, "press": view.presses,
        "reason": reason, "hits": list(hit_codes),
        "map": view.current_map, "pos": view.last_pos,
        "current_goal": pending[0] if pending else "",
        "next_goals": pending[1:4],
        "last_goal": view.last_goal_name or None, "last_goal_step": view.last_goal_press,
        "map_sequence": [{"map": m, "first": f, "last": l} for m, f, l in view.segments[-SEGMENTS_KEPT:]],
        "thinking_top": [{"text": t, "count": n}
                         for t, n in view.thinking_counts().most_common(THINKING_TOP)],
        "stall_count": view.stall_count,
        "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def write(view, reason: str, hit_codes: list[str]) -> tuple[Path | None, bool]:
    """(path, created): the episode's bundle. An existing one is reported and never rewritten;
    an unreadable dir reports (None, False) - a diagnostic must never raise."""
    stalls = view.dir.parent / "stalls"
    try:
        stalls.mkdir(parents=True, exist_ok=True)
        old = _existing(stalls, episode_key(view, reason))
        if old is not None:
            return old, False
        out = stalls / f"{view.name}-{reason}-{view.presses}.json"
        atomic_write_text(out, json.dumps(build(view, reason, hit_codes), indent=1))
        return out, True
    except OSError:
        return None, False
