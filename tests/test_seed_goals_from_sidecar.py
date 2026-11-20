"""seed_initial_goals reads the start state's goals sidecar; the name heuristic is only the fallback; parcel spots skip menu overlays."""
from __future__ import annotations

from pokeagent.checkpoint_goals import write_completed
from pokeagent.emulator import FakeEmulator
from pokeagent.explorer import press_goals
from pokeagent.explorer.context import ExplorerContext, ExplorerOptions
from pokeagent.explorer.memory import MapMemory
from pokeagent.explorer.planner import plan_step
from pokeagent.explorer.world import parcel_spots
from pokeagent.goals import GOALS, check_goals


def ctx_for(tmp_path, stem, state=None):
    (tmp_path / "meta.json").write_text("{}")
    logs = []
    return ExplorerContext(emu=FakeEmulator({0xD35E: 0x26}), mem=MapMemory(tmp_path / "maps.json"), run_dir=tmp_path, log=lambda m, t=None: logs.append(m),
                           opts=ExplorerOptions(state_stem=stem, state_path=str(state) if state else ""))


def through(goal):
    return set(GOALS[:GOALS.index(goal) + 1])


def test_sidecar_is_the_source_of_truth(tmp_path):
    state = tmp_path / "won_battle.best.state"
    write_completed(state, ["potion", "left_house", "first_pokemon", "won_battle"])
    ctx = ctx_for(tmp_path, "won_battle.best", state)
    press_goals.seed_initial_goals(ctx)
    assert {"potion", "left_house", "first_pokemon", "won_battle"} <= ctx.initial_goals
    assert "to_route1" not in ctx.initial_goals


def test_sidecar_beats_the_name(tmp_path):
    state = tmp_path / "to_viridian.state"      # the name says through to_viridian, the sidecar says only potion
    write_completed(state, ["potion"])
    ctx = ctx_for(tmp_path, "to_viridian", state)
    press_goals.seed_initial_goals(ctx)
    assert "to_viridian" not in ctx.initial_goals and "potion" in ctx.initial_goals


def test_best_suffix_stem_without_sidecar(tmp_path):
    ctx = ctx_for(tmp_path, "won_battle.best", tmp_path / "won_battle.best.state")
    press_goals.seed_initial_goals(ctx)
    assert through("won_battle") <= ctx.initial_goals


def test_at_stem_without_sidecar_assumes_goals_before_it(tmp_path):
    ctx = ctx_for(tmp_path, "ss_anne_captain@63")
    press_goals.seed_initial_goals(ctx)
    prefix = set(GOALS[:GOALS.index("ss_anne_captain")])
    assert prefix <= ctx.initial_goals and "potion" in ctx.initial_goals


def test_unknown_stem_without_sidecar_assumes_nothing(tmp_path):
    ctx = ctx_for(tmp_path, "mystery")
    press_goals.seed_initial_goals(ctx)
    assert ctx.initial_goals == {g for g, v in check_goals(ctx.emu, {}).items() if v and g in GOALS}  # RAM detectors only
    assert "potion" not in ctx.initial_goals


def test_seeding_happens_once(tmp_path):
    ctx = ctx_for(tmp_path, "won_battle")
    press_goals.seed_initial_goals(ctx)
    first = set(ctx.initial_goals)
    ctx.opts.state_stem = "ss_anne_captain"
    press_goals.seed_initial_goals(ctx)
    assert ctx.initial_goals == first


MENU = "looking great! | Take care / OAK PARCEL | CANCEL | USE | This isn yours | t / PLAYER BCN"


def maps_with_menu_in_the_bedroom():
    return {"38": {"interactions": {"4,1,UP": {"text": MENU}}},
            "37": {"interactions": {"7,6,RIGHT": {"text": MENU}}},
            "1": {"interactions": {"29,20,UP": {"text": "His order came in. Will you take the PARCEL to him?"}}}}


def test_menu_overlays_and_house_spots_are_not_parcel_spots():
    assert parcel_spots(maps_with_menu_in_the_bedroom()) == [(1, 29, 20, "UP")]


def test_viridian_agent_with_potion_is_never_sent_to_the_bedroom():
    maps = {**maps_with_menu_in_the_bedroom(), "1": {"interactions": {"29,20,UP": {"text": "OAK PARCEL! His order came in."}},
                                                    "visited": {"21,35": 1, "21,34": 1, "21,33": 1}}}
    goals = {g: True for g in through("to_viridian")}
    got = plan_step(goals, maps, (1, 21, 35), "UP")
    assert got is None or "0x26" not in got[1] and "0x25" not in got[1]


# ---- leg states: no sidecar, no goal name (2026-11-15: a run from 88_2_7.state aimed at Route 1)
def badge_ctx(tmp_path, badges, extra=None):
    ctx = ctx_for(tmp_path, "88_2_7", tmp_path / "88_2_7.state")
    ctx.emu = FakeEmulator({0xD35E: 0x26, 0xD356: badges, **(extra or {})})
    return ctx


def test_leg_state_with_two_badges_assumes_through_beat_misty(tmp_path):
    ctx = badge_ctx(tmp_path, 0b11)
    press_goals.seed_initial_goals(ctx)
    assert through("beat_misty") <= ctx.initial_goals and "to_route1" in ctx.initial_goals
    assert not {"ss_ticket", "to_route5", "bicycle", "beat_surge"} & ctx.initial_goals


def test_no_badges_assumes_nothing_from_badges(tmp_path):
    ctx = badge_ctx(tmp_path, 0)
    press_goals.seed_initial_goals(ctx)
    assert "to_route1" not in ctx.initial_goals


def test_out_of_order_bike_shop_does_not_drag(tmp_path):
    from pokeagent.campaign import badge_anchored
    ctx = badge_ctx(tmp_path, 0, {0xD35E: 66})   # standing in the bike shop, no badge
    press_goals.seed_initial_goals(ctx)
    assert "to_route1" not in ctx.initial_goals and "beat_misty" not in ctx.initial_goals
    assert badge_anchored(0) == set() and "bike_shop" not in badge_anchored(0b11)


def test_badge_gap_does_not_assume_skipped_badge():
    from pokeagent.campaign import badge_anchored
    got = badge_anchored(0b101)   # Boulder + Thunder, no Cascade
    assert "beat_brock" in got and "beat_misty" not in got and "beat_surge" not in got
    assert badge_anchored(0b11) >= got and "beat_misty" in badge_anchored(0b11)
