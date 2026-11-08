"""Swarm rows: assembly from fixture files (runs/segments.json via the scorecard reader,
runs/swarm/agent_stats.jsonl) with blanks when files are absent, the live/lost/dead mapping,
and the next curriculum segment per slot."""
import json

from pokeagent.snapshot import AgentSnapshot, Goal, Segment
from pokeagent.viewer import swarm_rows
from pokeagent.viewer.health_classify import Health, STALLED


def _snap(aid, seg="to_route1", done=("left_house",)):
    return AgentSnapshot(agent_id=aid, segment=Segment(id=seg),
                         goals=[Goal(id=g, name=g, status="done") for g in done])


def _fixture(tmp_path):
    (tmp_path / "runs" / "swarm").mkdir(parents=True)
    (tmp_path / "runs" / "segments.json").write_text(json.dumps(
        {"version": 1, "stats": {"to_route1": {"grade": "B", "n": 4, "solves": 3,
                                               "attempts": [], "best": None, "confirmed": None}}}))
    (tmp_path / "runs" / "swarm" / "agent_stats.jsonl").write_text(
        "\n".join([json.dumps({"ts": 1, "agent": "a", "pid": 11, "rss_mb": 150.5, "steps_per_s": 42.3}),
                   json.dumps({"ts": 2, "agent": "b", "pid": 12, "rss_mb": 99, "steps_per_s": 25})]))


def test_rows_from_fixture_files(tmp_path):
    _fixture(tmp_path)
    snaps = {"a": _snap("a"), "b": _snap("b", seg="", done=())}
    entries = {"a": {"id": "a", "pid": 11}, "b": {"id": "b", "pid": 12}}
    health = {"a": Health(STALLED, "no new tiles")}
    rows = swarm_rows.build_rows(tmp_path, ["a", "b"], lambda aid: "live",
                                 snaps.get, entries, lambda aid: health.get(aid))
    by = {r["id"]: r for r in rows}
    a = by["a"]
    assert a["state"] == "live" and a["segment"] == "to_route1"
    assert a["grade"] == "B" and a["next"] == "to_viridian"   # the leaf after to_route1 in chain order
    assert a["steps_s"] == "42.3" and a["rss"] == "150.5"
    assert a["health"] == STALLED and a["reason"] == "no new tiles"
    assert a["goal"] == "left_house"
    b = by["b"]
    assert b["segment"] == "n/a" and b["grade"] == "n/a" and b["next"] == "n/a"
    assert b["steps_s"] == "25" and b["health"] == "ok" and b["goal"] == ""


def test_missing_files_yield_blanks(tmp_path):
    snaps = {"a": _snap("a")}
    rows = swarm_rows.build_rows(tmp_path, ["a"], lambda aid: "live",
                                 snaps.get, {"a": {"pid": 5}}, lambda aid: None)
    r = rows[0]
    assert r["grade"] == "n/a" and r["steps_s"] == "" and r["rss"] == "" and r["health"] == "ok"


def test_state_mapping():
    assert swarm_rows._state("live", True) == "live"
    assert swarm_rows._state("stale", True) == "lost"      # heartbeat overdue but not dead
    assert swarm_rows._state("lost", True) == "dead"       # 10 s silent, or registry entry gone
    assert swarm_rows._state("live", False) == "dead"


def test_rows_cover_registry_agents_without_snapshots(tmp_path):
    rows = swarm_rows.build_rows(tmp_path, [], lambda aid: "lost",
                                 lambda aid: None, {"gone": {"pid": 1}}, lambda aid: None)
    assert rows[0]["id"] == "gone" and rows[0]["state"] == "dead"
    assert rows[0]["segment"] == "n/a" and rows[0]["goal"] == ""


def test_fake_agents_are_not_dead(tmp_path):
    """--fake mode has no registry entries; an agent the model has seen is not 'dead'."""
    snaps = {"fake-1": _snap("fake-1")}
    rows = swarm_rows.build_rows(tmp_path, ["fake-1"], lambda aid: "live",
                                 snaps.get, {}, lambda aid: None)
    assert rows[0]["state"] == "live"


def test_store_round_trip_and_copies(tmp_path):
    from pokeagent.viewer.model import ViewerModel
    from pokeagent.viewer.sources import FakeSource
    m = ViewerModel()
    m.poll([FakeSource("a", [_snap("a")])]); m.drain()
    store = swarm_rows.SwarmRowStore()
    store.refresh(tmp_path, m, {"a": {"pid": 7}}, None)
    rows = store.rows()
    assert rows[0]["id"] == "a" and rows[0]["segment"] == "to_route1"
    rows[0]["id"] = "mutated"                                # the store hands out copies
    assert store.rows()[0]["id"] == "a"
