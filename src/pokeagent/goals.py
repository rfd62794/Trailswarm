"""Campaign goals: the single source of truth for the goal ladder (data/campaign.json) and its RAM detectors.

The first 25 goals keep the hand-coded detectors in check_goals; the rest are generic detectors from the data file (pokeagent.campaign).

tools/{explore_demo,overnight,swarm,review_runs,status}.py all read GOALS from here —
tests/test_goal_order.py guards against new local copies. goals.json is a stale
sibling, not a source.
"""
from __future__ import annotations

from pokeagent import campaign
from pokeagent.knowledge import kb as _kbmod
from pokeagent.knowledge.cut_learner import cut_capable, party_names
from pokeagent.magikarp import gyarados_goal, magikarp_goal_settled

is_unverified = campaign.is_unverified  # re-exported for the explorer package (no detector of its own)
GOALS = campaign.goal_ids()  # the ladder lives in data/campaign.json; the first 25 ids are the hand-coded ones below

def goals_brief(goals: dict) -> str:
    """One short log line for the whole ladder: done/total and the next few unmet goals."""
    return campaign.brief(goals, GOALS)


# Background goals: reported by check_goals and tools/status.py, never part of the ladder (they must not block the route).
SIDE_GOALS = ["gyarados"]

GOAL_MENU = {"potion": ["WITHDRAW ITEM", "POTION"]}  # menu options to take, in order, while a goal is unmet


def bag_contents(emu) -> dict[int, int]:
    n = emu.read(0xD31D)
    if not 0 < n < 21:
        return {}
    raw = emu.read_range(0xD31E, 2 * n)
    return {raw[i]: raw[i + 1] for i in range(0, len(raw), 2)}


SS_TICKET = 0x3F  # ROM item-name table: index 0x3F is "S.S.TICKET"


def through_mt_moon(emu, st: dict, m: int, seen: set) -> bool:
    """Crossed Mt Moon: on Route 4 east of the exit warp after B2F was seen (sticky), or Cerulean already seen."""
    if m == 0x0F and 0x3D in seen and emu.read(0xD362) >= 24:
        st["through_mt_moon"] = True
    return bool(st.get("through_mt_moon")) or 0x03 in seen


def party_full(emu) -> bool:
    """Every party Pokemon at full HP (wPartyMonN HP 0xD16C / MaxHP 0xD18D, 44 bytes apart; count at 0xD163)."""
    n = emu.read(0xD163)
    if not 0 < n <= 6:
        return False
    for i in range(n):
        hp = (emu.read(0xD16C + 0x2C * i) << 8) | emu.read(0xD16D + 0x2C * i)
        mx = (emu.read(0xD18D + 0x2C * i) << 8) | emu.read(0xD18E + 0x2C * i)
        if mx == 0 or hp < mx:
            return False
    return True


def healed_in_cerulean(emu, st: dict, m: int) -> bool:
    """heal_cerulean = the whole party is at full HP while standing in the Cerulean Pokecenter (0x40); sticky."""
    if m == 0x40 and party_full(emu):
        st["healed_cerulean"] = True
    return bool(st.get("healed_cerulean"))


def cut_learner_settled(emu, st: dict, kb) -> bool:
    """cut_learner: a Cut-compatible species is in the party (sticky ``had_cut_learner``), Cut is already known,
    the step cap was spent, or there is no ROM data to judge by (an empty table never blocks the route)."""
    if st.get("had_cut_learner") or st.get("cut_learner_skipped"):
        return True
    from pokeagent.explorer.catch_list import hm_table  # late import: the explorer package loads after this module
    hm = hm_table()
    if not hm:
        return True  # no kb/hm_compat.json: cannot judge, never block
    names = party_names(emu, kb)
    if names is None:
        return True  # no name_of_internal either
    if cut_capable(names, hm) or campaign.party_knows_move(emu, 15):
        st["had_cut_learner"] = True
        return True
    return False


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
         "to_route3": 0x0E in seen, "to_route4": 0x0F in seen,
         # Robert 2026-11-05: buy the 500-yen Magikarp from the salesman in the Mt Moon Pokecenter (0x44) before the cave;
         # settled when owned, or when it is no longer possible (< 500 money, full party) or Mt Moon 1F was entered.
         "buy_magikarp": magikarp_goal_settled(emu, st, seen), "to_mt_moon": 0x3B in seen,
         # Mt Moon floors (ROM: Route 4 warps lead to 0x3B and 0x3C; B1F warps lead to 0x3D). The cave counts as crossed
         # when the player is back on Route 4 EAST of the exit: the exit warp (B1F -> Route 4 warp 2) lands at tile
         # (24,5); the west entrance is (18,5) and the Mt Moon Pokecenter door (11,5). So: map 0x0F, x >= 24, B2F seen.
         "mt_moon_b1f": 0x3C in seen, "mt_moon_b2f": 0x3D in seen,
         "through_mt_moon": through_mt_moon(emu, st, m, seen), "to_cerulean": 0x03 in seen,
         # Cerulean (ROM warps from 0x03): 0x40 Pokecenter (heal_cerulean needs a full party inside it, not just a visit), 0x41 Gym; 0x23 Route 24 is Cerulean's north connection;
         # 0x58 Bill's house is the only warp on Route 25 (0x24). CASCADEBADGE = wObtainedBadges bit1 (ROM 17:5736).
         "heal_cerulean": healed_in_cerulean(emu, st, m), "beat_misty": bool(emu.read(0xD356) & 2),
         "nugget_bridge": 0x23 in seen, "to_bill": 0x58 in seen,
         "ss_ticket": SS_TICKET in bag_contents(emu)}
    g.update(campaign.campaign_goals(emu, st, seen, bag_contents(emu)))  # goals 26+: generic detectors from campaign.json
    g["cut_learner"] = cut_learner_settled(emu, st, _kbmod.ROM_KB)  # special goal: hand-coded, skipped by campaign_goals
    # A goal, once achieved in this run (or already true at its start), stays achieved: using the potion in a battle
    # must not send the agent back to an empty PC (seen 2026-11-03 04:30).
    for k in g:
        if k in st.get("goal_steps", {}) or k in st.get("initial_goals", set()):
            g[k] = True
    campaign.infer_unverified(g)  # unverified goals (no RAM detector) follow from later ones; keeps the ladder from stalling
    g["gyarados"] = gyarados_goal(emu, st)  # side goal: informational, not in the ladder
    return g
