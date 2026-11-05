import pytest

from pokeagent.snapshot import (SCHEMA_VERSION, AgentSnapshot, DriverWindow, Event, Goal,
                                PartyMon, Screen)


def full():
    return AgentSnapshot(agent_id="a1", kind="hybrid", step=5, goals=[Goal("g", "Get Pokedex", "current", 3)],
                         screen=Screen(party=[PartyMon("PIKACHU", 5, 10, 20)], money=300),
                         recent=[Event(1, "rl", "x")], human_hold=True, updated_at=1.5)


def test_round_trip():
    s = full()
    assert AgentSnapshot.from_dict(s.to_dict()) == s


def test_unknown_keys_ignored_and_missing_default():
    s = AgentSnapshot.from_dict({"agent_id": "a", "bogus": 1, "thinking": {"want": "x", "zzz": 2}})
    assert s.thinking.want == "x" and s.state == "running" and s.drivers["rl"] == 0


def test_errors():
    with pytest.raises(ValueError):
        AgentSnapshot.from_dict({"kind": "x"})
    with pytest.raises(ValueError):
        AgentSnapshot.from_dict({"agent_id": "a", "v": SCHEMA_VERSION + 1})


def test_recent_truncated():
    s = AgentSnapshot(agent_id="a", recent=[Event(i, "rl", "t") for i in range(30)])
    d = s.to_dict()
    assert len(d["recent"]) == 20 and d["recent"][-1]["step"] == 29
    assert len(AgentSnapshot.from_dict({"agent_id": "a", "recent": [{"step": i} for i in range(30)]}).recent) == 20


def test_driver_window():
    w = DriverWindow()
    for i in range(150):
        w.add("rl" if i < 100 else "human")
    c = w.counts()
    assert set(c) >= {"explorer", "rl", "human", "claude"}
    assert c["human"] == 50 and c["rl"] == 50 and c["explorer"] == 0 and sum(c.values()) == 100


def test_from_dict_defensive():
    s = AgentSnapshot.from_dict({"agent_id": "a", "drivers": "oops", "goals": {"x": 1}, "recent": 5,
                                 "screen": {"party": "nope", "money": 3}})
    assert s.drivers == {"explorer": 0, "rl": 0, "human": 0, "claude": 0}
    assert s.goals == [] and s.recent == [] and s.screen.party == [] and s.screen.money == 3
    s = AgentSnapshot.from_dict({"agent_id": "a", "goals": [1, None, {"id": "g"}, "x"],
                                 "recent": ["a", {"step": 2}], "screen": {"party": [3, {"species": "P"}]},
                                 "thinking": "bad", "segment": None, "sees": []})
    assert [g.id for g in s.goals] == ["g"] and [e.step for e in s.recent] == [2]
    assert [p.species for p in s.screen.party] == ["P"]
    assert s.thinking.want == "" and s.sees.rows == []
