"""Swarm rows: assembly from fixture files (runs/segments.json via the scorecard reader +
segment_grades, runs/swarm/agent_stats.jsonl) with blanks when files are absent, the
live/lost/dead mapping, and the next curriculum segment per slot."""
import json
import logging
import time

from pokeagent.snapshot import AgentSnapshot, Goal, Segment
from pokeagent.viewer import swarm_rows
from pokeagent.viewer.health_classify import Health, STALLED


def _snap(aid, seg="to_route1", done=("left_house",)):
    return AgentSnapshot(agent_id=aid, segment=Segment(id=seg),
                         goals=[Goal(id=g, name=g, status="done") for g in done])


def _fixture(tmp_path):
    """A solved+optimized to_route1: 20 solves in the window, the confirmed best first and 19
    slower solves since (the plateau fallback grades it optimized without a par)."""
    (tmp_path / "runs" / "swarm").mkdir(parents=True)
    now = time.time()
    attempts = [{"solved": True, "frames": 1000, "steps": 95, "run": "r1", "ts": now}]
    attempts += [{"solved": True, "frames": 1100, "steps": 105, "run": f"r{i}", "ts": now}
                 for i in range(2, 21)]
    (tmp_path / "runs" / "segments.json").write_text(json.dumps(
        {"version": 1, "stats": {"to_route1": {"n": 20, "solves": 20, "attempts": attempts,
                                               "best": {"frames": 1000, "run": "r1"},
                                               "confirmed": {"frames": 1000, "run": "r1"}}}}))
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
    assert a["grade"] == "solved,optimized"                 # grade_all's flags, not a stored field
    assert a["next"] == "to_viridian"                       # the leaf after to_route1 in chain order
    assert a["steps_s"] == "42.3" and a["rss"] == "150.5"
    assert a["health"] == STALLED and a["reason"] == "no new tiles"
    assert a["goal"] == "left_house"
    b = by["b"]
    assert b["segment"] == "n/a" and b["grade"] == "n/a" and b["next"] == "n/a"
    assert b["steps_s"] == "25" and b["health"] == "ok" and b["goal"] == ""


def test_unreadable_segments_json_warns_once(tmp_path, monkeypatch, caplog):
    """A torn read during the supervisor's save blanks the columns but is logged (once), not silent."""
    class Boom:
        @staticmethod
        def load(root): raise ValueError("torn json")
        @staticmethod
        def layout(doc): return []
    swarm_rows._logged.clear()
    monkeypatch.setattr(swarm_rows, "_seg_store", lambda: Boom)
    with caplog.at_level(logging.WARNING, logger="pokeagent.viewer.swarm_rows"):
        for _ in range(2):
            rows = swarm_rows.build_rows(tmp_path, ["a"], lambda aid: "live",
                                         lambda aid: None, {}, lambda aid: None)
    warns = [r for r in caplog.records if "segments.json unreadable" in r.getMessage()]
    assert len(warns) == 1 and rows[0]["next"] == "n/a"


def test_missing_files_yield_blanks(tmp_path):
    snaps = {"a": _snap("a")}
    rows = swarm_rows.build_rows(tmp_path, ["a"], lambda aid: "live",
                                 snaps.get, {"a": {"pid": 5}}, lambda aid: None)
    r = rows[0]
    # no scorecard data for the segment reads n/a (the grader's "stale" means data that went old)
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
