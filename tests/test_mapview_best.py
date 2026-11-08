import numpy as np

from pokeagent.mapview.best import best_index
from pokeagent.mapview.ghosts import Ghost


def ghost(run, agent="w", outcome="ok", n=5, last_idx=0, last_x=50.0):
    ai = np.zeros(n, np.int16)
    ai[-1] = last_idx
    xs = np.zeros(n, np.float32)
    xs[-1] = last_x
    return Ghost(run, agent, outcome, 2, ai, xs, np.zeros(n, np.float32))


def test_furthest_by_area_rank_then_x():
    gs = [ghost("r1", last_idx=0, last_x=300), ghost("r2", last_idx=1, last_x=5)]
    assert best_index(gs, ["a-1", "b-1"]) == 1                      # deeper area beats bigger x


def test_tie_goes_to_shorter_then_earlier_run():
    a = ghost("r9", n=10, last_idx=0, last_x=50)
    b = ghost("r2", n=4, last_idx=0, last_x=50)
    c = ghost("r1", n=4, last_idx=0, last_x=50)
    assert best_index([a, b, c], ["a-1"]) == 2                      # fewer points beats a, then r1 < r2
    assert best_index([b, c], ["a-1"]) == 1                         # same length: earlier run id


def test_unknown_last_area_ranks_below_known_ones():
    a = ghost("r1", last_idx=-1, last_x=9999)
    b = ghost("r2", last_idx=0, last_x=1)
    assert best_index([a, b], ["a-1"]) == 1
    assert best_index([a], ["a-1"]) == 0                            # still pickable alone


def test_labelled_best_that_is_not_furthest_loses():
    a = ghost("r1", outcome="best", last_idx=0, last_x=10)
    b = ghost("r2", outcome="death", last_idx=0, last_x=80)
    assert best_index([a, b], ["a-1"]) == 1                         # the label is not special


def test_none_for_no_ghosts():
    assert best_index([], ["a-1"]) is None
