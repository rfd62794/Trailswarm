"""Viewer health (pure, no Dear PyGui): run_pid, anomalies_for, classify, break_summary, HealthStore."""
import json
import os
import time
from datetime import datetime
from pathlib import Path


from pokeagent.invariants.findings import ERROR, INFO, WARN, Finding
from pokeagent.viewer import health as hm

NOW = datetime(2026, 11, 7, 16, 0, 0).timestamp()          # fixed "now" for all freshness maths
AGENT = "explore-24324"
STARTED = datetime(2026, 11, 7, 15, 0, 0).timestamp()


def run(day="20261107", hms="150000", pid="24324"):
    return f"explore-{day}-{hms}-{pid}"


def iso(epoch):
    return datetime.fromtimestamp(epoch).isoformat(timespec="seconds")


def dossier(run_name, t_epoch, **kw):
    d = {"run": run_name, "t": iso(t_epoch), "reason": "no new goal and only 3 new tiles",
         "likely_cause": "pressing into a sprite: person-not-wall class", "signature": {"map": 0}}
    d.update(kw)
    return d


def anomaly(run_name, mtime, step=2940, atype="endless_battle", png="a.png", state="a.state"):
    return hm.AnomalyRef(run=run_name, step=step, type=atype, png=Path(png) if png else None,
                         state=Path(state) if state else None, mtime=mtime)


# --- run_pid / anomalies_for ------------------------------------------------------

def test_run_pid():
    assert hm.run_pid("explore-20261107-153827-24324") == "24324"
    assert hm.run_pid("explore-17696") == "17696"
    assert hm.run_pid("no-pid-here") is None
    assert hm.run_pid("") is None


def test_anomalies_for_pairs_and_sorts(tmp_path):
    adir = tmp_path / "runs" / "anomalies"
    adir.mkdir(parents=True)
    run_name = "explore-20261105-224401-19936"
    (adir / f"{run_name}-2940-endless_battle.png").write_bytes(b"x")
    (adir / f"{run_name}-2940-endless_battle.state").write_bytes(b"y")
    (adir / f"{run_name}-100-menuloop.png").write_bytes(b"z")          # unpaired .png
    (adir / "junk.png").write_bytes(b"j")                              # no <step>
    (adir / "a-b-c.state").write_bytes(b"j")                           # step not numeric
    (adir / "readme.txt").write_text("hi")
    for i, p in enumerate(sorted(adir.iterdir())):                     # distinct mtimes, newest = .png pair
        os.utime(p, (100 + i, 100 + i))
    os.utime(adir / f"{run_name}-2940-endless_battle.png", (999, 999))
    os.utime(adir / f"{run_name}-2940-endless_battle.state", (999, 999))
    out = hm.anomalies_for(tmp_path)
    assert len(out) == 2
    first = out[0]
    assert (first.run, first.step, first.type) == (run_name, 2940, "endless_battle")
    assert first.png is not None and first.state is not None and first.mtime == 999
    assert out[1].type == "menuloop" and out[1].png is not None and out[1].state is None


def test_anomalies_for_cause_hint_and_junk_jsonl(tmp_path):
    adir = tmp_path / "runs" / "anomalies"
    adir.mkdir(parents=True)
    run_name = "explore-20261105-224401-19936"
    (adir / f"{run_name}-2940-endless_battle.png").write_bytes(b"x")
    jl = tmp_path / "runs" / "anomalies.jsonl"
    jl.write_text(json.dumps({"run": run_name, "step": 2940, "cause_hint": "loop", "provenance": "synthetic"})
                  + "\n{bad json\n", encoding="utf-8")
    (ref,) = hm.anomalies_for(tmp_path)
    assert ref.cause_hint == "loop" and ref.provenance == "synthetic"


def test_anomalies_for_missing_dir(tmp_path):
    assert hm.anomalies_for(tmp_path) == []


# --- classify ---------------------------------------------------------------------

def test_classify_ok_when_nothing_joins():
    h = hm.classify(AGENT, STARTED, [], [], NOW)
    assert h == hm.Health(hm.OK, "")
    other = dossier(run(pid="99999"), NOW - 10)
    assert hm.classify(AGENT, STARTED, [other], [], NOW).state == hm.OK


def test_classify_join_requires_run_start_at_or_after_slack():
    inside = dossier(run(hms="145900"), NOW - 10)      # run started at STARTED-60s: within JOIN_SLACK_S
    assert hm.classify(AGENT, STARTED, [inside], [], NOW).state == hm.STALLED
    before = dossier(run(hms="145700"), NOW - 10)      # run started at STARTED-180s: outside slack
    assert hm.classify(AGENT, STARTED, [before], [], NOW).state == hm.OK
    # a same-pid run from the previous day never joins
    yesterday = dossier(run(day="20261106", hms="150000"), NOW - 10)
    assert hm.classify(AGENT, STARTED, [yesterday], [], NOW).state == hm.OK


def test_classify_join_on_pid_alone_when_started_unknown():
    fresh = dossier(run(), NOW - 10)
    assert hm.classify(AGENT, None, [fresh], [], NOW).state == hm.STALLED


def test_classify_stalled_slow_boundaries():
    at = lambda age: hm.classify(AGENT, STARTED, [dossier(run(), NOW - age)], [], NOW).state
    assert at(hm.STALL_FRESH_S) == hm.STALLED
    assert at(hm.STALL_FRESH_S + 1) == hm.SLOW
    assert at(hm.STALL_SLOW_S) == hm.SLOW
    assert at(hm.STALL_SLOW_S + 1) == hm.OK


def test_classify_anomaly_boundaries_and_reason():
    ref = anomaly(run(), NOW - hm.ANOMALY_FRESH_S)
    h = hm.classify(AGENT, STARTED, [], [ref], NOW)
    assert h.state == hm.ANOMALY and h.anomaly is ref
    old = anomaly(run(), NOW - hm.ANOMALY_FRESH_S - 1)
    assert hm.classify(AGENT, STARTED, [], [old], NOW).state == hm.OK


def test_classify_priority_anomaly_beats_stalled():
    d = dossier(run(), NOW - 10)
    a = anomaly(run(), NOW - 10)
    assert hm.classify(AGENT, STARTED, [d], [a], NOW).state == hm.ANOMALY


def test_classify_stalled_reason_and_newest_dossier_wins():
    d = dossier(run(), NOW - 10)
    h = hm.classify(AGENT, STARTED, [d], [], NOW)
    assert h.state == hm.STALLED and h.dossier_run == run()
    assert "pressing into a sprite" in h.reason and "3 new tiles" in h.reason and len(h.reason) <= 120
    slow = dossier(run(), NOW - 2000)
    h2 = hm.classify(AGENT, STARTED, [slow, d], [], NOW)
    assert h2.state == hm.STALLED                       # the newest joined dossier decides


# --- break_summary / store ----------------------------------------------------------

def test_break_summary_counts_and_top():
    fs = [Finding("warps", ERROR, "k", f"err {i}") for i in range(5)]
    fs += [Finding("warps", WARN, "k", "w"), Finding("warps", INFO, "k", "i")]
    s = hm.break_summary(fs)
    assert s["errors"] == 5 and s["warns"] == 1 and s["top"] == ["err 0", "err 1", "err 2"]


def _write_dossier(root, d):
    (root / "runs" / "stalls").mkdir(parents=True, exist_ok=True)
    (root / "runs" / "stalls" / f"{d['run']}.json").write_text(json.dumps(d), encoding="utf-8")


def test_store_refresh_reads_only_on_changed_mtime(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(hm, "load_dossiers", lambda root: calls.append("dossiers") or [])
    monkeypatch.setattr(hm, "anomalies_for", lambda root: calls.append("anomalies") or [])
    store = hm.HealthStore(clock=lambda: NOW)
    store.refresh(tmp_path, NOW)                        # nothing exists: stats only, no reads
    assert calls == []
    _write_dossier(tmp_path, dossier(run(), NOW - 10))
    store.refresh(tmp_path, NOW)                        # stalls dir appeared: one read
    store.refresh(tmp_path, NOW)                        # unchanged mtimes: no reads
    assert calls == ["dossiers"]
    stalls_dir = tmp_path / "runs" / "stalls"
    os.utime(stalls_dir, (NOW + 50, NOW + 50))          # a changed dir mtime -> re-read
    store.refresh(tmp_path, NOW)
    assert calls == ["dossiers", "dossiers"]


def test_store_refresh_survives_corrupt_dossier(tmp_path):
    (tmp_path / "runs" / "stalls").mkdir(parents=True)
    (tmp_path / "runs" / "stalls" / f"{run()}.json").write_text("{bad json", encoding="utf-8")
    store = hm.HealthStore(clock=lambda: NOW)
    store.refresh(tmp_path, NOW)                        # never raises
    assert store.health(AGENT, STARTED).state == hm.OK


def test_store_health_joins_and_fake_overrides(tmp_path):
    _write_dossier(tmp_path, dossier(run(), NOW - 10))
    store = hm.HealthStore(clock=lambda: NOW)
    store.refresh(tmp_path, NOW, {AGENT: STARTED, "explore-99999": STARTED})
    assert store.health(AGENT, STARTED).state == hm.STALLED
    assert store.health("explore-99999", STARTED).state == hm.OK
    store.fake_refresh(["fake-1", "fake-2", "fake-3"], NOW)
    assert store.health("fake-1", None).state == hm.STALLED
    assert store.health("fake-2", None).state == hm.ANOMALY
    assert store.health("fake-3", None).state == hm.OK


def test_request_invariants_one_worker_and_unavailable(tmp_path, monkeypatch):
    calls = []

    def boom(_runs_dir):
        calls.append(1)
        raise RuntimeError("no rom")

    monkeypatch.setattr(hm, "run_all", boom)
    store = hm.HealthStore()
    store.request_invariants(tmp_path, NOW)
    store.request_invariants(tmp_path, NOW)             # one already running: refused
    deadline = time.time() + 5
    while store.breaks() is None and time.time() < deadline:
        time.sleep(0.01)
    assert calls == [1]
    assert "unavailable" in store.breaks()
    # next request allowed again after the worker finished (and INVARIANT_EVERY_S elapsed)
    monkeypatch.setattr(hm, "run_all", lambda _r: [Finding("warps", ERROR, "k", "e")])
    store.request_invariants(tmp_path, NOW + hm.INVARIANT_EVERY_S + 1)
    deadline = time.time() + 5
    while store.breaks() == {"unavailable": "no rom"} and time.time() < deadline:
        time.sleep(0.01)
    assert store.breaks()["errors"] == 1


def test_store_reads_do_no_file_io(monkeypatch):
    def _raise(*a, **k):
        raise AssertionError("file I/O on the render path")

    for name in ("open", "read_text", "glob", "stat"):
        monkeypatch.setattr(Path, name, _raise)
    store = hm.HealthStore()
    assert store.health(AGENT, STARTED).state == hm.OK
    assert store.breaks() is None
    assert store.anomalies() == []
    assert store.provenance(run()) == ""


def test_failed_read_leaves_mtime_unrecorded_and_retries(tmp_path, monkeypatch, caplog):
    _write_dossier(tmp_path, dossier(run(), NOW - 10))
    calls = []

    def flaky(root):
        calls.append(1)
        if len(calls) < 3:
            raise OSError("disk hiccup")
        return [dossier(run(), NOW - 10)]

    monkeypatch.setattr(hm, "load_dossiers", flaky)
    store = hm.HealthStore(clock=lambda: NOW)
    with caplog.at_level("WARNING", logger=hm.log.name):
        store.refresh(tmp_path, NOW, {AGENT: STARTED})
        assert store.last_error and "OSError" in store.last_error and "disk hiccup" in store.last_error
        assert store._mtimes.get("stalls") is None            # not recorded after a failed read
        store.refresh(tmp_path, NOW, {AGENT: STARTED})        # same dir mtime, still retried
    assert len(calls) == 2
    assert sum("health read failed" in r.message for r in caplog.records) == 1   # logged once, not per tick
    store.refresh(tmp_path, NOW, {AGENT: STARTED})            # third try succeeds
    assert store.last_error is None
    assert store.health(AGENT, STARTED).state == hm.STALLED
    store.refresh(tmp_path, NOW, {AGENT: STARTED})            # recorded now: no further read
    assert len(calls) == 3


def test_badge_text_shows_read_error():
    assert hm.badge_text({}, {"errors": 0}).endswith("invariants: 0 errors")
    assert hm.badge_text({}, {"errors": 0}, "dossiers: OSError: x").endswith("| read error")


def test_health_does_no_classification_after_refresh(tmp_path, monkeypatch):
    _write_dossier(tmp_path, dossier(run(), NOW - 10))
    store = hm.HealthStore(clock=lambda: NOW)
    store.refresh(tmp_path, NOW, {AGENT: STARTED})

    def _raise(*a, **k):
        raise AssertionError("classify on the render path")

    monkeypatch.setattr(hm, "classify", _raise)
    assert store.health(AGENT, STARTED).state == hm.STALLED
    assert store.health("unknown-1", None).state == hm.OK


def test_started_map_tolerates_bad_entries():
    got = hm.started_map({"a": {"started": "12.5"}, "b": {"started": "x"}, "c": {}, "d": None})
    assert got == {"a": 12.5, "b": None, "c": None, "d": None}
