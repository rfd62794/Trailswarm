"""XP and level logging: party snapshots at battle start/end, the per-battle diff, and the per-run level timeline.

Battle records (runs/battles.jsonl) gain ``party_before``/``party_after`` (rows of [species, level, exp, hp, max_hp],
species = the internal id the game stores), ``exp_gained`` (per member), ``level_ups``, ``evolved`` and
``moves_learned``. Every battle end and every out-of-battle level/exp change also appends a line to
``<run>/levels.jsonl``. Everything here is best effort: a failure must never end a run (see docs/KNOWLEDGE.md).
"""
from __future__ import annotations

import json
from collections import Counter
from typing import Any

from pokeagent.explorer.economy import ledger
from pokeagent.explorer.perceive import lead_level
from pokeagent.goals import bag_contents
from pokeagent.ramstructs import read_party
from pokeagent.ramworld import read_money

Member = tuple  # (species, level, exp, hp, max_hp, moves)


def snapshot(emu) -> list[Member]:
    """The party from RAM (verified party struct: species, level, 3-byte big-endian exp, hp, max hp, move ids)."""
    return [(m.species, m.level, m.exp, m.hp, m.max_hp, tuple(m.moves)) for m in read_party(emu)]


def rows(snap: list[Member]) -> list[list[int]]:
    return [list(m[:5]) for m in snap]


def diff(before: list[Member], after: list[Member]) -> dict[str, Any]:
    """Compare two snapshots slot by slot (a mon caught in between has no 'before' and counts as 0 gained)."""
    exp_gained, level_ups, evolved, moves_learned = [], [], [], []
    for i, a in enumerate(after):
        b = before[i] if i < len(before) else None
        if b is None:
            exp_gained.append(0)
            continue
        exp_gained.append(a[2] - b[2])
        if a[1] > b[1]:
            level_ups.append({"slot": i, "species": a[0], "from": b[1], "to": a[1]})
        if a[0] != b[0]:
            evolved.append({"slot": i, "from": b[0], "to": a[0]})
        new = [mv for mv in a[5] if mv and mv not in b[5]]
        if new:
            moves_learned.append({"slot": i, "species": a[0], "moves": new})
    return {"exp_gained": exp_gained, "level_ups": level_ups, "evolved": evolved, "moves_learned": moves_learned}


def _key(snap: list[Member]) -> list[tuple]:
    return [(m[0], m[1], m[2]) for m in snap]


class PartyLog:
    """One per run: remembers the party at battle start, the last party seen, and the run's totals."""

    def __init__(self) -> None:
        self.before: list[Member] | None = None
        self.prev: list[Member] | None = None
        self.money_before: int | None = None
        self.potions_before: int | None = None
        self.exp_total = 0
        self.levels_by_slot: Counter = Counter()
        self.blackouts = 0
        self.grind_steps = 0
        self.travel_steps = 0
        self.battle_steps = 0

    # -- battle hooks (called from behaviours/battle.py) --
    def start_battle(self, ctx) -> None:
        try:
            self.before = snapshot(ctx.emu)
        except Exception:
            self.before = None
        try:
            self.money_before, self.potions_before = read_money(ctx.emu), bag_contents(ctx.emu).get(0x14, 0)
        except Exception:
            self.money_before = self.potions_before = None

    def end_battle(self, ctx, won: bool, fled: bool) -> dict:
        """The new battle-record fields; also appends the levels.jsonl line. Never raises.
        party_before comes from the battle-start snapshot, party_after from RAM now: a failed read leaves a
        ``party_error`` (repr of the exception) on the record instead of silently dropping the whole party."""
        out: dict = {}
        before, self.before = self.before, None
        try:
            after = snapshot(ctx.emu)
        except Exception as exc:  # noqa: BLE001
            after = None
            out["party_error"] = repr(exc)
        if before is None:
            before = after  # no start snapshot: the after read stands in for both (as before)
        try:
            if before is not None:
                out["party_before"] = rows(before)
            if after is not None:
                out["party_after"] = rows(after)
        except Exception as exc:  # noqa: BLE001
            out.setdefault("party_error", repr(exc))
        if before is not None and after is not None:
            try:
                d = diff(before, after)
                self.exp_total += sum(g for g in d["exp_gained"] if g > 0)
                for lu in d["level_ups"]:
                    self.levels_by_slot[lu["slot"]] += lu["to"] - lu["from"]
                self.prev = after
                self._write(ctx, after, "battle_end", {k: v for k, v in d.items() if k != "exp_gained" and v})
                out.update(d)
            except Exception as exc:  # noqa: BLE001
                out.setdefault("party_error", repr(exc))
        if not won and not fled:
            self.blackouts += 1
        out.update(self._money(ctx, won, fled))
        return out

    def _money(self, ctx, won: bool, fled: bool) -> dict:
        """money_before / money_after for the battle record; the ledger books the prize or the blackout loss."""
        try:
            after = read_money(ctx.emu)
            before, self.money_before = (after if self.money_before is None else self.money_before), None
            ledger.of(ctx).battle(before, after, won, fled)
            return {"money_before": before, "money_after": after, "potions_before": self.potions_before}
        except Exception:
            return {}

    # -- every step (called from the engine) --
    def tick(self, ctx) -> None:
        try:
            self._count_steps(ctx)
            if ctx.in_battle or ctx.view.battling:
                return
            ledger.of(ctx).tick(ctx)
            now = snapshot(ctx.emu)
            if self.prev is None:
                self.prev = now
                self._write(ctx, now, "start", {})
            elif _key(now) != _key(self.prev):
                d = diff(self.prev, now)
                self.exp_total += sum(g for g in d["exp_gained"] if g > 0)
                for lu in d["level_ups"]:
                    self.levels_by_slot[lu["slot"]] += lu["to"] - lu["from"]
                self.prev = now
                self._write(ctx, now, "out_of_battle", {k: v for k, v in d.items() if k != "exp_gained" and v})
        except Exception:
            pass

    def _count_steps(self, ctx) -> None:
        if ctx.in_battle or ctx.view.battling:
            self.battle_steps += 1
        elif 0 < lead_level(ctx.emu) < ctx.train_need:  # the training gate plan_goal set: grass-seeking below it
            self.grind_steps += 1
        else:
            self.travel_steps += 1

    def _write(self, ctx, party: list[Member], cause: str, extra: dict) -> None:
        line = {"step": ctx.step, "frame": ctx.frame, "map": ctx.view.m if ctx.view is not None else None,
                "cause": cause, "party": rows(party), **extra}
        with (ctx.run_dir / "levels.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line) + "\n")

    def summary(self, ctx) -> dict:
        return {"exp_gained": self.exp_total, "levels_gained_by_slot": {str(k): v for k, v in sorted(self.levels_by_slot.items())},
                "battles": ctx.battles, "battles_won": ctx.battles_won, "blackouts": self.blackouts,
                "steps_grinding": self.grind_steps, "steps_travelling": self.travel_steps, "steps_in_battle": self.battle_steps}


def of(ctx) -> PartyLog:
    if ctx.party_log is None:
        ctx.party_log = PartyLog()
    return ctx.party_log
