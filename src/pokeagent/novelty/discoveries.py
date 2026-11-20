"""Discovery detectors: surprising game-state events are LOGGED for review, never rewarded.

Records go to runs/discoveries.jsonl, with a save state in runs/discoveries/ (a directory no checkpoint, segment or
curriculum code reads; ``is_discovery_state`` is the guard they ask). Some Gen 1 glitches corrupt saves, so these
states are evidence for Claude and Robert, not starting points.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from pokeagent.glitch_signals import (
    VIRIDIAN_FOREST_SCRIPT,
    Signals,
    active_reasons,
    instant_text_candidate,
)
from pokeagent.novelty.features import Snapshot, flag_bits

DIR_NAME, LOG_NAME, STATE_SUFFIX = "discoveries", "discoveries.jsonl", ".discovery.state"
STAGE_SLACK = 5        # a flag set this many campaign goals earlier than ever seen before is out of order
ITEM_JUMP = 3          # bag stack growth in one step that a pickup does not explain...
CHEAPEST_ITEM = 50     # ...unless money fell by at least this much per unit (a purchase)
MONEY_JUMP = 50        # money gain no battle prize or sale explains
BATTLE_WINDOW = 20     # steps after a battle in which a money gain is a prize
STUCK_STEPS = 30       # consecutive snapshots a stuck-flag signature must hold before it is logged (a scripted
                       # walk or a text box holds the same bits briefly during normal play)
MAX_PER_RUN = 25

_NAMES: dict | None = None


def map_names() -> dict:
    global _NAMES
    if _NAMES is None:
        _NAMES = json.loads((Path(__file__).resolve().parent.parent / "atlas" / "map_names.json").read_text(encoding="utf-8"))
    return _NAMES


def odd_map(map_id: int) -> bool:
    """A map id outside the normal list (ids past the table, or UNUSED_MAP_xx): a glitch warp."""
    name = map_names().get(str(map_id))
    return name is None or name.startswith("UNUSED")


def is_discovery_state(path: Path | str) -> bool:
    p = Path(path)
    return p.name.endswith(STATE_SUFFIX) or DIR_NAME in p.parts


def _sum(pairs) -> dict:
    out: dict = {}
    for i, q in pairs:
        out[i] = out.get(i, 0) + q
    return out


def new_map(prev, cur, ctx) -> list:
    if prev is None or prev.map == cur.map:
        return []
    if odd_map(cur.map):
        return [("glitch_map", f"m:{cur.map}", prev.map, cur.map)]
    if ctx.get("maps_known") and ctx["counts"].get(f"m:{cur.map}", 0) == 0:
        return [("new_map", f"m:{cur.map}", prev.map, cur.map)]
    return []


def flag_out_of_order(prev, cur, ctx) -> list:
    if prev is None or prev.flags == cur.flags or ctx.get("stage_now") is None:
        return []
    now, out = ctx["stage_now"], []
    for b in flag_bits(cur.flags, prev.flags):
        seen = ctx["stage"].get(f"f:{b}")
        if seen is not None and seen - now >= STAGE_SLACK:
            out.append(("flag_out_of_order", f"f:{b}", seen, now))
    return out


def item_duplication(prev, cur, ctx) -> list:
    if prev is None:
        return []
    a, b = _sum(prev.bag), _sum(cur.bag)
    pa, pb = _sum(prev.pc), _sum(cur.pc)
    spent = max(0, prev.money - cur.money)
    out = []
    for item, q in b.items():
        gain = q - a.get(item, 0)
        if gain < ITEM_JUMP:
            continue
        if gain <= pa.get(item, 0) - pb.get(item, 0) or spent >= gain * CHEAPEST_ITEM:
            continue  # withdrawn from the PC, or bought
        out.append(("item_jump", f"i:{item}", a.get(item, 0), q))
    return out


def money_jump(prev, cur, ctx) -> list:
    if prev is None or cur.money - prev.money < MONEY_JUMP or cur.in_battle or prev.in_battle:
        return []
    if ctx["step"] - ctx.get("last_battle_step", -10 ** 9) <= BATTLE_WINDOW:
        return []  # a battle prize
    a, b = _sum(prev.bag), _sum(cur.bag)
    if any(b.get(i, 0) < q for i, q in a.items()):
        return []  # an item left the bag: a sale
    return [("money_jump", "money", prev.money, cur.money)]


def level_without_xp(prev, cur, ctx) -> list:
    """A level rose and the mon's exp has not moved since its level was last read. (The game updates exp first and the
    level field later, so a level that jumps a step or a battle after the exp is normal: compare to the exp at the last
    level read, which the log tracks per mon, not to the previous step.)"""
    if prev is None:
        return []
    before = {m[4]: m for m in prev.party}
    base = ctx.get("lvl_exp", {})
    out = []
    for sp, lv, exp, _mv, ident in cur.party:
        p = before.get(ident)
        if p and p[0] == sp and lv > p[1] and exp <= base.get(ident, p[2]):
            out.append(("level_without_xp", f"so:{sp}", [p[1], base.get(ident, p[2])], [lv, exp]))
    return out


def species_unseen(prev, cur, ctx) -> list:
    """A species newly in the party that nobody has met in battle (not an evolution; not the first party member)."""
    if prev is None or not prev.party:
        return []
    old_ids = {m[4] for m in prev.party}
    old_species = {m[0] for m in prev.party}
    out = []
    for sp, _lv, _e, _m, ident in cur.party:
        if ident in old_ids or sp in old_species:
            continue
        if sp in ctx["seen_species"] or ctx["counts"].get(f"ss:{sp}", 0) > 0:
            continue
        out.append(("species_unseen", f"so:{sp}", None, sp))
    return out


def _signals(cur) -> Signals | None:
    """The glitch-signal bytes on a Snapshot (``cur.sig``), or None when the snapshot carries none."""
    return Signals.from_tuple(cur.sig)


def _streak(ctx, key: str, hit: bool) -> int:
    """Consecutive snapshots ``key``'s rule has held, counted in the shared ``ctx["streaks"]`` dict."""
    st = ctx.get("streaks")
    if st is None:
        return 0
    st[key] = st.get(key, 0) + 1 if hit else 0
    return st[key]


def script_byte_oor(prev, cur, ctx) -> list:
    """Viridian Forest's meta-map script byte out of range (research row 4: death-warp + double fight)."""
    sig = _signals(cur)
    if sig is None or "script_oor" not in active_reasons(sig):
        return []
    psig = _signals(prev) if prev is not None else None
    return [("glitch_script_oor", f"s:0x{VIRIDIAN_FOREST_SCRIPT:04X}",
             psig.forest_script if psig is not None else None, sig.forest_script)]


def trainer_flags_stuck(prev, cur, ctx) -> list:
    """Trainer bookkeeping flags set with no trainer engaged (research row 2: trainer-escape leftovers)."""
    sig = _signals(cur)
    hit = sig is not None and "trainer_flags_stuck" in active_reasons(sig)
    streak = _streak(ctx, "trainer_flags_stuck", hit)   # always counted: a miss resets the run of hits
    if not hit or streak < STUCK_STEPS:
        return []
    return [("glitch_trainer_flags", "tf", None, {"misc_flags": sig.misc_flags, "status5": sig.status5})]


def move_override_set(prev, cur, ctx) -> list:
    """The movement-override byte nonzero outside battle (research rows 5/7: buffer overflow into 0xCD3B)."""
    sig = _signals(cur)
    hit = sig is not None and "move_override" in active_reasons(sig)
    streak = _streak(ctx, "move_override", hit)
    if not hit or streak < STUCK_STEPS:
        return []
    return [("glitch_move_override", "mo", None, sig.move_override)]


def instant_text_flag(prev, cur, ctx) -> list:
    """UNVERIFIED instant-text signature (wStatusFlags5 bit 6, the Cerulean Bike Shop trick, research row 24).
    Log only: the bit's role is unconfirmed, so it never feeds ``active_reasons`` or the checkpoint guard."""
    sig = _signals(cur)
    hit = sig is not None and not sig.in_battle and instant_text_candidate(sig)
    streak = _streak(ctx, "instant_text", hit)
    if not hit or streak < STUCK_STEPS:
        return []
    return [("glitch_instant_text", "it", None, {"status5": sig.status5, "d358": sig.text_d358})]


DETECTORS = (new_map, flag_out_of_order, item_duplication, money_jump, level_without_xp, species_unseen,
             script_byte_oor, trainer_flags_stuck, move_override_set, instant_text_flag)


class DiscoveryLog:
    """Runs the detectors each step; writes a record plus a save state per surprising event (deduped, capped per run)."""

    def __init__(self, runs_dir: Path | str, run: str, role: str, clock=time.time) -> None:
        self.runs_dir, self.run, self.role, self.clock = Path(runs_dir), run, role, clock
        self.done: set = set()
        self.last_battle_step = -10 ** 9
        self.lvl_exp: dict = {}  # mon identity -> its exp when its level was last read to change (or first seen)
        self.streaks: dict = {}  # detector name -> consecutive snapshots its stuck-flag rule has held
        self.records: list[dict] = []

    def check(self, prev: Snapshot | None, cur: Snapshot, step: int, emu, ctx: dict) -> list[dict]:
        if cur.in_battle:
            self.last_battle_step = step
        ctx = {**ctx, "step": step, "last_battle_step": self.last_battle_step, "lvl_exp": self.lvl_exp,
               "streaks": self.streaks}
        out = []
        for det in DETECTORS:
            try:
                hits = det(prev, cur, ctx)
            except Exception:  # noqa: BLE001  a detector bug must never stop a run
                continue
            for kind, feature, before, after in hits:
                if (kind, feature) in self.done or len(self.done) >= MAX_PER_RUN:
                    continue
                self.done.add((kind, feature))
                out.append(self._write(kind, feature, before, after, step, emu, cur))
        self._track_levels(prev, cur)
        return out

    def _track_levels(self, prev, cur) -> None:
        old = {m[4]: m[1] for m in prev.party} if prev is not None else {}
        for _sp, lv, exp, _mv, ident in cur.party:
            if old.get(ident) != lv:
                self.lvl_exp[ident] = exp

    def record(self, kind, feature, before, after, step, emu, cur) -> dict | None:
        """Log one record outside ``check`` (the checkpoint guard's refusals): same done-set and per-run cap."""
        if (kind, feature) in self.done or len(self.done) >= MAX_PER_RUN:
            return None
        self.done.add((kind, feature))
        return self._write(kind, feature, before, after, step, emu, cur)

    def _write(self, kind, feature, before, after, step, emu, cur) -> dict:
        d = self.runs_dir / DIR_NAME
        state = d / f"{self.run}-{step}-{kind}{STATE_SUFFIX}"
        try:
            d.mkdir(parents=True, exist_ok=True)
            emu.save_state(state)
            saved = str(state)
        except Exception:  # noqa: BLE001
            saved = None
        rec = {"run": self.run, "role": self.role, "step": step, "kind": kind, "feature": feature, "before": before, "after": after,
               "pos": [cur.map, cur.x, cur.y] if cur is not None else None, "state": saved, "t": round(self.clock(), 1)}
        try:
            with (self.runs_dir / LOG_NAME).open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
        except OSError:
            pass
        self.records.append(rec)
        return rec
