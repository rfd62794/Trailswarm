"""Agent-side inputs of the digest: what the snapshot lacks (where it is, mode, battle, bag, recent decisions).

``Tracker`` follows the agent's decision log (via ``DecisionLog.listeners``) and the box text at each snapshot, and
``build`` returns the ``extra`` dict the explorer view puts in its snapshot. Read-only; it never presses anything.
"""
from __future__ import annotations

from collections import deque

from pokeagent.intervene.names import item_name, species_name
from pokeagent.intervene.screen import read_screen
from pokeagent.party_view import read_party_view
from pokeagent.ram_symbols import IS_IN_BATTLE
from pokeagent.ramstructs import read_bag, read_battle_mon, read_enemy_mon

KINDS = {1: "wild", 2: "trainer"}


class Tracker:
    def __init__(self, decisions: int = 40, boxes: int = 6) -> None:
        self.decisions: deque[dict] = deque(maxlen=decisions)
        self.boxes: deque[str] = deque(maxlen=boxes)

    def add_decision(self, rec: dict) -> None:
        """A DecisionLog listener: keep a compact form of each decision record."""
        self.decisions.append({"s": rec.get("step"), "r": rec.get("rule"), "b": rec.get("button"), "m": rec.get("map"),
                               "x": rec.get("x"), "y": rec.get("y"), "o": rec.get("outcome"), "bx": rec.get("box"),
                               "bt": rec.get("battle"), "d": rec.get("driver", "agent")})

    def note_box(self, text: str) -> None:
        self.boxes.append(text)


def _mon(m) -> dict:
    return {"species": species_name(m.species), "level": m.level, "hp": m.hp, "max": m.max_hp}


def _our_mon(emu) -> dict:
    """Our battler. wBattleMon reads species 0 (stale level/HP from the last fight) until the new battle loads; then the
    party view's verified active slot (else its fighter, else the stale struct) is the honest source, so the digest
    never mixes two Pokemon."""
    me = read_battle_mon(emu)
    if me.species:
        return _mon(me)
    view = read_party_view(emu)
    p = view.slots[view.active_slot] if view.active_slot is not None else view.fighter()
    return _mon(p) if p is not None else _mon(me)


def build(ctx, emu, tracker: Tracker, box_text: str) -> dict:
    """The `extra` snapshot dict; a failure in any one part leaves that part empty (it must never break the snapshot)."""
    tracker.note_box(box_text)
    mid, x, y = ctx.pos()
    scr = read_screen(emu)
    out: dict = {"map": mid, "x": x, "y": y, "mode": scr.mode, "battle": None, "bag": {},
                 "decisions": list(tracker.decisions), "box_hist": list(tracker.boxes)}
    try:
        out["bag"] = {item_name(i): q for i, q in read_bag(emu)}
        if scr.in_battle:
            out["battle"] = {"kind": KINDS.get(emu.read(IS_IN_BATTLE), "battle"), "you": _our_mon(emu),
                             "enemy": _mon(read_enemy_mon(emu))}
    except Exception:
        pass
    return out
