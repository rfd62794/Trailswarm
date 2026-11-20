"""Trainer engagement survey: for each trainer sprite on the map, walk the player toward it one tile per step
and record, per tile, the BIT_SEEN_BY_TRAINER signal (wMiscFlags bit 0) and its 0 -> 1 edge.

The survey does NOT navigate: it measures from a start state that already stands on the trainer's sight line
(same column for a trainer facing up/down, same row for left/right); a trainer the player is not lined up with is
reported ``off_line`` with no presses. ``engaged_class`` is never read as a signal (stale byte). Every tile is one
JSONL row under ``<out_dir>/<DIR_NAME>/``; each trainer starts from a fresh scratch copy. Buttons and reads only.
"""
from __future__ import annotations

import json
from pathlib import Path

from pokeagent.emulator import Button
from pokeagent.glitch_signals import engaged_now, engagement_edge, read_signals
from pokeagent.glitchlab.scratch import report_path, scratch_copy
from pokeagent.glitchlab.sprites import read_trainer_sprites
from pokeagent.glitchlab.trainer_escape import default_menu_probe
from pokeagent.knowledge.trainers import trainers_on
from pokeagent.novelty.discoveries import DIR_NAME
from pokeagent.ram import RAM_MAP

MAX_RUNS = 60   # trainers surveyed per call; beyond it the survey stops aborted:"cap"


def _side(t, px, py):
    """(distance, button toward the trainer) when the player stands on the trainer's facing sight line, else None."""
    if t.facing == "down" and px == t.x and py > t.y:
        return py - t.y, Button.UP
    if t.facing == "up" and px == t.x and py < t.y:
        return t.y - py, Button.DOWN
    if t.facing == "left" and py == t.y and px < t.x:
        return t.x - px, Button.RIGHT
    if t.facing == "right" and py == t.y and px > t.x:
        return px - t.x, Button.LEFT
    return None


def _label(t, kb, map_id):
    """The kb class name for the sprite at t.x,t.y when a kb is given, else the raw class byte."""
    if kb is not None:
        try:
            for r in trainers_on(map_id, kb):
                if (r.get("x"), r.get("y")) == (t.x, t.y):
                    return r.get("class")
        except Exception:  # noqa: BLE001
            pass
    return t.cls


def _walk(emu, t, menu_probe, max_steps):
    """Rows for one trainer's approach plus (reason, engage_dist, start_before_engage)."""
    px, py = emu.read(RAM_MAP["player_x"]), emu.read(RAM_MAP["player_y"])
    side = _side(t, px, py)
    if side is None:
        return [], "off_line", None, False
    dist, button = side
    rows, prev, reason, edist, sbe = [], None, None, None, False
    for _ in range(max_steps):
        if dist <= 1:
            break
        emu.press(button)
        nx, ny = emu.read(RAM_MAP["player_x"]), emu.read(RAM_MAP["player_y"])
        if (nx, ny) == (px, py):
            reason = "blocked"
            break
        px, py = nx, ny
        dist = abs(px - t.x) + abs(py - t.y)
        sig = read_signals(emu)
        edge = engagement_edge(prev, sig) if prev is not None else None
        rows.append({"dist": dist, "player_x": px, "player_y": py, "seen_by_trainer": bool(sig.misc_flags & 1),
                     "engaged": engaged_now(sig), "edge": edge, "in_battle": sig.in_battle,
                     "misc_flags": sig.misc_flags, "status5": sig.status5, "start_opened": None})
        prev = sig
        if edge is not None:
            edist = dist
            break
    if edist is None and reason is None and rows and dist <= 1:
        emu.press(Button.START)
        try:
            opened = menu_probe(emu)
        except Exception:  # noqa: BLE001
            opened = None
        rows[-1]["start_opened"] = opened
        sbe = bool(opened) and not rows[-1]["engaged"]
    return rows, reason, edist, sbe


def survey_map(emu_factory, state, map_id, kb, *, out_dir, menu_probe=None, name=None, max_steps=12,
               distances=None, approach_presses=None) -> dict:
    """Survey every trainer sprite on ``map_id``. ``emu_factory(state_path)`` returns an emulator booted from a
    state copy. ``kb`` (may be None) only labels a sprite's class name by x,y; ``distances`` and
    ``approach_presses`` are accepted for call compatibility and ignored."""
    out_dir = Path(out_dir)
    report = report_path(out_dir, name or f"survey-{map_id}")
    report.parent.mkdir(parents=True, exist_ok=True)
    scratch_root = out_dir / DIR_NAME
    menu_probe = menu_probe or default_menu_probe
    emu = emu_factory(scratch_copy(state, scratch_root))
    try:
        sprites = read_trainer_sprites(emu)
    finally:
        emu.close()
    summary = {"map": map_id, "report": str(report), "runs": 0, "trainers": []}
    with report.open("w", encoding="utf-8") as fh:
        for t in sprites:
            if summary["runs"] >= MAX_RUNS:
                summary["aborted"] = "cap"
                break
            emu = emu_factory(scratch_copy(state, scratch_root))
            try:
                rows, reason, edist, sbe = _walk(emu, t, menu_probe, max_steps)
            finally:
                emu.close()
            summary["runs"] += 1
            cls = _label(t, kb, map_id)
            for r in rows or [{"reason": reason}]:
                fh.write(json.dumps({"map": map_id, "slot": t.slot, "class": cls, "x": t.x, "y": t.y,
                                     "facing": t.facing, **r}) + "\n")
            summary["trainers"].append({"slot": t.slot, "class": cls, "x": t.x, "y": t.y, "facing": t.facing,
                                        "engage_dist": edist, "start_before_engage": sbe, "reason": reason})
    return summary
