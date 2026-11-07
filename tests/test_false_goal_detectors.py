"""Goals that used to fire early (milestones.json 2026-11-06): rival_ss_anne, hm01_cut, bike_shop, to_route9; plus the cleaner."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from pokeagent import campaign, goals
from pokeagent.emulator import FakeEmulator

MAP, PX, PY, BAG_N, BAG = 0xD35E, 0xD362, 0xD361, 0xD31D, 0xD31E
CERULEAN, BIKE_SHOP, ROUTE_9, VOUCHER = 0x03, 66, 20, 45
EARLY = ["potion", "left_house", "first_pokemon", "won_battle", "to_route1", "to_viridian", "oaks_parcel", "deliver_parcel",
         "to_route2", "to_pewter", "to_gym", "beat_brock", "to_route3", "to_route4", "buy_magikarp", "to_mt_moon", "mt_moon_b1f",
         "mt_moon_b2f", "through_mt_moon", "to_cerulean"]


def run(emu, st, *maps_in_order):
    out = {}
    for m, x in maps_in_order:
        emu.set(MAP, m); emu.set(PX, x)
        out = goals.check_goals(emu, st)
    return out


def with_voucher(emu):
    emu.set(BAG_N, 1); emu.set(BAG, VOUCHER); emu.set(BAG + 1, 1)


def test_bike_shop_needs_the_voucher_in_the_bag():
    emu, st = FakeEmulator({}), {}
    g = run(emu, st, (CERULEAN, 13), (BIKE_SHOP, 2))        # the swarm walked in through the door, no voucher
    assert not g["bike_shop"] and not g["rival_ss_anne"] and not g["hm01_cut"]
    with_voucher(emu)
    assert goals.check_goals(emu, st)["bike_shop"]           # in the shop holding the Bike Voucher
    emu.set(BAG_N, 0); emu.set(MAP, CERULEAN)
    assert not goals.check_goals(emu, st)["bike_shop"]       # record_goals' goal_steps does the sticking, not the detector


def test_bike_shop_before_the_voucher_never_counts_later():
    emu, st = FakeEmulator({}), {}
    run(emu, st, (BIKE_SHOP, 2))                              # visited early
    emu.set(MAP, CERULEAN); with_voucher(emu)                 # voucher arrives later, shop not re-entered
    assert not goals.check_goals(emu, st)["bike_shop"]


def test_out_of_order_goal_does_not_infer_unverified_predecessors():
    g = {s["id"]: False for s in campaign.load_campaign()}
    for k in EARLY:
        g[k] = True
    g["bike_shop"] = True                                     # reached out of order
    campaign.infer_unverified(g)
    assert not g["rival_ss_anne"]
    for k in ("ss_anne_2f", "ss_anne_captain", "pokemon_fan_club"):
        g[k] = True                                           # the real chain
    campaign.infer_unverified(g)
    assert g["rival_ss_anne"]


def test_early_game_ram_fires_none_of_the_four():
    emu = FakeEmulator({MAP: CERULEAN, PX: 13})
    g = goals.check_goals(emu, {})
    assert not any(g[k] for k in ("rival_ss_anne", "hm01_cut", "bike_shop", "to_route9"))


def test_to_route9_needs_to_get_past_the_cut_tree():
    emu, st = FakeEmulator({}), {}
    g = run(emu, st, (CERULEAN, 39), (ROUTE_9, 0), (ROUTE_9, 3))   # Route 9 west edge: the tree stands at x=4
    assert not g["to_route9"]
    g = run(emu, st, (ROUTE_9, 5))                                  # cut, or arrived from the Route 10 side
    assert g["to_route9"]


def test_to_route9_stays_true_after_leaving():
    emu, st = FakeEmulator({}), {}
    run(emu, st, (ROUTE_9, 6))
    st.setdefault("goal_steps", {})["to_route9"] = 1               # what record_goals does once it fires
    assert run(emu, st, (CERULEAN, 39))["to_route9"]


def _load_cleaner():
    spec = importlib.util.spec_from_file_location("milestones_clean", Path(__file__).resolve().parents[1] / "tools" / "milestones_clean.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


def _mkrun(root: Path, name: str, start: str, initial: list[str], reached: dict[str, int]):
    d = root / name; d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({"start": start, "initial_goals": initial}))
    (d / "goal_frames.jsonl").write_text("".join(json.dumps({"goal": g, "step": s, "frame": 0}) + "\n" for g, s in reached.items()))


def test_cleaner_flags_impossible_entries_and_writes_a_copy(tmp_path, capsys):
    mc = _load_cleaner()
    order = campaign.goal_ids()
    _mkrun(tmp_path, "r-bad", "to_cerulean", EARLY, {"bike_shop": 49})
    _mkrun(tmp_path, "r-far", "ss_ticket", order[:order.index("ss_ticket") + 1], {"to_route9": 90})
    _mkrun(tmp_path, "r-ok", "ss_ticket", order[:order.index("ss_ticket") + 1], {"to_route5": 10, "to_route6": 20})
    ms = {"bike_shop": [{"run": "r-bad", "step": 49}], "to_route9": [{"run": "r-far", "step": 90}],
          "to_route5": [{"run": "r-ok", "step": 10}], "to_route6": [{"run": "r-ok", "step": 20}]}
    bad, unjudged = mc.find_impossible(ms, tmp_path)
    assert {(g, e["run"]) for g, e, _ in bad} == {("bike_shop", "r-bad"), ("to_route9", "r-far")} and unjudged == 0
    src = tmp_path / "milestones.json"; src.write_text(json.dumps(ms))
    before = src.read_text()
    assert mc.main(["--runs", str(tmp_path)]) == 0
    assert not (tmp_path / "milestones.cleaned.json").exists()           # report mode writes nothing
    assert mc.main(["--runs", str(tmp_path), "--apply"]) == 0
    assert set(json.loads((tmp_path / "milestones.cleaned.json").read_text())) == {"to_route5", "to_route6"}
    assert src.read_text() == before                                      # the live file is untouched
    assert mc.main(["--runs", str(tmp_path), "--apply", "--out", str(src)]) == 2   # refuses to overwrite the input
    assert src.read_text() == before


def test_cleaner_keeps_entries_it_cannot_judge(tmp_path):
    mc = _load_cleaner()
    bad, unjudged = mc.find_impossible({"to_route9": [{"run": "gone", "step": 1}]}, tmp_path)
    assert bad == [] and unjudged == 1
