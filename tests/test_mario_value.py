"""Pure logic of the Mario Land style value: accumulation, replacement and best ordering. No ROM, no pyboy."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import mario_value as V  # noqa: E402


def test_value_accumulates_per_kind():
    assert V.add_event(0, "kill", 100) == 100 + V.KILL_WEIGHT
    assert V.add_event(0, "coin", 10) == 10 + V.COIN_WEIGHT
    assert V.add_event(0, "block", 50) == 50 + V.BLOCK_WEIGHT
    total = 0
    for kind, pts in [("kill", 100), ("coin", 10), ("block", 50)]:
        total = V.add_event(total, kind, pts)
    assert total == 160 + V.KILL_WEIGHT + V.COIN_WEIGHT + V.BLOCK_WEIGHT


def test_timer_bonus_is_excluded():
    assert V.add_event(500, "bonus", 4000) == 500


def test_block_weight_is_real():
    assert V.BLOCK_WEIGHT > 0
    assert V.event_value("block", 0) == V.BLOCK_WEIGHT


def test_replacement_decision():
    assert V.should_replace(100, 3, 101, 3)
    assert V.should_replace(100, 3, 500, 4)
    assert not V.should_replace(100, 3, 500, 2)      # fewer lives refused
    assert not V.should_replace(100, 3, 100, 3)      # equal value refused
    assert not V.should_replace(100, 3, 50, 3)


def doc(world, bucket, value=None):
    d = {"key": [list(world), bucket]}
    if value is not None:
        d["value"] = value
    return d


def test_best_ordering():
    far, near = doc((1, 2), 5, 0), doc((1, 1), 40, 9999)
    assert V.best_order(far) > V.best_order(near)                       # distance beats value
    assert V.best_order(doc((1, 1), 7, 300)) > V.best_order(doc((1, 1), 7, 200))   # value breaks ties
    assert V.best_order(doc((1, 1), 7)) == V.best_order(doc((1, 1), 7, 0))         # missing value is 0
    assert V.best_order(doc((1, 1), 7, 1)) > V.best_order(doc((1, 1), 7))


def test_replacement_does_not_regress_position():
    assert V.should_replace(100, 3, 200, 3, old_progress=10, new_progress=10)
    assert V.should_replace(100, 3, 200, 3, old_progress=10, new_progress=15)
    assert not V.should_replace(100, 3, 200, 3, old_progress=10, new_progress=9)


def test_fails_carry_unless_a_bucket_further():
    n = V.PROGRESS_STEP
    assert V.carried_fails(30, 10, 10) == 30          # value-only growth keeps the death count
    assert V.carried_fails(30, 10, 11) == 30          # a one-pixel gain does not reset it
    assert V.carried_fails(30, 10, 10 + n - 1) == 30
    assert V.carried_fails(30, 10, 10 + n) == 0       # a full bucket further resets it


def test_tally_needs_consecutive_drops():
    assert not V.is_tally(True, False)    # isolated drop: an ordinary tick
    assert not V.is_tally(False, True)
    assert not V.is_tally(False, False)
    assert V.is_tally(True, True)         # consecutive drops: the level-end tally
