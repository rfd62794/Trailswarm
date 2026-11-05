"""Knowledge-based move values from the cartridge tables (moved unchanged from tools/explore_demo.py)."""
from __future__ import annotations

from pokeagent.explorer.kb import ROM_KB


def move_value(name: str) -> float:
    """Cartridge value of a move by name (power x accuracy, status moves 0); used when learning/forgetting moves."""
    if not ROM_KB:
        return 0.0
    n = "".join(ch for ch in name.upper() if ch.isalnum())
    for mv in ROM_KB["moves"].values():
        if "".join(ch for ch in mv["name"].upper() if ch.isalnum()) == n:
            return mv["power"] * mv["accuracy"]
    return 0.0


def move_scores(emu) -> dict[str, tuple[float, str]]:
    """Knowledge-based move values for the current battle: power x type effectiveness (ROM type chart) x STAB x
    accuracy, from the cartridge's own tables; moves with 0 PP score 0. Returns {MOVE NAME: (score, reason)}."""
    if not ROM_KB:
        return {}
    chart = {(a, d): e for a, d, e in ROM_KB["type_chart"]}
    enemy_types = {ROM_KB["moves"]["1"]["type"]} if False else set()
    et1, et2 = emu.read(0xCFEA), emu.read(0xCFEB)
    names = {"NORMAL": 0, "FIGHTING": 1, "FLYING": 2, "POISON": 3, "GROUND": 4, "ROCK": 5, "BUG": 7, "GHOST": 8, "FIRE": 20,
             "WATER": 21, "GRASS": 22, "ELECTRIC": 23, "PSYCHIC": 24, "ICE": 25, "DRAGON": 26}
    inv = {v: k for k, v in names.items()}
    enemy_types = {inv.get(et1, "?"), inv.get(et2, "?")}
    my_types = {inv.get(emu.read(0xD170), "?"), inv.get(emu.read(0xD171), "?")}
    out = {}
    for slot in range(4):
        mid, pp = emu.read(0xD01C + slot), emu.read(0xD02D + slot) & 0x3F
        mv = ROM_KB["moves"].get(str(mid))
        if not mv or not mid:
            continue
        eff = 1.0
        for t in enemy_types:
            eff *= chart.get((mv["type"], t), 1.0)
        stab = 1.5 if mv["type"] in my_types else 1.0
        score = mv["power"] * eff * stab * mv["accuracy"] if pp > 0 else 0.0
        out[mv["name"]] = (score, f"pow {mv['power']} x{eff:g} type{' STAB' if stab > 1 else ''} pp {pp}")
    return out
