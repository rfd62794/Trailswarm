"""Campaign goals: the single source of truth for the 16-goal ladder and its RAM detectors.

tools/{explore_demo,overnight,swarm,review_runs,status}.py all read GOALS from here —
tests/test_goal_order.py guards against new local copies. goals.json is a stale
sibling, not a source.
"""
from __future__ import annotations

GOALS = ["potion", "left_house", "first_pokemon", "won_battle",
         "to_route1", "to_viridian", "oaks_parcel", "deliver_parcel",
         "to_route2", "to_pewter", "to_gym", "beat_brock",
         "to_route3", "to_route4", "to_mt_moon", "to_cerulean"]

GOAL_MENU = {"potion": ["WITHDRAW ITEM", "POTION"]}  # menu options to take, in order, while a goal is unmet


def bag_contents(emu) -> dict[int, int]:
    n = emu.read(0xD31D)
    if not 0 < n < 21:
        return {}
    raw = emu.read_range(0xD31E, 2 * n)
    return {raw[i]: raw[i + 1] for i in range(0, len(raw), 2)}


def check_goals(emu, st: dict) -> dict[str, bool]:
    """Milestones read straight from RAM (bag 0xD31D/E verified; party 0xD163 and battle 0xD057 unverified)."""
    bag_n = emu.read(0xD31D)
    bag = emu.read_range(0xD31E, 2 * bag_n) if 0 < bag_n < 21 else b""  # PyBoy rejects empty slices
    potion = any(bag[i] == 0x14 for i in range(0, len(bag), 2))
    m = emu.read(0xD35E)
    seen = st.setdefault("seen_maps", set()); seen.add(m)
    has_parcel = 0x46 in bag_contents(emu)
    if has_parcel:
        st["had_parcel"] = True
    g = {"potion": potion, "left_house": m not in (0x25, 0x26) or st.get("goal_left_house", False),
         "first_pokemon": emu.read(0xD163) > 0, "won_battle": st.get("battles_won", 0) > 0,
         "to_route1": 0x0C in seen, "to_viridian": 0x01 in seen,
         "oaks_parcel": has_parcel or st.get("had_parcel", False),
         "deliver_parcel": st.get("had_parcel", False) and not has_parcel,
         "to_route2": 0x0D in seen, "to_pewter": 0x02 in seen,
         "to_gym": 0x36 in seen,  # Pewter Gym map 0x36
         "beat_brock": bool(emu.read(0xD356) & 1),  # wObtainedBadges bit0 = BOULDERBADGE (pokered.sym)
         # East of Pewter. Map ids checked against the ROM's map headers (kb: MapHeaderPointers/Banks) and the live
         # maps.json: 0x0E Route 3 (35x9), 0x0F Route 4 (45x9), 0x3B Mt Moon 1F (cavern tileset, 20x18), 0x03 Cerulean (20x18).
         # Geography (ROM connections): Pewter E-> Route 3 N-> Route 4 (Mt Moon 1F is a warp on Route 4) E-> Cerulean,
         # so the ladder runs route3, route4, mt_moon, cerulean.
         "to_route3": 0x0E in seen, "to_route4": 0x0F in seen, "to_mt_moon": 0x3B in seen, "to_cerulean": 0x03 in seen}
    # A goal, once achieved in this run (or already true at its start), stays achieved: using the potion in a battle
    # must not send the agent back to an empty PC (seen 2026-11-03 04:30).
    for k in g:
        if k in st.get("goal_steps", {}) or k in st.get("initial_goals", set()):
            g[k] = True
    return g
