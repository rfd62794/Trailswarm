"""The trainer ledger: which ROM-placed trainers THIS save has already beaten.

Three layers, on purpose:

- static, shared (per ROM): class / party / tile / prize / XP / flag bit -> ``ctx.mem.data["trainers"]``,
  merged across agents by ``swarm_merge.merge_trainers``;
- per save: ``beaten`` lives in this run's ledger and in ``<run dir>/trainers.json``, NEVER in shared
  memory - a trainer beaten in agent A's game is alive in agent B's (the directive's deliberate
  correction: do NOT merge "beaten" through swarm_merge);
- live truth: the ``wEventFlags`` RAM block, once the controller mines each trainer's bit into
  ``src/pokeagent/data/trainer_flags.json`` (ships ``{}`` until then; the loader tolerates it).

``unknown`` counts as unbeaten for targeting but is never a hazard: talking to a beaten trainer costs a
few presses and resolves to ``talk_no_battle`` (UNVERIFIED: assumes an unbeaten trainer always battles
when spoken to).

This module is the pure half; the thin ctx glue lives in ``explorer/trainer_hooks.py`` and is re-exported
at the bottom so callers (engine, battle, press_interact, demos, Goal Procedures' beaten_trainers seam)
keep one import surface.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

FLAG_LO, FLAG_HI = 0xD747, 0xD886  # wEventFlags block (ramlab.flags.FLAG_LO/FLAG_HI; ramlab is not an explorer layer)
MATCH_MAX_DIST = 6      # how far (Manhattan, tiles) a walked-up NPC may stand from its ROM placement
TALK_WAIT_STEPS = 12    # presses of text with no battle after talking = beaten (UNVERIFIED, see docstring)
LEDGER_SYNC_EVERY = 50  # steps between wEventFlags syncs: RAM is cheap but not per-press
FLAG_LEN = FLAG_HI - FLAG_LO + 1
FLAGS_PATH = Path(__file__).resolve().parent.parent / "data" / "trainer_flags.json"
PROVENANCES = ("organic", "synthetic", "unknown")
BEATEN, UNBEATEN, UNKNOWN = "beaten", "unbeaten", "unknown"


@dataclass
class TrainerEntry:
    """One ROM trainer placement; ``idx`` = index in ``trainers.trainers_on(map)`` (ROM list order)."""

    map: int
    idx: int
    cls: str
    party: int
    x: int
    y: int
    state: str = UNKNOWN         # "beaten" | "unbeaten" | "unknown"
    source: str = ""             # "battle_log" | "flag" | "talk_no_battle" | "initial"
    step: int | None = None
    flag_bit: tuple[int, int] | None = None   # (addr, bit) once the controller has mined it
    mons: tuple = ()                          # ROM party [(level, species)]: sim/XP input, never persisted
    provenance: str = "unknown"               # the run's start-state lineage (standing rule)


class TrainerLedger:
    """Per-run beaten state over the ROM's trainer placements; pure - no ctx, no emulator."""

    def __init__(self, placements: dict[int, list[dict]], flag_bits: dict[str, tuple[int, int]] | None = None,
                 provenance: str = "unknown"):
        self.provenance = provenance if provenance in PROVENANCES else "unknown"
        self.flag_bits = flag_bits or {}
        self._entries: dict[int, list[TrainerEntry]] = {}
        self._talk: dict[tuple[int, int], int] = {}   # (map, idx) -> step the A press first produced text
        self._talk_text: dict[tuple[int, int], int] = {}   # (map, idx) -> probe steps spent with text scrolling (not counted)
        self.avoid_key: tuple | None = None           # (map, dest, unbeaten idxs) the sight-line block was last made for
        self.avoid_until = 0                          # frame the routing-only block expires (re-made quietly after)
        self.party_warned: tuple | None = None        # (battle no., reason) of the last party-read warning
        self._flag_synced = -LEDGER_SYNC_EVERY
        self._restored: dict[str, dict] = {}          # persisted states, applied as maps are added
        for m, rows in placements.items():
            self.add_map(m, rows)

    def add_map(self, map_id: int, rows: list[dict]) -> None:
        """Register a map's ROM placements (``trainers_on`` rows); restored states re-apply."""
        if map_id in self._entries:
            return
        out = []
        for i, r in enumerate(rows):
            e = TrainerEntry(map_id, i, r["class"], r["party"], r["x"], r["y"],
                             flag_bit=self.flag_bits.get(f"{map_id}:{i}"),
                             mons=tuple(tuple(p) for p in (r.get("mons") or ())),
                             provenance=self.provenance)
            saved = self._restored.get(f"{map_id}:{i}")
            if saved:
                e.state, e.source, e.step = saved["state"], saved.get("source", ""), saved.get("step")
                if saved.get("provenance") in PROVENANCES:
                    e.provenance = saved["provenance"]
            out.append(e)
        self._entries[map_id] = out

    def known(self, map_id: int) -> bool:
        return map_id in self._entries

    def entries(self, map_id: int) -> list[TrainerEntry]:
        return self._entries.get(map_id, [])

    def beaten_tiles(self) -> set[tuple[int, int, int]]:
        return {(e.map, e.x, e.y) for es in self._entries.values() for e in es if e.state == BEATEN}

    def needs_flags(self) -> bool:
        return any(e.flag_bit for es in self._entries.values() for e in es)

    def flag_due(self, step: int) -> bool:
        if step - self._flag_synced >= LEDGER_SYNC_EVERY:
            self._flag_synced = step
            return True
        return False

    def mark_beaten(self, map_id: int, idx: int, source: str, step: int) -> None:
        entries = self._entries.get(map_id, [])
        if 0 <= idx < len(entries) and entries[idx].state != BEATEN:
            e = entries[idx]
            e.state, e.source, e.step = BEATEN, source, step

    def match(self, map_id: int, positions: list[tuple[int, int]], enemy_species: list[str] | None = None,
              max_dist: int = MATCH_MAX_DIST) -> int | None:
        """The ROM placement an NPC corresponds to: smallest Manhattan distance to ANY tile it was seen
        on (a trainer that sights the player walks up, so the battle tile is not the placement); ties
        break toward the placement whose ROM party holds the record's enemy species."""
        species = set(enemy_species or ())
        best = None
        for e in self.entries(map_id):
            d = min((abs(e.x - px) + abs(e.y - py) for px, py in positions), default=max_dist + 1)
            if d > max_dist:
                continue
            key = (d, 0 if species & {sp for _lv, sp in e.mons} else 1, e.idx)
            if best is None or key < best[0]:
                best = (key, e.idx)
        return best[1] if best else None

    def sync_flags(self, flags: bytes) -> None:
        """Truth from the live wEventFlags block: a set bit means beaten. A clear bit refines ``unknown``
        to ``unbeaten`` but never erases a state the run itself recorded (battle_log / talk_no_battle)."""
        for es in self._entries.values():
            for e in es:
                if e.flag_bit is None:
                    continue
                off = e.flag_bit[0] - FLAG_LO
                if not 0 <= off < len(flags):
                    continue
                if flags[off] >> e.flag_bit[1] & 1:
                    e.state, e.source = BEATEN, "flag"
                elif e.state == UNKNOWN:
                    e.state = UNBEATEN

    def note_talk(self, map_id: int, idx: int, step: int) -> None:
        """An A press faced the NPC matching this placement and produced text. The first press arms the
        probe; a battle starting cancels it (tick with battling=True)."""
        if (map_id, idx) not in self._talk:
            self._talk[(map_id, idx)] = step
            self._talk_text[(map_id, idx)] = 0

    def tick(self, step: int, battling: bool = False, text_open: bool = False) -> bool:
        """Advance talk probes; True when the ledger changed (the caller may persist). Steps with text
        still scrolling (``text_open``) do not count toward TALK_WAIT_STEPS: a long pre-battle speech is
        not 'talked and nothing happened'."""
        if battling:
            self._talk.clear()
            self._talk_text.clear()
            return False
        changed = False
        for (m, idx), started in list(self._talk.items()):
            if text_open:
                self._talk_text[(m, idx)] = self._talk_text.get((m, idx), 0) + 1
            if step - started - self._talk_text.get((m, idx), 0) >= TALK_WAIT_STEPS:
                self.mark_beaten(m, idx, "talk_no_battle", step)
                del self._talk[(m, idx)]
                self._talk_text.pop((m, idx), None)
                changed = True
        return changed

    # --- per-run persistence (<run dir>/trainers.json; per save, never shared) -----------------------

    def save(self, path) -> None:
        rec = {"provenance": self.provenance, "entries": {}}
        for m, es in self._entries.items():
            for e in es:
                if e.state != UNKNOWN or e.source:
                    rec["entries"][f"{m}:{e.idx}"] = {"state": e.state, "source": e.source,
                                                      "step": e.step, "provenance": e.provenance}
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(rec))
        os.replace(tmp, path)  # atomic: a kill mid-write cannot corrupt the ledger

    def restore(self, path) -> int:
        """Re-apply this run's own file on resume (a fresh run dir has none). Rows for maps not yet
        added are kept in ``_restored`` and applied by add_map."""
        try:
            rec = json.loads(Path(path).read_text())
        except (OSError, ValueError):
            return 0
        n = 0
        for key, e in (rec.get("entries") or {}).items():
            if isinstance(e, dict) and e.get("state") in (BEATEN, UNBEATEN):
                self._restored[key] = e
                n += 1
        for m, es in list(self._entries.items()):
            for e in es:
                saved = self._restored.get(f"{m}:{e.idx}")
                if saved:
                    e.state, e.source, e.step = saved["state"], saved.get("source", ""), saved.get("step")
        return n


def load_flag_bits(path: Path = FLAGS_PATH) -> dict[str, tuple[int, int]]:
    """``{"<map>:<idx>": (addr, bit)}`` from the committed table; {} until the controller mines them."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    for k, v in (raw or {}).items():
        try:
            if isinstance(v, dict):
                out[str(k)] = (int(v["addr"]), int(v["bit"]))
            elif isinstance(v, (list, tuple)) and len(v) == 2:
                out[str(k)] = (int(v[0]), int(v[1]))
        except (KeyError, TypeError, ValueError):
            continue
    return out


# --- the ctx glue lives in explorer/trainer_hooks.py; re-exported so callers keep one import surface ---


def _hook(name: str):
    from pokeagent.explorer import trainer_hooks
    return getattr(trainer_hooks, name)


def beaten_trainers(ctx):
    return _hook("beaten_trainers")(ctx)


def ledger_for(ctx):
    return _hook("ledger_for")(ctx)


def ensure_maps(ctx):
    return _hook("ensure_maps")(ctx)


def share_static(ctx, map_id):
    return _hook("share_static")(ctx, map_id)


def tick(ctx):
    return _hook("tick")(ctx)


def note_battle_won(ctx, npc, battle_map):
    return _hook("note_battle_won")(ctx, npc, battle_map)


def note_talk(ctx, before, npc, got_text):
    return _hook("note_talk")(ctx, before, npc, got_text)


def save_run(ctx):
    return _hook("save_run")(ctx)
