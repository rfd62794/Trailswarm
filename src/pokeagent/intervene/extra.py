"""Agent-side inputs of the digest: what the snapshot lacks (where it is, mode, battle, bag, recent decisions).

``Tracker`` follows the agent's decision log (via ``DecisionLog.listeners``) and the box text at each snapshot, and
``build`` returns the ``extra`` dict the explorer view puts in its snapshot. Read-only; it never presses anything.
"""
from __future__ import annotations

from collections import deque

from pokeagent.intervene.names import item_name, species_name
from pokeagent.intervene.screen import PLAYER_MON, read_screen
from pokeagent.ramstructs import read_bag, read_battle_mon, read_enemy_mon, read_party

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


def _mon(m, species: int | None = None) -> dict:
    return {"species": species_name(m.species or species or 0), "level": m.level, "hp": m.hp, "max": m.max_hp}


def _active_species(emu) -> int:
    """Our battler's species from the party slot in the fight: wBattleMon's own species byte reads 0 during battles."""
    party = read_party(emu)
    slot = emu.read(PLAYER_MON)
    return party[slot].species if slot < len(party) else 0


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
            out["battle"] = {"kind": KINDS.get(emu.read(0xD057), "battle"), "you": _mon(read_battle_mon(emu), _active_species(emu)),
                             "enemy": _mon(read_enemy_mon(emu))}
    except Exception:
        pass
    return out
