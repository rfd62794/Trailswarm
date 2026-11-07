"""The data-driven campaign ladder: chain, first-25 prefix, ROM id checks, generic detectors, reachability, picker."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from pokeagent import campaign, goals
from pokeagent.emulator import FakeEmulator

ROOT = Path(__file__).resolve().parents[1]
ROM = ROOT / "roms" / "Pokemon Red.gb"
TABLES = ROOT / "kb" / "rom_tables.json"
PREFIX = ["potion", "left_house", "first_pokemon", "won_battle",
          "to_route1", "to_viridian", "oaks_parcel", "deliver_parcel",
          "to_route2", "to_pewter", "to_gym", "beat_brock",
          "to_route3", "to_route4", "buy_magikarp", "to_mt_moon", "mt_moon_b1f", "mt_moon_b2f", "through_mt_moon", "to_cerulean",
          "heal_cerulean", "beat_misty", "nugget_bridge", "gyarados", "to_bill", "ss_ticket"]
SPECS = list(campaign.load_campaign())


def _ids(det):
    if not isinstance(det, dict):
        return []
    inner = next((v for k, v in det.items() if k in ("map_now_with_item", "map_past_x")), det)
    return inner.get("map", [])


def test_ladder_is_long_and_starts_with_todays_26():
    assert len(SPECS) >= 100
    assert goals.GOALS[:26] == PREFIX and goals.GOALS == [g["id"] for g in SPECS]
    assert len(set(goals.GOALS)) == len(goals.GOALS)
    assert all(g.get("special") for g in SPECS[:26]) and not any(g.get("special") for g in SPECS[26:])


def test_order_is_a_chain():
    assert SPECS[0]["after"] is None
    for prev, cur in zip(SPECS, SPECS[1:]):
        assert cur["after"] == prev["id"]


def test_every_goal_has_a_known_detector_shape():
    for g in SPECS:
        d = g["detector"]
        assert d == "unverified" or (isinstance(d, dict) and len(d) == 1 and next(iter(d)) in
                                     {"map", "badge", "item", "flag", "party", "party_move", "map_and_badge", "map_now_with_item", "map_past_x", "special"}), g["id"]
        if isinstance(d, dict) and "badge" in d:
            assert 0 <= d["badge"] <= 7


@pytest.mark.skipif(not ROM.exists(), reason="ROM not present")
def test_map_ids_exist_in_rom_headers():
    from pokeagent.atlas import rom_maps
    valid = rom_maps.valid_map_ids(ROM)
    for g in SPECS:
        d = g["detector"]
        ids = _ids(d) + (d["map_and_badge"]["map"] if isinstance(d, dict) and "map_and_badge" in d else [])
        assert all(i in valid for i in ids), g["id"]


@pytest.mark.skipif(not TABLES.exists(), reason="kb/rom_tables.json not present")
def test_item_ids_exist_in_rom_item_table():
    items = json.loads(TABLES.read_text(encoding="utf-8"))["items"]
    for g in SPECS:
        d = g["detector"]
        if isinstance(d, dict) and "item" in d:
            ids = d["item"] if isinstance(d["item"], list) else [d["item"]]
            assert all(str(i) in items for i in ids), g["id"]
    assert items["63"]["name"] == "S.S.TICKET" and items["70"]["name"].startswith("OAK")


def test_detectors_on_synthetic_ram():
    emu = FakeEmulator({0xD35E: 0x25})
    st: dict = {}
    g = goals.check_goals(emu, st)
    assert not g["to_route5"] and not g["beat_surge"] and not g["bike_voucher"]
    emu.set(0xD35E, 0x10)                      # Route 5
    emu.set(0xD356, 0b0100)                    # Thunder badge
    emu.set(0xD31D, 1); emu.set(0xD31E, 45); emu.set(0xD31F, 1)  # BIKE VOUCHER
    g = goals.check_goals(emu, st)
    assert g["to_route5"] and g["beat_surge"] and g["bike_voucher"] and not g["beat_erika"]
    emu.set(0xD31D, 0)                         # item gone from the bag: still achieved this run
    emu.set(0xD35E, 0x01)
    assert goals.check_goals(emu, st)["bike_voucher"]


def test_item_list_and_flag_and_combined_detectors():
    emu = FakeEmulator({0xD31D: 1, 0xD31E: 61, 0xD31F: 1, 0xD7F0: 0b10, 0xD356: 0b10})
    ev = campaign.evaluate
    assert ev({"item": [60, 61, 62]}, emu, {}, set(), {61: 1})
    assert not ev({"item": 6}, emu, {}, set(), {61: 1})
    assert ev({"flag": {"addr": "0xD7F0", "bit": 1}}, emu, {}, set(), {})
    assert not ev({"flag": {"addr": "0xD7F0", "bit": 0}}, emu, {}, set(), {})
    mb = {"map_and_badge": {"map": [3], "badge": 1}}
    assert ev(mb, emu, {}, {3}, {}) and not ev(mb, emu, {}, set(), {})
    assert ev({"party": {"min_count": 1}}, FakeEmulator({0xD163: 2}), {}, set(), {})


def test_party_move_detector_reads_every_member_and_slot():
    ev = campaign.evaluate
    cut = {"party_move": 15}
    assert not ev(cut, FakeEmulator({0xD163: 2}), {}, set(), {})
    assert ev(cut, FakeEmulator({0xD163: 2, 0xD173 + 0x2C + 3: 15}), {}, set(), {})       # slot 4 of the second member
    assert not ev(cut, FakeEmulator({0xD163: 1, 0xD173 + 0x2C: 15}), {}, set(), {})       # a bench slot past the party count


def test_captain_and_hm01_use_the_mined_event_flags():
    ev = campaign.evaluate
    by = {g["id"]: g for g in SPECS}
    assert by["ss_anne_captain"]["detector"] == {"flag": {"addr": "0xD803", "bit": 1}}   # rubbed the captain's back
    assert by["hm01_cut"]["detector"] == {"flag": {"addr": "0xD803", "bit": 0}}          # EVENT_GOT_HM01
    assert by["cut_taught"]["after"] == "hm01_cut" and by["pokemon_fan_club"]["after"] == "cut_taught"
    g = {s["id"]: False for s in SPECS}
    emu = FakeEmulator({})
    for k in ("ss_anne_captain", "hm01_cut"):
        g[k] = bool(ev(by[k]["detector"], emu, {}, set(), {}))
    assert not g["ss_anne_captain"] and not g["hm01_cut"]                                 # walking into the cabin is not enough
    emu.set(0xD803, 0b11)
    assert ev(by["ss_anne_captain"]["detector"], emu, {}, set(), {}) and ev(by["hm01_cut"]["detector"], emu, {}, set(), {})


def test_unverified_goals_follow_later_goals():
    g = {s["id"]: False for s in SPECS}
    campaign.infer_unverified(g)
    assert not g["rival_ss_anne"]
    g["to_pokemon_tower"] = True
    campaign.infer_unverified(g)
    assert not g["rival_ss_anne"]                                          # a later goal alone is not enough: predecessors missing
    g["ss_anne_2f"] = g["ss_anne_captain"] = True
    campaign.infer_unverified(g)
    assert g["rival_ss_anne"]                                             # earlier than a reached goal
    assert not g["snorlax_route12"]                                        # later than the last reached goal


def test_reachable_filters_on_needs():
    assert campaign.reachable("to_vermilion", set())
    assert not campaign.reachable("vermilion_gym_entry", set())
    assert campaign.reachable("vermilion_gym_entry", {"cut"})
    assert not campaign.reachable("beat_surge", {"cut"}) and campaign.reachable("beat_surge", {"cut", "puzzle"})
    assert not campaign.reachable("no_such_goal", {"cut"})
    assert all(campaign.reachable(k, set()) for k in PREFIX)


def test_chain_reachability_and_selectable():
    assert campaign.campaign_reachable("ss_anne_captain", set())
    assert not campaign.campaign_reachable("to_route10", set())          # behind the Cut tree on Route 9
    assert campaign.selectable("to_vermilion", set())
    assert not campaign.selectable("rival_ss_anne", set())                # unverified: no detector to land on
    assert campaign.selectable("hm01_cut", set()) and campaign.selectable("cut_taught", set())   # real detectors since 2026-11-07
    assert not campaign.selectable("to_cinnabar", {"cut", "puzzle"})      # needs Surf
    everything = {t for g in SPECS for t in g["needs"]}
    assert campaign.selectable("to_cinnabar", everything)


def test_agent_capabilities_env(monkeypatch):
    monkeypatch.setenv("POKEAGENT_CAPS", "cut, puzzle")
    assert campaign.agent_capabilities() == {"cut", "puzzle"}
    assert campaign.reachable("beat_surge")


def _swarm():
    tools = str(ROOT / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    spec = importlib.util.spec_from_file_location("tool_swarm_campaign", ROOT / "tools" / "swarm.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_segment_picker_skips_unreachable_goals(monkeypatch):
    sw = _swarm()
    import overnight
    weak = {"to_vermilion": 0.1, "to_cinnabar": 0.0, "hm01_cut": 0.0, "beat_surge": 0.05, "potion": 0.5}
    monkeypatch.setattr(overnight, "consistency", lambda: dict(weak))
    monkeypatch.delenv("POKEAGENT_CAPS", raising=False)
    picks = {sw.weakest_segment(n) for n in range(6)}
    assert picks == {"to_vermilion", "potion", "hm01_cut"}               # no Surf or Cut-wall goals (hm01_cut has a flag detector now)
    monkeypatch.setenv("POKEAGENT_CAPS", "cut,puzzle,surf,flash,poke_flute,silph_scope,safari,bike,dex10,strength")
    picks = {sw.weakest_segment(n) for n in range(8)}
    assert "to_cinnabar" in picks and "beat_surge" in picks


def test_brief_truncates_the_long_ladder():
    line = campaign.brief({k: True for k in goals.GOALS[:30]}, goals.GOALS)
    assert line.startswith(f"30/{len(goals.GOALS)} done") and line.count("-") == 6 and len(line) < 160
    assert campaign.brief({k: True for k in goals.GOALS}, goals.GOALS).endswith("done")


def test_overnight_attempt_rule_ignores_far_goals():
    tools = str(ROOT / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import overnight
    n = len(goals.GOALS)
    assert not overnight.is_attempt(60, -1, n, 24)             # a full run from the bedroom was never an attempt at goal 60
    assert overnight.is_attempt(1, -1, n, -1) and overnight.is_attempt(25, -1, n, 24)
    assert overnight.is_attempt(30, 29, n, 24) and overnight.is_attempt(31, 29, n, 24)
    assert not overnight.is_attempt(33, 29, n, 24)
    assert overnight.is_attempt(33, 29, 33, 24)                # stopped at it
    assert not overnight.is_attempt(5, 5, n, 24) and not overnight.is_attempt(10, 2, 8, 24)


def test_snapshot_goals_come_in_ladder_order():
    from pokeagent.adapters import explorer_snapshot as es
    key = lambda k: (goals.GOALS.index(k) if k in goals.GOALS else len(goals.GOALS), k)
    names = ["to_route5", "potion", "gyarados", "beat_champion", "to_bill"]
    assert sorted(names, key=key) == ["potion", "gyarados", "to_bill", "to_route5", "beat_champion"]
    assert es.GOALS is goals.GOALS
