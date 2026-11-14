"""The Go-Explore cell key: bucketing at the edges, the monotone goals count, and the cell_id round trip."""
from __future__ import annotations

from pokeagent.goals import GOALS
from pokeagent.goexplore.cell import (Cell, cell_id, flag_popcount, from_log_row, from_snapshot,
                                      goals_reached, parse_id, party_bucket)
from pokeagent.novelty.features import Snapshot


def mon(species=177, level=5, exp=100, moves=(33,), ident=(1, 2)):
    return (species, level, exp, tuple(moves), ident)


def row(map_id, x, y):
    return {"map": map_id, "x": x, "y": y}


def test_block_bucketing():
    assert [from_log_row(row(1, x, 0), 0).bx for x in (0, 1, 2, 3)] == [0, 0, 0, 0]
    assert from_log_row(row(1, 4, 0), 0).bx == 1
    assert from_log_row(row(1, 7, 0), 0).bx == 1
    assert from_log_row(row(1, 8, 0), 0).bx == 2
    same_a, same_b = from_log_row(row(1, 0, 0), 0), from_log_row(row(1, 3, 3), 0)
    across = from_log_row(row(1, 4, 3), 0)
    assert same_a == same_b and same_a != across      # one block is one cell; over the edge is a new cell


def test_flag_bucket_edges():
    assert flag_popcount(bytes([0xFF, 0x01])) == 9
    assert from_snapshot(Snapshot(flags=bytes([0b111]) + bytes(319)), 0).flag4 == 0    # popcount 3 -> bucket 0
    assert from_snapshot(Snapshot(flags=bytes([0b1111]) + bytes(319)), 0).flag4 == 1   # popcount 4 -> bucket 1
    assert from_snapshot(Snapshot(flags=bytes([0b1]) + bytes(319)), 0).flag4 == 0      # one story flag, same cell


def test_party_level_bucket():
    assert party_bucket((mon(level=4),)) == (0, 1)
    assert party_bucket((mon(level=5),)) == (1, 1)
    assert party_bucket((mon(level=16), mon(species=25, level=8))) == (3, 2)
    assert party_bucket(()) == (0, 0)


def test_goals_count_is_monotone_along_the_ladder():
    for i, g in enumerate(GOALS):
        assert goals_reached(g) == i
    assert goals_reached("done") == len(GOALS)
    assert goals_reached("not_a_goal") is None
    seq = [goals_reached(g) for g in [*GOALS, "done"]]
    assert all(b > a for a, b in zip(seq, seq[1:]))


def test_from_snapshot_and_from_log_row():
    s = Snapshot(map=12, x=9, y=5, flags=bytes([0xFF]) + bytes(319), party=(mon(level=7),))
    assert from_snapshot(s, 7) == Cell(12, 2, 1, 7, 2, 1, 1)
    assert from_log_row(row(12, 9, 5), 7) == Cell(12, 2, 1, 7, None, None, None)


def test_cell_id_round_trip_with_none_fields():
    for c in (Cell(12, 2, 1, 7, 2, 1, 1), Cell(12, 2, 1, 7, None, None, None)):
        s = cell_id(c)
        assert ":" not in s and "/" not in s and "\\" not in s
        assert parse_id(s) == c
    assert cell_id(Cell(12, 2, 1, 7, 2, 1, 1)) == "12.2.1.7.2.1.1"
