"""XP measurement: per-member XP over rolling step windows (measurement only, no decision logic reads it).

``PartyLog.end_battle`` hands each battle's before/after party to ``on_battle``; the engine calls ``tick`` every
step. Each ``WINDOW`` steps one row per member is appended to ``<run>/xp_rates.jsonl`` and the (map, level band)
ledger (``xp_spots.py``) is updated; ``finish`` (run shutdown) flushes the partial window and writes a per-map
summary. Members are keyed by identity (OT id + DVs, as ``party_log._match``), so the lowest-first party order
moving slots does not matter. "Switched" = the member gained XP in a battle but was not slot 0 at battle start
(it was swapped in or shared the fight); "solo" = it was the starting lead. Never raises.
"""
from __future__ import annotations

import json
from pathlib import Path
from collections import Counter, defaultdict
from typing import Any

from pokeagent.explorer import xp_spots, xp_report

WINDOW = 1000        # steps per window
CONSOLE_EVERY = 1000  # steps between [xp] console lines
MIN_MAP_STEPS = 100   # steps on a map before a window's rate there enters the ledger
FILE = "xp_rates.jsonl"


def member_key(m: tuple, slot: int = 0) -> str:
    ident = m[6] if len(m) > 6 else None
    return f"{ident[0]:04x}-{ident[1]:04x}" if ident else f"slot{slot}"


class XpMeter:
    def __init__(self, window: int = WINDOW, spots: xp_spots.XpSpots | None = None) -> None:
        self.window = window
        self.spots = spots
        self.start_step: int | None = None
        self.roster: dict[str, tuple] = {}              # key -> (species, level), latest seen
        self.acc: dict[str, dict] = {}                  # key -> window accumulator
        self.map_steps: Counter = Counter()             # window: steps per map
        self.totals: dict[int, dict] = defaultdict(lambda: {"steps": 0, "xp": 0, "battles": 0})  # run: per map
        self.latest: dict[str, float] = {}              # key -> last window's xp_per_1k_steps
        self.last_console: int | None = None

    def _a(self, key: str) -> dict:
        return self.acc.setdefault(key, {"xp": 0, "battles": 0, "solo": 0, "switched": 0, "maps": Counter(), "mb": Counter()})

    def on_battle(self, ctx, before: list, after: list) -> None:
        """One finished battle: credit each XP-gaining member (matched by identity, so re-orders gain nothing)."""
        from pokeagent.explorer.party_log import _match
        lead = member_key(before[0]) if before else None
        mp = ctx.view.m if ctx.view is not None else None
        for i, b in enumerate(_match(before, after)):
            a = after[i]
            key = member_key(a, i)
            self.roster[key] = (a[0], a[1])
            if b is None or a[2] <= b[2]:
                continue
            acc = self._a(key)
            acc["xp"] += a[2] - b[2]
            acc["battles"] += 1
            acc["solo" if key == lead else "switched"] += 1
            acc["maps"][mp] += a[2] - b[2]
            acc["mb"][mp] += 1
            t = self.totals[mp]
            t["xp"] += a[2] - b[2]
            t["battles"] += 1

    def tick(self, ctx) -> None:
        try:
            if self.start_step is None:
                self.start_step = ctx.step - 1  # this tick is already a step of the window
            mp = ctx.view.m if ctx.view is not None else None
            self.map_steps[mp] += 1
            self.totals[mp]["steps"] += 1
            if ctx.step - self.start_step >= self.window:
                self.flush(ctx)
        except Exception:
            pass

    def flush(self, ctx) -> list[dict]:
        """Close the window: append one row per member, feed the ledger, maybe print the console line."""
        steps = max(1, ctx.step - (self.start_step if self.start_step is not None else ctx.step))
        try:
            from pokeagent.explorer import party_log
            for i, m in enumerate(party_log.snapshot(ctx.emu)):
                self.roster[member_key(m, i)] = (m[0], m[1])
        except Exception:
            pass
        rows = []
        for key, (species, level) in self.roster.items():
            a = self.acc.get(key) or self._a(key)
            top = a["maps"].most_common(1)
            row = {"step": ctx.step, "member": key, "species": species, "level": level, "xp_gain": a["xp"], "steps": steps,
                   "battles": a["battles"], "map": top[0][0] if top else (ctx.view.m if ctx.view is not None else None),
                   "xp_per_1k_steps": round(a["xp"] * 1000 / steps, 2), "solo": a["solo"], "switched": a["switched"],
                   "xp_per_battle": round(a["xp"] / a["battles"], 2) if a["battles"] else 0.0, "kind": "window"}
            rows.append(row)
            self.latest[key] = row["xp_per_1k_steps"]
            self._ledger(ctx, a, level)
        self._write(ctx, rows)
        self._console(ctx, rows)
        self.acc, self.map_steps, self.start_step = {}, Counter(), ctx.step
        return rows

    def _ledger(self, ctx, a: dict, level: int) -> None:
        try:
            if a["battles"] == 0:
                return
            if self.spots is None:
                # the shared ledger sits next to the per-run dirs (runs/xp_spots.json), never relative to the CWD
                self.spots = xp_spots.XpSpots.load(Path(ctx.run_dir).parent / xp_spots.FILE)
            for mp, xp in a["maps"].items():
                st = self.map_steps.get(mp, 0)
                if mp is not None and st >= MIN_MAP_STEPS:
                    nb = a["mb"][mp]
                    self.spots.record(mp, level, xp * 1000 / st, nb * 1000 / st, xp / nb)
            self.spots.save()
        except Exception:
            pass

    def _console(self, ctx, rows: list[dict]) -> None:
        try:
            if self.last_console is not None and ctx.step - self.last_console < CONSOLE_EVERY:
                return
            line = xp_report.console_line(rows)
            if line:
                self.last_console = ctx.step
                ctx.log(line, "res")
        except Exception:
            pass

    def _write(self, ctx, rows: list[dict]) -> None:
        try:
            with (ctx.run_dir / FILE).open("a", encoding="utf-8") as fh:
                for r in rows:
                    fh.write(json.dumps(r) + "\n")
        except Exception:
            pass

    def finish(self, ctx) -> None:
        """Run end: flush the partial window, then one ``map_summary`` row per map this run trained on."""
        try:
            if self.start_step is not None and ctx.step > self.start_step:
                self.flush(ctx)
            self._write(ctx, [{"step": ctx.step, "kind": "map_summary", "map": m, **t,
                               "xp_per_1k_steps": round(t["xp"] * 1000 / t["steps"], 2) if t["steps"] else 0.0}
                              for m, t in self.totals.items() if t["battles"]])
        except Exception:
            pass


def of(ctx) -> XpMeter:
    if getattr(ctx, "xp_meter", None) is None:
        ctx.xp_meter = XpMeter()
    return ctx.xp_meter
