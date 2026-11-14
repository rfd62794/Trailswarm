"""The pure archive: the strict score-replace rule, n_seen kept, best-per-goals, children."""
from __future__ import annotations

from pokeagent.goexplore.archive import Archive, Entry


def ent(cid, goals=0, steps=100, hp=0.5, **kw):
    return Entry(cid=cid, state=f"cells/{cid}.state", goals=goals, steps=steps, hp=hp, **kw)


def test_new_cell_is_inserted():
    a = Archive()
    assert a.offer(ent("1.0.0.0.0.0.0")) is True
    assert len(a) == 1
    a.mark_seen("1.0.0.0.0.0.0")
    a.mark_seen("not.a.cell")                    # unknown cid: ignored, no KeyError
    assert a.entries["1.0.0.0.0.0.0"].n_seen == 1


def test_better_score_replaces_and_keeps_n_seen():
    a = Archive()
    a.offer(ent("c", goals=0, steps=10, n_seen=3))
    assert a.offer(ent("c", goals=1, steps=99)) is True
    assert a.entries["c"].goals == 1 and a.entries["c"].n_seen == 3


def test_replace_rule_order():
    a = Archive()
    a.offer(ent("c", goals=1, steps=50))
    assert not a.offer(ent("c", goals=0, steps=10))          # fewer steps loses to more goals
    assert a.offer(ent("c", goals=1, steps=40))              # same goals, fewer steps wins
    assert not a.offer(ent("c", goals=1, steps=60))          # same goals, more steps loses
    assert a.offer(ent("c", goals=1, steps=40, hp=0.9))      # same goals+steps, higher hp wins


def test_equal_or_worse_score_is_rejected():
    a = Archive()
    a.offer(ent("c", goals=1, steps=50, hp=0.5))
    old = a.entries["c"]
    assert not a.offer(ent("c", goals=1, steps=50, hp=0.5))  # equal score
    assert a.entries["c"] is old
    assert not a.offer(ent("c", goals=1, steps=50, hp=0.4))  # strictly worse
    assert a.entries["c"] is old


def test_best_per_goals_and_children_of():
    a = Archive()
    a.offer(ent("z", goals=0, steps=10))
    a.offer(ent("a", goals=0, steps=10, parent="z"))   # score tie with z: the smaller cid wins
    a.offer(ent("m", goals=1, steps=5, parent="z"))
    assert a.best_per_goals() == {"a", "m"}
    assert a.children_of("z") == ["a", "m"]
    assert a.children_of("a") == []


def test_entry_dict_round_trip_and_unknown_keys():
    e = Entry(cid="c", state="cells/c.state", goals=2, steps=9, hp=0.7, n_seen=4,
              novelty=1.5, parent="p", lineage="promoted")
    assert Entry.from_dict(e.to_dict()) == e
    assert Entry.from_dict(e.to_dict() | {"future_key": 1}) == e
    minimal = Entry.from_dict({"cid": "c", "state": "s", "goals": 0, "steps": 3})
    assert (minimal.hp, minimal.n_seen, minimal.novelty) == (0.0, 0, 0.0)
    assert minimal.parent is None and minimal.lineage == "organic"
