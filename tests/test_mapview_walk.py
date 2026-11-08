"""Facing and walk phase from position change, per preset style."""
from pokeagent.mapview.walk import LiveTracker, facing_from, phase_from


def test_facing_all_four_directions():
    assert facing_from((5, 5), (9, 5), True) == "RIGHT"
    assert facing_from((5, 5), (1, 5), True) == "LEFT"
    assert facing_from((5, 5), (5, 9), True) == "DOWN"
    assert facing_from((5, 5), (5, 1), True) == "UP"
    assert facing_from((5, 5), (7, 6), True) == "RIGHT"                   # |dx| >= |dy|: horizontal wins
    assert facing_from((5, 5), (6, 8), True) == "DOWN"


def test_facing_no_change_keeps_last_and_none_keeps_last():
    assert facing_from((5, 5), (5, 5), True, "UP") == "UP"
    assert facing_from(None, (5, 5), True) == "DOWN"                      # default


def test_facing_side_on_only_left_right():
    assert facing_from((5, 5), (9, 5), False) == "RIGHT"
    assert facing_from((5, 5), (1, 5), False) == "LEFT"
    assert facing_from((5, 5), (5, 9), False, "LEFT") == "LEFT"           # vertical keeps last
    assert facing_from((5, 5), (5, 5), False, "RIGHT") == "RIGHT"
    assert facing_from(None, (5, 5), False, "DOWN") == "RIGHT"            # never UP/DOWN


def test_phase_alternates_every_six_steps():
    assert phase_from(3, True, True) == 1
    assert phase_from(7, True, True) == 2
    assert phase_from(13, True, True) == 1
    assert phase_from(3, False, True) == 0                                # unmoved
    assert phase_from(3, True, False) == 0                                # preset without frames


def test_tracker_remembers_facing_and_counts_moves():
    t = LiveTracker(True)
    assert t.update("a", "1-1", 5, 5) == ("DOWN", 0)
    assert t.update("a", "1-1", 9, 5) == ("RIGHT", 1)
    assert t.update("a", "1-1", 9, 5) == ("RIGHT", 0)                     # same spot: no move
    assert t.update("a", "2-1", 0, 0) == ("RIGHT", 0)                     # area change: keeps last
