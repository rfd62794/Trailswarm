"""Trainer sight survey: a scripted approach toward each kb trainer on a map, from each start
distance, one tile per step, with START pressed on the last (adjacent) tile's step.

The kb rows carry no facing and no sight range (trainer_route.SIGHT_GUESS is an UNVERIFIED
guess), so this MEASURES: per tile, whether the engaged-trainer byte went nonzero and whether
the Start menu still opened. Every (trainer, distance, tile) is one JSONL row under
``<out_dir>/<DIR_NAME>/``; each run starts from a fresh scratch copy of the state. Buttons
and reads only.
"""
from __future__ import annotations

import json
from pathlib import Path

from pokeagent.glitch_signals import read_signals
from pokeagent.glitchlab.scratch import report_path, scratch_copy
from pokeagent.glitchlab.script import load_script, run_script
from pokeagent.glitchlab.trainer_escape import default_menu_probe
from pokeagent.knowledge.trainers import trainers_on
from pokeagent.novelty.discoveries import DIR_NAME

MAX_RUNS = 60   # (trainer x distance) runs per call; beyond it the survey stops aborted:"cap"


def approach_steps(trainer, d, presses=("UP",)) -> list[dict]:
    """Tile-by-tile step dicts for a scripted approach from ``d`` tiles out down to 1; the
    last tile's step also presses START (the tile the trainer must have spotted us on)."""
    out = []
    for tile in range(d, 0, -1):
        press = list(presses) + (["START"] if tile == 1 else [])
        out.append({"id": f"d{d}_t{tile}", "press": press})
    return out


def survey_map(emu_factory, state, map_id, kb, *, distances=(2, 3, 4, 5, 6),
               approach_presses=("UP",), out_dir, menu_probe=None, name=None) -> dict:
    """Survey every trainer on ``map_id``. ``emu_factory(state_path)`` returns an emulator
    already booted from a state copy (PyBoy in real runs, FakeEmulator timelines in tests).
    Writes the per-tile JSONL report and returns the summary dict."""
    out_dir = Path(out_dir)
    report = report_path(out_dir, name or f"survey-{map_id}")
    report.parent.mkdir(parents=True, exist_ok=True)
    scratch_root = out_dir / DIR_NAME  # scratch copies sit beside the report, inside the discoveries dir
    menu_probe = menu_probe or default_menu_probe

    def probe(emu) -> dict:
        sig = read_signals(emu)
        try:
            opened = menu_probe(emu)
        except Exception:  # noqa: BLE001
            opened = None
        return {"engaged": sig.engaged_class, "misc_flags": sig.misc_flags,
                "status5": sig.status5, "start_opened": opened}

    summary = {"map": map_id, "report": str(report), "runs": 0, "trainers": []}
    with report.open("w", encoding="utf-8") as fh:
        for tidx, t in enumerate(trainers_on(map_id, kb)):
            tsum = {"trainer_idx": tidx, "class": t["class"], "x": t["x"], "y": t["y"],
                    "max_engage_dist": None, "start_before_engage": False}
            for d in distances:
                if summary["runs"] >= MAX_RUNS:
                    summary["aborted"] = "cap"
                    break
                emu = emu_factory(scratch_copy(state, scratch_root))
                try:
                    trace = run_script(emu, load_script(approach_steps(t, d, approach_presses)), probe)
                finally:
                    emu.close()
                summary["runs"] += 1
                engage_dist = None
                for srow, tile in zip(trace, range(d, 0, -1)):
                    rec = {"map": map_id, "trainer_idx": tidx, "class": t["class"],
                           "x": t["x"], "y": t["y"], "dist": tile,
                           "start_opened": srow["ram"]["start_opened"],
                           "engaged": srow["ram"]["engaged"],
                           "misc_flags": srow["ram"]["misc_flags"],
                           "status5": srow["ram"]["status5"]}
                    fh.write(json.dumps(rec) + "\n")
                    if rec["engaged"] and engage_dist is None:
                        engage_dist = tile          # first nonzero going d->1 = farthest spot
                    if rec["start_opened"] and not rec["engaged"]:
                        tsum["start_before_engage"] = True
                if engage_dist is not None:
                    tsum["max_engage_dist"] = max(tsum["max_engage_dist"] or 0, engage_dist)
            summary["trainers"].append(tsum)
            if summary.get("aborted"):
                break
    return summary
