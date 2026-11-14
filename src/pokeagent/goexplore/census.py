"""Offline cell census over existing run logs: how many distinct cells real runs yield (plan D2, slice 1).

Reads ``decisions.jsonl`` (press rows only) and ``goal_frames.jsonl`` from each run dir. The logs carry
position and the ladder stage only, so the census measures the position x goals part of the cell key;
``flag_popcount`` and ``party_level_bucket`` are RAM-only and reported under ``not_in_logs``.
"""
from __future__ import annotations

from pathlib import Path

from pokeagent.goals import GOALS
from pokeagent.goexplore.cell import Cell, from_log_row, goals_reached
from pokeagent.review.load import jsonl

NOT_IN_LOGS = ["flag_popcount", "party_level_bucket"]
BLOCK_SWEEP = (1, 2, 4, 8)


def press_rows(run_dir: Path, skipped: dict | None = None) -> list[dict]:
    """decisions.jsonl press rows: no "event" key, int map/x/y, str goal_stage; the rest dropped."""
    rows, bad = [], 0
    for r in jsonl(Path(run_dir) / "decisions.jsonl", skipped):
        if "event" in r:
            continue
        if isinstance(r.get("map"), int) and isinstance(r.get("x"), int) \
                and isinstance(r.get("y"), int) and isinstance(r.get("goal_stage"), str):
            rows.append(r)
        else:
            bad += 1
    if bad and skipped is not None:
        skipped["bad_rows"] = skipped.get("bad_rows", 0) + bad
    return rows


def _ladder_goals_logged(run_dir: Path) -> list[str]:
    """goal_frames.jsonl ladder goals in log order; skipped-settled rows and non-ladder goals ignored."""
    out = []
    for r in jsonl(Path(run_dir) / "goal_frames.jsonl"):
        if r.get("skipped"):
            continue
        g = r.get("goal")
        if g in GOALS:
            out.append(g)
    return out


def _out_of_order(logged: list[str]) -> list[str]:
    """Goals logged at a lower GOALS index than a goal logged before them."""
    out, best = [], -1
    for g in logged:
        i = GOALS.index(g)
        if i < best:
            out.append(g)
        best = max(best, i)
    return out


def census(run_dirs: list[Path]) -> dict:
    """The slice-1 census dict over every run dir that yields at least one usable press row."""
    cells: set[Cell] = set()
    per_run: dict[str, int] = {}
    by_goals: dict[str, set[Cell]] = {}
    sweep = {b: set() for b in BLOCK_SWEEP}
    monotone: dict[str, int] = {}
    out_of_order: dict[str, list[str]] = {}
    runs = rows_n = skipped_rows = 0
    for d in run_dirs:
        d = Path(d)
        skipped: dict = {}
        rows = press_rows(d, skipped)
        skipped_rows += sum(skipped.values())          # corrupt lines + rows with missing fields
        usable = [(r, goals_reached(r["goal_stage"])) for r in rows]
        skipped_rows += sum(1 for _, g in usable if g is None)
        usable = [(r, g) for r, g in usable if g is not None]
        if not usable:
            continue
        runs += 1
        rows_n += len(usable)
        run_cells, prev, drops = set(), -1, 0
        for r, g in usable:
            c = from_log_row(r, g)
            cells.add(c)
            run_cells.add(c)
            by_goals.setdefault(str(g), set()).add(c)
            for b in sweep:
                sweep[b].add((r["map"], r["x"] // b, r["y"] // b, g))
            drops += g < prev
            prev = g
        per_run[d.name] = len(run_cells)
        if drops:
            monotone[d.name] = drops
        if ooo := _out_of_order(_ladder_goals_logged(d)):
            out_of_order[d.name] = ooo
    return {"runs": runs, "rows": rows_n, "skipped_rows": skipped_rows, "cells": len(cells),
            "cells_per_run": per_run,
            "cells_by_goals": {k: len(v) for k, v in sorted(by_goals.items(), key=lambda kv: int(kv[0]))},
            "block_sweep": {str(b): len(sweep[b]) for b in BLOCK_SWEEP},
            "monotone_violations": monotone, "out_of_order_goals": out_of_order, "not_in_logs": NOT_IN_LOGS}
