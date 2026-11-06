"""area_grind: bounded Route 2 grind and bounded top-off heal trips."""
from types import SimpleNamespace as NS

from pokeagent.explorer import area_grind
from pokeagent.explorer.planner import plan_step
from pokeagent.goals import GOALS


def ctx(battles=0):
    return NS(area_grind={}, battles=battles, heal_trips=0, last_plan_map=-1, log=lambda *a, **k: None)


def test_grind_lifts_after_the_step_cap():
    c = ctx()
    for _ in range(area_grind.AREA_GRIND_STEPS - 1):
        assert area_grind.capped_need(c, 0x0D, 13, 9, True) == 13
    assert area_grind.capped_need(c, 0x0D, 13, 9, True) == 0
    assert area_grind.capped_need(c, 0x0D, 13, 9, True) == 0  # stays lifted for the run


def test_grind_lifts_after_the_battle_cap():
    c = ctx()
    assert area_grind.capped_need(c, 0x0D, 13, 9, True) == 13
    c.battles = area_grind.AREA_GRIND_BATTLES
    assert area_grind.capped_need(c, 0x0D, 13, 9, True) == 0


def test_not_counted_elsewhere_or_at_target():
    c = ctx()
    for _ in range(1000):
        assert area_grind.capped_need(c, 0x01, 13, 9, True) == 13       # Viridian is not a grind map
        assert area_grind.capped_need(c, 0x0D, 13, 13, True) == 13      # already at target
        assert area_grind.capped_need(c, 0x0D, 13, 9, False) == 13      # before Route 2
    assert not c.area_grind.get("lifted")


def test_heal_trips_counted_on_entering_a_center_only():
    c = ctx()
    for m in (0x0D, 1, 41, 41, 1, 0x0D, 1, 41):
        area_grind.note_map(c, m)
    assert c.heal_trips == 2


def test_top_off_threshold_drops_to_half_after_the_trips():
    g = {g: True for g in GOALS[:GOALS.index("to_route2") + 1]}
    g.update(_hp=(25, 30), _level=10, _train_level=0)  # 83%: under the 90% top-off, over 50%
    first = plan_step({**g, "_heal_trips": 0}, {}, (41, 2, 5), "UP")  # inside the Viridian center
    assert first is not None and "to heal" not in first[1] and "HP 25/30" in first[1]
    later = plan_step({**g, "_heal_trips": 2}, {}, (41, 2, 5), "UP")
    assert later is None or "HP 25/30" not in later[1]  # no heal rule fires any more
    hurt = plan_step({**g, "_hp": (10, 30), "_heal_trips": 2}, {}, (41, 2, 5), "UP")
    assert hurt is not None and "HP 10/30" in hurt[1]  # below 50% still heals
